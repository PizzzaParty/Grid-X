from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from supabase import create_client
import pandas as pd
import io
import os
from datetime import datetime
from .. import models, database, schemas
from ..database import SessionLocal
import time
from typing import List
from datetime import timezone
# ==========================================
# 1. CONFIGURATION
# ==========================================
# Load from environment variables for security
# Create a .env file based on .env.example
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
BUCKET_NAME = os.getenv("SUPABASE_BUCKET_NAME", "gridx-files")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Missing required environment variables: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY. "
        "Copy .env.example to .env and fill in your Supabase credentials."
    )

# Initialize Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

router = APIRouter()

# ==========================================
# 2. HELPER: UPLOAD TO SUPABASE
# ==========================================
def upload_bytes_to_supabase(file_bytes: bytes, destination_path: str, content_type: str):
    """Uploads raw bytes to Supabase Storage with RETRY logic."""
    MAX_RETRIES = 3
    last_error = None
    
    for attempt in range(MAX_RETRIES):
        try:
            # Create bucket if not exists? No, bucket should exist.
            # BUCKET_NAME is global
            
            # Note: storage.from_() creates bucket object, .upload() performs action
            res = supabase.storage.from_(BUCKET_NAME).upload(
                path=destination_path,
                file=file_bytes,
                file_options={"content-type": content_type, "x-upsert": "true"}
            )
            # If successful, returns response object (usually dict or list)
            
            # Get Public URL
            return supabase.storage.from_(BUCKET_NAME).get_public_url(destination_path)
            
        except Exception as e:
            print(f"⚠️ Upload Attempt {attempt+1}/{MAX_RETRIES} Failed: {e}")
            last_error = e
            time.sleep(2) # Wait 2 seconds before retry
            
    print(f"❌ Final Upload Error: {last_error}")
    raise HTTPException(status_code=500, detail=f"File upload failed: {last_error}")

# ==========================================
# 3. BACKGROUND TASK: SPLITTER
# ==========================================
def split_csv_and_create_subtasks(job_id: int, csv_content: bytes):
    """
    Takes the uploaded CSV, splits it into 5 chunks, uploads chunks,
    and creates Subtask rows in the database.

    Creates its own DB session because this runs as a background task —
    after the HTTP request has already closed its session.
    """
    db = SessionLocal()
    try:
        print(f"🔪 [Job {job_id}] Starting background split...")
        print(f"   CSV size: {len(csv_content)} bytes")

        # A. Load CSV, then split with stratification if possible.
        #
        #    Why this matters — data heterogeneity (non-IID data) is the core
        #    failure mode of FedAvg. If chunks have different class distributions,
        #    each worker's model drifts toward its local skew. Averaging drifted
        #    models produces a worse result than any single model alone.
        #
        #    Strategy:
        #    1. Try stratified split on the last column (assumed label).
        #       This guarantees every chunk has the same class distribution.
        #    2. If stratification fails (regression target, too few samples,
        #       etc.), fall back to a shuffled sequential split which is still
        #       much better than an unshuffled sequential split.
        print(f"   Loading CSV into pandas...")
        df = pd.read_csv(io.BytesIO(csv_content))
        total_rows = len(df)
        num_chunks = 5
        chunks = []

        try:
            label_col = df.columns[-1]
            label_values = df[label_col]
            # Only stratify if the label looks categorical (≤20 unique values)
            if label_values.nunique() <= 20:
                from sklearn.model_selection import StratifiedKFold
                skf = StratifiedKFold(n_splits=num_chunks, shuffle=True, random_state=42)
                # StratifiedKFold gives us indices for each fold
                for _, fold_idx in skf.split(df, label_values):
                    chunks.append(df.iloc[fold_idx].reset_index(drop=True))
                print(f"   ✅ Stratified split on '{label_col}' ({label_values.nunique()} classes)")
            else:
                raise ValueError("Continuous target — using shuffled split")
        except Exception as strat_err:
            print(f"   ℹ️  Stratification skipped ({strat_err}), using shuffled split")
            df = df.sample(frac=1, random_state=42).reset_index(drop=True)
            chunk_size = total_rows // num_chunks
            for i in range(num_chunks):
                start = i * chunk_size
                end = None if i == num_chunks - 1 else start + chunk_size
                chunks.append(df.iloc[start:end].reset_index(drop=True))

        print(f"   ✅ {total_rows} rows → {num_chunks} chunks")

        # B. Upload each chunk and create a Subtask
        print(f"   ✅ Loaded {total_rows} rows, splitting into {num_chunks} chunks")

        # B. Upload each chunk and create a Subtask
        for i, subset in enumerate(chunks):
            print(f"   Processing chunk {i+1}/{num_chunks}...")
            chunk_row_count = len(subset)

            # C. Convert Chunk to CSV bytes
            buffer = io.BytesIO()
            subset.to_csv(buffer, index=False)
            chunk_bytes = buffer.getvalue()
            print(f"      Chunk {i}: {chunk_row_count} rows, {len(chunk_bytes)} bytes")

            # D. Upload Chunk
            chunk_path = f"jobs/{job_id}/chunks/chunk_{i}.csv"
            print(f"      Uploading to: {chunk_path}")
            chunk_url = upload_bytes_to_supabase(chunk_bytes, chunk_path, "text/csv")
            print(f"      ✅ Uploaded: {chunk_url[:60]}...")

            # E. Create Subtask in DB — store row count for weighted FedAvg
            new_subtask = models.Subtask(
                job_id=job_id,
                assigned_to=None,
                status="PENDING",
                chunk_file_url=chunk_url,
                chunk_row_count=chunk_row_count,
            )
            db.add(new_subtask)
            print(f"      ✅ Subtask {i+1} created ({chunk_row_count} rows)")

        # F. Update Job Status
        job = db.query(models.Job).filter(models.Job.id == job_id).first()
        job.status = "RUNNING"
        db.commit()
        print(f"✅ [Job {job_id}] Split complete! Created {num_chunks} subtasks. Status: RUNNING.")

    except Exception as e:
        print(f"❌ [Job {job_id}] Splitting Failed: {e}")
        import traceback
        traceback.print_exc()
        try:
            job = db.query(models.Job).filter(models.Job.id == job_id).first()
            if job:
                job.status = "ERROR"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()

# ==========================================
# 4. THE ENDPOINT
# ==========================================

JOB_COST_CREDITS = 5.0      # Credits deducted from buyer on job submission
SUBTASK_REWARD_CREDITS = 1.0  # Credits earned by seller per completed subtask (used in agent.py)

@router.post("/upload")
async def upload_job(
    title: str = Form(...),
    user_id: int = Form(...),
    file_code: UploadFile = File(...),
    file_req: UploadFile = File(...),
    file_data: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(database.get_db)
):
    # 0. Verify the buyer has enough credits
    buyer = db.query(models.User).filter(models.User.id == user_id).first()
    if not buyer:
        raise HTTPException(status_code=404, detail="User not found")
    if buyer.credits < JOB_COST_CREDITS:
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient credits. Job costs {JOB_COST_CREDITS} credits, "
                   f"you have {buyer.credits:.1f}."
        )

    # 1. Read Files
    code_bytes = await file_code.read()
    req_bytes  = await file_req.read()
    data_bytes = await file_data.read()

    # 2. Create unique folder paths
    timestamp = int(time.time())
    base_path = f"jobs/{user_id}_{timestamp}"

    # 3. Upload original files to Supabase
    code_url = upload_bytes_to_supabase(code_bytes, f"{base_path}/train.py",        "text/x-python")
    req_url  = upload_bytes_to_supabase(req_bytes,  f"{base_path}/requirements.txt", "text/plain")
    data_url = upload_bytes_to_supabase(data_bytes, f"{base_path}/data.csv",         "text/csv")

    # 4. Deduct credits from the buyer
    buyer.credits -= JOB_COST_CREDITS

    # 5. Create Job entry
    new_job = models.Job(
        title=title,
        status="PROCESSING",
        owner_id=user_id,
        original_code_url=code_url,
        original_req_url=req_url,
        original_data_url=data_url,
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    # 6. Trigger background splitting (creates its own DB session)
    background_tasks.add_task(split_csv_and_create_subtasks, new_job.id, data_bytes)

    return {
        "job_id": new_job.id,
        "message": f"Upload successful! {JOB_COST_CREDITS:.0f} credits deducted. Splitting data in background.",
        "status": "PROCESSING",
        "credits_remaining": buyer.credits,
    }

@router.get("/list/{user_id}", response_model=List[schemas.JobResponse])
def get_my_jobs(user_id: int, db: Session = Depends(database.get_db)):
    """
    Fetch all jobs belonging to a specific user.
    """
    # 1. Query the database
    # filter(models.Job.owner_id == user_id) ensures you only see YOUR jobs
    jobs = db.query(models.Job).filter(models.Job.owner_id == user_id).all()
    
    # 2. Return them (FastAPI converts them to JSON automatically)
    return jobs

@router.get("/{job_id}")
def get_job_status(job_id: int, db: Session = Depends(database.get_db)):
    """
    Get the status of a specific job.
    Includes calculated fields for progress.
    """
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Calculate progress
    total_subtasks = db.query(models.Subtask).filter(models.Subtask.job_id == job_id).count()
    completed_subtasks = db.query(models.Subtask).filter(
        models.Subtask.job_id == job_id, 
        models.Subtask.status == "COMPLETED"
    ).count()

    return {
        "id": job.id,
        "title": job.title,
        "status": job.status,
        "created_at": job.created_at,
        "final_result_url": job.final_result_url,
        "convergence_delta": job.convergence_delta,
        "total_subtasks": total_subtasks,
        "completed_subtasks": completed_subtasks,
    }

@router.get("/download/{job_id}", response_model=schemas.JobResultResponse)
def get_final_job_result(job_id: int, user_id: int = None, db: Session = Depends(database.get_db)):
    """
    Called by the Buyer Frontend to get the final download link.
    """
    # 1. Fetch the job
    job = db.query(models.Job).filter(models.Job.id == job_id).first()

    # 2. Safety Check: Does the job exist?
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # 3. Security Check: Does the user_id match the job's owner_id?
    # This prevents User A from guessing User B's job ID and stealing their data.
    # We only check if user_id is provided (to support older clients)
    if user_id is not None and job.owner_id != user_id:
        raise HTTPException(
            status_code=403, 
            detail="Unauthorized: You do not own this job."
        )

    # 4. Return the result
    return {
        "job_id": job.id,
        "title": job.title,
        "status": job.status,
        "final_result_url": job.final_result_url
    }