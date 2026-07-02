#!/usr/bin/env python3
"""
Force Complete Job - Manually marks job as completed and triggers aggregation
"""

# Load .env FIRST before importing backend modules
from dotenv import load_dotenv
from pathlib import Path

env_file = Path(__file__).parent / '.env'
load_dotenv(env_file)

# Now import backend modules
import sys
sys.path.insert(0, 'backend')

from app.database import SessionLocal
from app import models
from app.aggregation import aggregate_pytorch_weights

def main():
    if len(sys.argv) < 2:
        print("Usage: python force_complete_job.py <job_id>")
        sys.exit(1)
    
    job_id = int(sys.argv[1])
    
    db = SessionLocal()
    try:
        # Check subtasks
        subtasks = db.query(models.Subtask).filter(
            models.Subtask.job_id == job_id
        ).all()
        
        completed = sum(1 for s in subtasks if s.status == "COMPLETED")
        print(f"Job {job_id}: {completed}/{len(subtasks)} subtasks completed")
        
        if completed < len(subtasks):
            print(f"⚠️  Not all subtasks are completed yet")
            return
        
        # Trigger aggregation
        print(f"\n🔄 Triggering aggregation...")
        final_url, convergence_delta = aggregate_pytorch_weights(job_id, db)

        # Update job
        job = db.query(models.Job).filter(models.Job.id == job_id).first()
        if job:
            job.status = "COMPLETED"
            job.final_result_url = final_url
            job.convergence_delta = convergence_delta
            db.commit()

            print(f"\n✅ Job {job_id} marked as COMPLETED!")
            print(f"   Final model: {final_url}")
            print(f"   Convergence delta: {convergence_delta:.6f}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()
