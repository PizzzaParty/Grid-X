from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import time
from .. import database, models, schemas
from ..aggregation import aggregate_pytorch_weights
from .front_job import upload_bytes_to_supabase, SUBTASK_REWARD_CREDITS


router = APIRouter()

@router.post("/register")
def register_agent(data: schemas.AgentRegister, db: Session = Depends(database.get_db)):
    """
    Registers a new agent (machine) and links it to a human user via email.
    """
    
    # 1. FIND THE HUMAN OWNER
    # We use the email provided by the script to find the User ID
    raw_email = data.email
    clean_email = raw_email.strip().strip('"').strip("'").lower()
    print(f"DEBUG: Registering agent with email: '{clean_email}' (Original: '{raw_email}')")
    
    owner = db.query(models.User).filter(models.User.email == clean_email).first()
    print(f"DEBUG: Owner found: {owner}")
    
    if not owner:
        # If the email doesn't exist, the agent can't register
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Owner email not found. Please register on the website first."
        )

    # 2. CHECK IF AGENT ALREADY EXISTS
    # We look up the Agent ID (which is saved in the script's local JSON file)
    agent = db.query(models.Agent).filter(models.Agent.id == data.id).first()

    current_time = datetime.now(timezone.utc)

    if agent:
        # SCENARIO A: RETURNING AGENT
        # Just update the specs and set to IDLE
        agent.owner_id = owner.id  # Ensure ownership is correct
        agent.status = "IDLE"
        agent.gpu_model = data.gpu_model
        agent.ram_total = data.ram_total
        agent.last_heartbeat = current_time
        
        db.commit()
        return {"message": f"Welcome back, Agent {data.id}", "status": "linked"}

    else:
        # SCENARIO B: NEW AGENT
        # Create a new row
        new_agent = models.Agent(
            id=data.id,
            owner_id=owner.id,
            status="IDLE",
            gpu_model=data.gpu_model,
            ram_total=data.ram_total,
            last_heartbeat=current_time
        )
        
        db.add(new_agent)
        db.commit()
        return {"message": f"New Agent {data.id} registered!", "status": "created"}


@router.post("/heartbeat")
def report_heartbeat(beat: schemas.AgentHeartbeat, db: Session = Depends(database.get_db)):
    """
    Updates the 'last_heartbeat' timestamp and status of an agent.
    """
    # 1. Find the agent in the DB
    agent = db.query(models.Agent).filter(models.Agent.id == beat.id).first()

    # 2. If agent not found (maybe database was wiped?)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not registered")

    # 3. Update the fields
    agent.last_heartbeat = datetime.now(timezone.utc) # "I am alive right now"
    agent.status = beat.status                        # "I am currently IDLE/BUSY"

    # 4. Save changes
    db.commit()

    return {"message": "Heartbeat received", "server_time": agent.last_heartbeat}

# In routers/agent.py

@router.post("/request_task", response_model=schemas.TaskResponse)
def request_task(data: schemas.TaskRequest, db: Session = Depends(database.get_db)):
    """
    Agent asks: "Is there any work?"
    Server checks for PENDING subtasks.
    """
    
    # 1. FIND A PENDING SUBTASK
    # We lock the first one we find that hasn't been started yet
    # (Optional: You could filter by GPU requirements here later)
    subtask = db.query(models.Subtask).filter(
        models.Subtask.status == "PENDING"
    ).first()

    # 2. IF NO WORK, RETURN EMPTY
    if not subtask:
        return {"task_id": None}

    # 3. IF WORK FOUND: ASSIGN IT TO AGENT
    # Get the parent Job to access the Code/Req URLs
    job = subtask.job 
    
    # Check if parent job is valid (sanity check)
    if not job:
        return {"task_id": None}

    # UPDATE DATABASE (Lock the task)
    subtask.status = "RUNNING"
    subtask.assigned_to = data.agent_id
    
    # Also update the Agent status to BUSY
    agent = db.query(models.Agent).filter(models.Agent.id == data.agent_id).first()
    if agent:
        agent.status = "BUSY"

    db.commit()

    # 5. RETURN THE INSTRUCTIONS
    print(f"🚀 Assigning Subtask {subtask.id} to Agent {data.agent_id}")
    
    return {
        "task_id": subtask.id,
        "job_id": job.id,
        "code_url": job.original_code_url,      # The Python Script
        "requirements_url": job.original_req_url, # The Pip packages
        "chunk_data_url": subtask.chunk_file_url  # The specific slice of data
    }

@router.post("/upload_result")
async def upload_result(
    agent_id: str = Form(...),
    task_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db)
):
    """
    Worker uploads the result file (model.pth) directly.
    """
    # 1. Verify Task Ownership
    subtask = db.query(models.Subtask).filter(models.Subtask.id == task_id).first()
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")
        
    # Optional: Verify agent_id matches subtask.assigned_to 
    
    # 2. Read File
    file_bytes = await file.read()
    
    # 3. Upload to Supabase
    # Path: jobs/{job_id}/results/{task_id}_model.pth
    file_path = f"jobs/{subtask.job_id}/results/{task_id}_model.pth"
    
    # We use application/octet-stream for .pth files
    url = upload_bytes_to_supabase(file_bytes, file_path, "application/octet-stream")
    
    return {"url": url}


@router.post("/complete_task")
def complete_task(data: schemas.TaskComplete, db: Session = Depends(database.get_db)):
    """
    Agent reports work is done.
    1. Mark Subtask as COMPLETED.
    2. Free up the Agent (IDLE).
    3. Check if the entire Job is finished.
    """
    
    # 1. FIND THE SUBTASK
    subtask = db.query(models.Subtask).filter(models.Subtask.id == data.task_id).first()
    
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")
        
    # Security Check: Ensure this agent was actually the one assigned
    if subtask.assigned_to != data.agent_id:
        raise HTTPException(status_code=400, detail="This task was not assigned to you")

    # 2. UPDATE SUBTASK STATUS
    subtask.status = "COMPLETED"
    subtask.result_file_url = data.result_url
    subtask.completed_at = datetime.now(timezone.utc)
    
    # 3. FREE THE AGENT and credit the seller
    agent = db.query(models.Agent).filter(models.Agent.id == data.agent_id).first()
    if agent:
        agent.status = "IDLE"
        agent.last_heartbeat = datetime.now(timezone.utc)
        # Credit the agent's owner for completing the task
        seller = db.query(models.User).filter(models.User.id == agent.owner_id).first()
        if seller:
            seller.credits += SUBTASK_REWARD_CREDITS
            print(f"💰 Credited {SUBTASK_REWARD_CREDITS} credit(s) to seller {seller.email}")

    # CRITICAL: Commit the status update BEFORE checking if all tasks are done
    # Otherwise the query won't see this task as COMPLETED yet!
    db.commit()

    # 4. CHECK IF PARENT JOB IS DONE
    # We count how many subtasks are NOT completed yet for this job
    remaining_tasks = db.query(models.Subtask).filter(
        models.Subtask.job_id == subtask.job_id,
        models.Subtask.status != "COMPLETED"
    ).count()
    
    print(f"🔍 Job {subtask.job_id}: {remaining_tasks} tasks remaining")
    
    if remaining_tasks == 0:
        # All tasks are done! Mark the Job as COMPLETED.
        parent_job = db.query(models.Job).filter(models.Job.id == subtask.job_id).first()
        if parent_job:
            parent_job.status = "COMPLETED"
            print(f"🎉 Job {parent_job.id} is fully COMPLETE!")
            
            # TRIGGER AGGREGATION
            try:
                print(f"🔄 Starting FedAvg aggregation for job {parent_job.id}...")
                final_url, convergence_delta = aggregate_pytorch_weights(parent_job.id, db)
                parent_job.final_result_url = final_url
                parent_job.convergence_delta = convergence_delta
                db.commit()
                print(f"✅ Aggregation complete! Convergence delta: {convergence_delta:.6f}")
            except Exception as e:
                print(f"❌ Aggregation Failed: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"⚠️  Parent job {subtask.job_id} not found!")
    
    return {"message": "Task marked as completed. Good job!"}