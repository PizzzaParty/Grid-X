import requests
import time
import io
import torch
import pandas as pd

BACKEND_URL = "http://localhost:8000"
TEST_USER_EMAIL = f"testuser_{int(time.time())}@gridx.com"
TEST_USER_PASSWORD = "testpass123"

def test_simple_integration():
    """Simplified integration test using only API endpoints"""
    print("🧪 Starting Simplified Integration Test")
    print("=" * 50)
    
    # Step 1: Create test user
    print("\n1️⃣ Creating test user...")
    resp = requests.post(f"{BACKEND_URL}/auth/register", json={
        "email": TEST_USER_EMAIL,
        "password": TEST_USER_PASSWORD,
        "role": "buyer",
    })
    assert resp.status_code == 200, f"User creation failed: {resp.status_code} - {resp.text}"
    user_id = resp.json()['id']
    print(f"✅ User created: ID={user_id}, email={TEST_USER_EMAIL}")
    
    # Step 2: Login — response now includes access_token + user
    print("\n2️⃣ Testing login...")
    resp = requests.post(f"{BACKEND_URL}/auth/login", json={
        "email": TEST_USER_EMAIL,
        "password": TEST_USER_PASSWORD,
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    login_data = resp.json()
    assert "access_token" in login_data, "No access_token in login response"
    assert login_data["user"]["id"] == user_id
    print(f"✅ Login successful, JWT received")
    
    # Step 3: Create agent owner
    print("\n3️⃣ Creating agent owner...")
    agent_email = f"agent_{int(time.time())}@gridx.com"
    resp = requests.post(f"{BACKEND_URL}/auth/register", json={
        "email": agent_email,
        "password": "agentpass",
        "role": "seller",
    })
    print(f"✅ Agent owner created: {agent_email}")
    
    # Step 4: Register agent
    print("\n4️⃣ Registering worker agent...")
    agent_id = f"test_agent_{int(time.time())}"
    resp = requests.post(f"{BACKEND_URL}/agent/register", json={
        "id": agent_id,
        "email": agent_email,
        "gpu_model": "Test GPU",
        "ram_total": "16GB"
    })
    assert resp.status_code == 200, f"Agent registration failed: {resp.text}"
    print(f"✅ Worker registered: {agent_id}")
    
    # Step 5: Send heartbeat
    print("\n5️⃣ Testing heartbeat...")
    resp = requests.post(f"{BACKEND_URL}/agent/heartbeat", json={
        "id": agent_id,
        "status": "IDLE"
    })
    assert resp.status_code == 200, f"Heartbeat failed: {resp.text}"
    print(f"✅ Heartbeat sent successfully")
    
    # Step 6: Prepare test job
    print("\n6️⃣ Preparing test job files...")
    train_code = """import torch
import pandas as pd

df = pd.read_csv('data.csv')
print(f"Training on {len(df)} rows")

model = torch.nn.Linear(10, 1)
torch.save(model.state_dict(), 'model.pth')
print("Model saved!")
"""
    
    requirements = "torch\npandas\n"
    
    # Create test CSV
    df = pd.DataFrame({f'f{i}': range(50) for i in range(10)})
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_content = csv_buffer.getvalue()
    
    print(f"✅ Test files prepared (CSV: {len(df)} rows)")
    
    # Step 7: Upload job
    print("\n7️⃣ Uploading job...")
    files = {
        'file_code': ('train.py', train_code, 'text/x-python'),
        'file_req': ('requirements.txt', requirements, 'text/plain'),
        'file_data': ('data.csv', csv_content, 'text/csv')
    }
    data = {
        'title': 'Simple Integration Test Job',
        'user_id': user_id
    }
    
    resp = requests.post(f"{BACKEND_URL}/jobs/upload", files=files, data=data)
    assert resp.status_code == 200, f"Job upload failed: {resp.text}"
    job_id = resp.json()['job_id']
    print(f"✅ Job uploaded: ID={job_id}")
    
    # Step 8: Wait for CSV splitting
    print("\n8️⃣ Waiting for background CSV splitting (10 seconds)...")
    time.sleep(10)
    print("✅ Wait complete")
    
    # Step 9: Check for available tasks
    print("\n9️⃣ Checking if tasks are available...")
    resp = requests.post(f"{BACKEND_URL}/agent/request_task", json={
        "agent_id": agent_id
    })
    assert resp.status_code == 200, f"Task request failed: {resp.text}"
    task_data = resp.json()
    
    if task_data['task_id'] is None:
        print("⚠️  No tasks available - CSV splitting may have failed")
        print("   Check backend logs for errors")
        return False
    
    print(f"✅ Task available: ID={task_data['task_id']}")
    print(f"   Code URL: {task_data['code_url'][:50]}...")
    print(f"   Data chunk URL: {task_data['chunk_data_url'][:50]}...")
    
    # Step 10: Simulate task completion
    print("\n🔟 Simulating task execution and completion...")
    task_id = task_data['task_id']
    
    # Create dummy model
    dummy_model = torch.nn.Linear(10, 1)
    model_bytes = io.BytesIO()
    torch.save(dummy_model.state_dict(), model_bytes)
    model_bytes.seek(0)
    
    # Upload result
    files = {'file': ('model.pth', model_bytes, 'application/octet-stream')}
    data = {'agent_id': agent_id, 'task_id': task_id}
    resp = requests.post(f"{BACKEND_URL}/agent/upload_result", files=files, data=data)
    assert resp.status_code == 200, f"Result upload failed: {resp.text}"
    result_url = resp.json()['url']
    print(f"✅ Result uploaded: {result_url[:60]}...")
    
    # Complete task
    resp = requests.post(f"{BACKEND_URL}/agent/complete_task", json={
        "agent_id": agent_id,
        "task_id": task_id,
        "result_url": result_url
    })
    assert resp.status_code == 200, f"Task completion failed: {resp.text}"
    print(f"✅ Task {task_id} marked as COMPLETED")
    
    # Step 11: Check job list
    print("\n1️⃣1️⃣ Checking user's job list...")
    resp = requests.get(f"{BACKEND_URL}/jobs/list/{user_id}")
    assert resp.status_code == 200, f"Job list failed: {resp.text}"
    jobs = resp.json()
    print(f"✅ User has {len(jobs)} job(s)")
    for job in jobs:
        print(f"   - Job {job['id']}: {job['title']} [{job['status']}]")
    
    print("\n" + "=" * 50)
    print("🎉 INTEGRATION TEST PASSED!")
    print("\nVerified:")
    print("  ✓ User registration and login")
    print("  ✓ Agent registration and heartbeat")
    print("  ✓ Job upload and CSV splitting")
    print("  ✓ Task assignment to worker")
    print("  ✓ Result upload and task completion")
    print("  ✓ Job listing")
    return True

if __name__ == "__main__":
    try:
        success = test_simple_integration()
        exit(0 if success else 1)
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
