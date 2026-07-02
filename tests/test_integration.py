import requests
import time
import io
import torch
import pandas as pd
import sys
from pathlib import Path

# Add parent directory to path so we can import backend modules
sys.path.insert(0, str(Path(__file__).parent.parent))

BACKEND_URL = "http://localhost:8000"
TEST_USER_EMAIL = "test@gridx.com"
TEST_USER_PASSWORD = "testpass123"

def test_end_to_end_workflow():
    print("🧪 Starting End-to-End Integration Test")
    
    # ===== STEP 1: Create Test User =====
    print("\n1️⃣ Creating test user...")
    resp = requests.post(f"{BACKEND_URL}/auth/register", json={
        "email": TEST_USER_EMAIL,
        "password": TEST_USER_PASSWORD,
        "role": "buyer",
    })
    assert resp.status_code in [200, 400], f"User creation failed: {resp.text}"

    # Login — response is now {access_token, user: {id, ...}}
    resp = requests.post(f"{BACKEND_URL}/auth/login", json={
        "email": TEST_USER_EMAIL,
        "password": TEST_USER_PASSWORD,
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    login_data = resp.json()
    user_id = login_data["user"]["id"]
    print(f"✅ User created/logged in: ID={user_id}")
    
    # ===== STEP 2: Prepare Test Job Files =====
    print("\n2️⃣ Preparing test job files...")
    
    # Create a simple training script
    train_code = """
import torch
import pandas as pd
import sys

# Load data
df = pd.read_csv('data.csv')
print(f"Loaded {len(df)} rows")

# Simple model
model = torch.nn.Linear(10, 1)

# Save model
torch.save(model.state_dict(), 'model.pth')
print("Model saved to model.pth")
"""
    
    # Create requirements
    requirements = """torch
pandas
"""
    
    # Create sample data (100 rows, 10 features)
    df = pd.DataFrame({
        f'feature_{i}': [j for j in range(100)]
        for i in range(10)
    })
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_content = csv_buffer.getvalue()
    
    print("✅ Test files prepared")
    
    # ===== STEP 3: Upload Job =====
    print("\n3️⃣ Uploading job to backend...")
    
    files = {
        'file_code': ('train.py', train_code, 'text/x-python'),
        'file_req': ('requirements.txt', requirements, 'text/plain'),
        'file_data': ('data.csv', csv_content, 'text/csv')
    }
    data = {
        'title': 'Integration Test Job',
        'user_id': user_id
    }
    
    resp = requests.post(f"{BACKEND_URL}/jobs/upload", files=files, data=data)
    assert resp.status_code == 200, f"Job upload failed: {resp.text}"
    job_id = resp.json()['job_id']
    print(f"✅ Job uploaded: ID={job_id}, Status=PROCESSING")
    
    # Wait for background splitting to complete
    print("\n⏳ Waiting for CSV splitting...")
    time.sleep(10)
    
    # ===== STEP 4: Verify Subtasks Created =====
    print("\n4️⃣ Verifying subtasks were created...")
    
    # Check database directly
    from backend.app.database import SessionLocal
    from backend.app import models
    
    db = SessionLocal()
    subtasks = db.query(models.Subtask).filter(
        models.Subtask.job_id == job_id
    ).all()
    db.close()
    
    assert len(subtasks) == 5, f"Expected 5 subtasks, got {len(subtasks)}"
    assert all(st.status == "PENDING" for st in subtasks), "Not all subtasks are PENDING"
    print(f"✅ {len(subtasks)} subtasks created, all PENDING")
    
    # ===== STEP 5: Simulate Worker Registration =====
    print("\n5️⃣ Registering test worker...")

    # First, create agent owner as a seller
    agent_email = "agent@gridx.com"
    requests.post(f"{BACKEND_URL}/auth/register", json={
        "email": agent_email,
        "password": "agentpass",
        "role": "seller",
    })
    
    agent_id = "test_agent_12345"
    resp = requests.post(f"{BACKEND_URL}/agent/register", json={
        "id": agent_id,
        "email": agent_email,
        "gpu_model": "Test GPU",
        "ram_total": "16GB"
    })
    assert resp.status_code == 200, f"Agent registration failed: {resp.text}"
    print(f"✅ Worker registered: {agent_id}")
    
    # ===== STEP 6: Process All Subtasks =====
    print("\n6️⃣ Simulating worker processing tasks...")
    
    for i in range(5):
        # Request task
        resp = requests.post(f"{BACKEND_URL}/agent/request_task", json={
            "agent_id": agent_id
        })
        assert resp.status_code == 200
        task_data = resp.json()
        
        if task_data['task_id'] is None:
            print(f"⚠️  No more tasks available")
            break
            
        task_id = task_data['task_id']
        print(f"  → Task {task_id} assigned to worker")
        
        # Simulate heartbeat
        requests.post(f"{BACKEND_URL}/agent/heartbeat", json={
            "id": agent_id,
            "status": "BUSY"
        })
        
        # Simulate execution (create dummy model)
        dummy_model = torch.nn.Linear(10, 1)
        model_bytes = io.BytesIO()
        torch.save(dummy_model.state_dict(), model_bytes)
        model_bytes.seek(0)
        
        # Upload result
        files = {'file': ('model.pth', model_bytes, 'application/octet-stream')}
        data = {'agent_id': agent_id, 'task_id': task_id}
        resp = requests.post(f"{BACKEND_URL}/agent/upload_result", files=files, data=data)
        assert resp.status_code == 200, f"Upload failed: {resp.text}"
        result_url = resp.json()['url']
        
        # Complete task
        resp = requests.post(f"{BACKEND_URL}/agent/complete_task", json={
            "agent_id": agent_id,
            "task_id": task_id,
            "result_url": result_url
        })
        assert resp.status_code == 200, f"Task completion failed: {resp.text}"
        print(f"  ✅ Task {task_id} completed")
        
        # Mark agent as idle
        requests.post(f"{BACKEND_URL}/agent/heartbeat", json={
            "id": agent_id,
            "status": "IDLE"
        })
    
    # ===== STEP 7: Verify Aggregation =====
    print("\n7️⃣ Verifying aggregation was triggered...")
    
    # Wait a bit for aggregation to complete
    time.sleep(5)
    
    # Check job status
    db = SessionLocal()
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    db.close()
    
    assert job.status == "COMPLETED", f"Expected COMPLETED, got {job.status}"
    assert job.final_result_url is not None, "Final result URL not set"
    print(f"✅ Job completed with final model at: {job.final_result_url}")
    
    # ===== STEP 8: Verify Final Model =====
    print("\n8️⃣ Verifying final aggregated model...")
    
    resp = requests.get(job.final_result_url)
    assert resp.status_code == 200, "Failed to download final model"
    
    # Load and verify model
    model_buffer = io.BytesIO(resp.content)
    state_dict = torch.load(model_buffer, map_location='cpu')
    assert 'weight' in state_dict, "Invalid model state dict"
    print(f"✅ Final model downloaded and verified")
    
    print("\n🎉 END-TO-END INTEGRATION TEST PASSED!")
    return True

if __name__ == "__main__":
    test_end_to_end_workflow()
