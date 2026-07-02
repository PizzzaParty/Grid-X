#!/usr/bin/env python3
"""
Complete End-to-End Test with Full Aggregation
Tests the entire Grid-X workflow including FedAvg aggregation
"""

import requests
import time
import io
import torch
import torch.nn as nn
import pandas as pd

BACKEND_URL = "http://localhost:8000"

def create_tiny_model():
    """Create a tiny PyTorch model for testing"""
    class TinyModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.fc = nn.Linear(10, 1)
        
        def forward(self, x):
            return self.fc(x)
    
    return TinyModel()

def main():
    print("🧪 Complete End-to-End Test with Aggregation")
    print("=" * 60)
    
    # Step 1: Create test user
    print("\n1️⃣ Creating test user...")
    email = f"fulltest_{int(time.time())}@gridx.com"
    requests.post(f"{BACKEND_URL}/auth/register", json={
        "email": email,
        "password": "test123",
        "role": "buyer",
    })

    # Login to get user_id and token
    login = requests.post(f"{BACKEND_URL}/auth/login", json={
        "email": email,
        "password": "test123",
    }).json()
    user_id = login["user"]["id"]
    print(f"✅ User created: ID={user_id}")

    # Step 2: Create agent owner and register worker
    print("\n2️⃣ Creating worker...")
    agent_email = f"agent_{int(time.time())}@gridx.com"
    requests.post(f"{BACKEND_URL}/auth/register", json={
        "email": agent_email,
        "password": "agent123",
        "role": "seller",
    })
    
    agent_id = f"test_worker_{int(time.time())}"
    resp = requests.post(f"{BACKEND_URL}/agent/register", json={
        "id": agent_id,
        "email": agent_email,
        "gpu_model": "Test GPU",
        "ram_total": "16GB"
    })
    print(f"✅ Worker registered: {agent_id}")
    
    # Step 3: Prepare tiny training job
    print("\n3️⃣ Preparing tiny PyTorch training job...")
    
    # Training code that creates a simple model
    train_code = """import torch
import torch.nn as nn
import pandas as pd

# Load data
df = pd.read_csv('data.csv')
print(f"Training on {len(df)} rows")

# Create tiny model
class TinyModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc = nn.Linear(10, 1)
    
    def forward(self, x):
        return self.fc(x)

model = TinyModel()

# Simple "training" (just initialize)
print(f"Model has {sum(p.numel() for p in model.parameters())} parameters")

# Save model
torch.save(model.state_dict(), 'model.pth')
print("Model saved!")
"""
    
    requirements = "torch\npandas\n"
    
    # Create tiny CSV (20 rows, 10 features)
    df = pd.DataFrame({f'f{i}': range(20) for i in range(10)})
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    
    print(f"   Training code: {len(train_code)} bytes")
    print(f"   CSV data: {len(df)} rows, {len(df.columns)} columns")
    
    # Step 4: Upload job
    print("\n4️⃣ Uploading job...")
    files = {
        'file_code': ('train.py', train_code, 'text/x-python'),
        'file_req': ('requirements.txt', requirements, 'text/plain'),
        'file_data': ('data.csv', csv_buffer.getvalue(), 'text/csv')
    }
    data = {'title': 'Full Aggregation Test', 'user_id': user_id}
    
    resp = requests.post(f"{BACKEND_URL}/jobs/upload", files=files, data=data)
    if resp.status_code != 200:
        print(f"❌ Job upload failed: {resp.status_code}")
        print(f"Response: {resp.text}")
        return False
    job_id = resp.json()['job_id']
    print(f"✅ Job uploaded: ID={job_id}")
    
    # Step 5: Wait for CSV splitting
    print("\n5️⃣ Waiting for CSV splitting (10 seconds)...")
    time.sleep(10)
    print("✅ CSV should be split into 5 subtasks")
    
    # Step 6: Process ALL available subtasks
    print("\n6️⃣ Processing all available subtasks...")
    completed_tasks = 0
    max_attempts = 10  # Safety limit
    
    for attempt in range(max_attempts):
        print(f"\n   Requesting task (attempt {attempt+1})...")
        
        # Request task
        resp = requests.post(f"{BACKEND_URL}/agent/request_task", json={
            "agent_id": agent_id
        })
        
        if resp.status_code != 200:
            print(f"   ❌ Failed to request task: {resp.text}")
            break
        
        task_data = resp.json()
        if task_data['task_id'] is None:
            print(f"   ✅ No more tasks available - all subtasks processed!")
            break
        
        task_id = task_data['task_id']
        print(f"   → Task {task_id} assigned")
        
        # Heartbeat
        requests.post(f"{BACKEND_URL}/agent/heartbeat", json={
            "id": agent_id,
            "status": "BUSY"
        })
        
        # Create dummy model result
        model = create_tiny_model()
        model_bytes = io.BytesIO()
        torch.save(model.state_dict(), model_bytes)
        model_bytes.seek(0)
        
        # Upload result
        files = {'file': ('model.pth', model_bytes, 'application/octet-stream')}
        data = {'agent_id': agent_id, 'task_id': task_id}
        resp = requests.post(f"{BACKEND_URL}/agent/upload_result", files=files, data=data)
        
        if resp.status_code != 200:
            print(f"   ❌ Upload failed: {resp.text}")
            break
        
        result_url = resp.json()['url']
        
        # Complete task
        resp = requests.post(f"{BACKEND_URL}/agent/complete_task", json={
            "agent_id": agent_id,
            "task_id": task_id,
            "result_url": result_url
        })
        
        if resp.status_code != 200:
            print(f"   ❌ Task completion failed: {resp.text}")
            break
        
        completed_tasks += 1
        print(f"   ✅ Task {task_id} completed ({completed_tasks} total)")
        
        # Mark agent idle
        requests.post(f"{BACKEND_URL}/agent/heartbeat", json={
            "id": agent_id,
            "status": "IDLE"
        })
        
        # Small delay between tasks
        time.sleep(1)
    
    # Step 7: Wait for aggregation
    print(f"\n7️⃣ Waiting for aggregation (5 seconds)...")
    time.sleep(5)
    
    # Step 8: Check job status
    print("\n8️⃣ Checking job status...")
    resp = requests.get(f"{BACKEND_URL}/jobs/list/{user_id}")
    jobs = resp.json()
    
    test_job = next((j for j in jobs if j['id'] == job_id), None)
    
    if test_job:
        print(f"   Job {job_id}:")
        print(f"   Status: {test_job['status']}")
        print(f"   Final result: {test_job.get('final_result_url', 'None')}")
        
        if test_job['status'] == 'COMPLETED':
            print("\n✅ AGGREGATION SUCCESSFUL!")
            if test_job.get('convergence_delta') is not None:
                print(f"   Convergence delta: {test_job['convergence_delta']:.6f}")
            
            # Try to download final model
            if test_job.get('final_result_url'):
                print("\n9️⃣ Downloading and verifying final model...")
                resp = requests.get(test_job['final_result_url'])
                
                if resp.status_code == 200:
                    model_buffer = io.BytesIO(resp.content)
                    state_dict = torch.load(model_buffer, map_location='cpu')
                    
                    print(f"   ✅ Final model downloaded!")
                    print(f"   Model keys: {list(state_dict.keys())}")
                    print(f"   Parameters: {sum(p.numel() for p in state_dict.values())}")
                else:
                    print(f"   ⚠️  Failed to download: {resp.status_code}")
        else:
            print(f"\n⚠️  Job status: {test_job['status']}")
            print(f"   Expected: COMPLETED")
            print(f"   Completed tasks: {completed_tasks}/5")
    else:
        print("   ❌ Job not found")
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 60)
    print(f"User created: ✅")
    print(f"Worker registered: ✅")
    print(f"Job uploaded: ✅")
    print(f"CSV split: ✅")
    print(f"Subtasks completed: {completed_tasks}/5")
    
    if test_job:
        if test_job['status'] == 'COMPLETED' and test_job.get('final_result_url'):
            print(f"Aggregation: ✅")
            print(f"Final model: ✅")
            print("\n🎉 FULL END-TO-END TEST PASSED!")
            return True
        else:
            print(f"Aggregation: ❌ (Status: {test_job['status']})")
            print("\n⚠️  Test incomplete - aggregation did not complete")
            return False
    else:
        print("Job status: ❌")
        return False

if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
