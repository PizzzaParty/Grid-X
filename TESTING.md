# Grid-X — Testing Guide

## How the System Actually Works

Before testing, understand what runs where:

```
Your laptop
├── Backend (FastAPI)     — runs directly: uvicorn app.main:app
├── Frontend (Next.js)    — runs directly: npm run dev
└── Worker (Python)       — runs directly: python worker/main.py
        └── For each task: spawns a Docker container (secure-executor-base)
                           to sandbox the buyer's training code
```

The Docker container is only used **per training job** as a security sandbox.
The backend, frontend, and worker themselves are plain processes on your machine.

To run buyer and seller on the same laptop: open two browser tabs.
Tab 1 → log in as buyer. Tab 2 → log in as seller. That's it.

---

## Prerequisites

```bash
# 1. Python 3.11+
python3 --version

# 2. Node.js 18+
node --version

# 3. Docker running (for the worker sandbox)
docker info

# 4. .env file at project root
cp .env.example .env
# Fill in: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, JWT_SECRET_KEY, NEXT_PUBLIC_API_URL
```

Generate a JWT secret if you don't have one:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Step 0 — Start Everything

You need **three terminals** open from the `Grid-X/` root.

**Terminal 1 — Backend:**
```bash
cd backend
pip install -r requirements.txt   # first time only
uvicorn app.main:app --reload --port 8000
```

Expected: `INFO: Application startup complete.`  
No `RuntimeError` about missing env vars = `.env` is loaded correctly.

**Terminal 2 — Frontend:**
```bash
cd grid-x/packages/dashboard
npm install                        # first time only
npm run dev
```

Open `http://localhost:3000`

**Terminal 3 — Worker:**
```bash
# First time only: run setup
./setup_worker.sh
# It will ask for Backend URL (press Enter for localhost:8000)
# and Worker Email (must be a registered seller account — see Step 2)

# After setup:
./start_worker.sh
```

Expected worker output:
```
🚀 Grid-X Worker Starting...
🔍 Detecting hardware...
   GPU: NVIDIA RTX 4090 (24.0GB VRAM)   ← or CPU only / Apple Silicon (MPS)
   RAM: 16.0GB
Building base image secure-executor-base...
✅ Registered as agent_abc123
🔄 Polling for tasks every 10s...
```

---

## Step 1 — Health Check

```bash
curl http://localhost:8000/
```
Expected: `{"status": "online", "message": "Grid-X API is running 🚀"}`

Open `http://localhost:8000/docs` — Swagger UI should show all routes.

---

## Step 2 — Register Accounts (Frontend)

Open `http://localhost:3000/registration` in **two tabs**.

**Tab 1 — Buyer account:**
- Email: `buyer@test.com`
- Password: `testpass123`
- Role: Scientist (Buyer)
- Submit → auto-redirected to Scientist Workstation
- ✅ Wallet shows **100 credits** (welcome bonus)

**Tab 2 — Seller account:**
- Email: `seller@test.com`
- Password: `testpass123`
- Role: Provider (Seller)
- Submit → auto-redirected to Provider Dashboard
- ✅ Wallet shows **100 credits**

### Verify bcrypt — passwords are never stored in plain text

```bash
python3 -c "
import sqlite3
db = sqlite3.connect('backend/app/sql_app.db')
for row in db.execute('SELECT email, password FROM users').fetchall():
    print(f'{row[0]}: {row[1][:30]}...')
db.close()
"
```

Every password hash starts with `$2b$12$` — that's bcrypt. The originals are unrecoverable.

---

## Step 3 — Configure the Worker with the Seller Email

Before starting the worker, edit `worker_config.env`:
```bash
# worker_config.env
BACKEND_URL=http://localhost:8000
WORKER_EMAIL=seller@test.com     # must match a registered seller account
```

Then start the worker (Terminal 3):
```bash
./start_worker.sh
```

Check `http://localhost:3000/dashboard/seller` — your machine should appear under **My Agents** with real GPU and RAM values detected automatically.

---

## Step 4 — Submit a Training Job (Buyer)

You need three test files. Create them:

```bash
# Training script
cat > /tmp/train.py << 'EOF'
import torch
import torch.nn as nn
import pandas as pd

df = pd.read_csv('data.csv')
print(f"Training on {len(df)} rows")

model = nn.Linear(df.shape[1] - 1, 1)

# Simple gradient descent for a few steps
optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
X = torch.tensor(df.iloc[:, :-1].values, dtype=torch.float32)
y = torch.tensor(df.iloc[:, -1].values, dtype=torch.float32).unsqueeze(1)

for _ in range(10):
    loss = nn.MSELoss()(model(X), y)
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()

print(f"Final loss: {loss.item():.4f}")
torch.save(model.state_dict(), 'model.pth')
print("Saved model.pth")
EOF

# Requirements
echo "torch
pandas" > /tmp/requirements.txt

# Dataset (500 rows so chunks are meaningful)
python3 -c "
import csv, random
with open('/tmp/data.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['x1', 'x2', 'x3', 'y'])
    for _ in range(500):
        x1, x2, x3 = random.random(), random.random(), random.random()
        w.writerow([x1, x2, x3, x1 + x2 * 0.5 + random.gauss(0, 0.1)])
"
```

In **Tab 1** (buyer dashboard):
1. Enter title: `FedAvg Demo`
2. Upload `/tmp/train.py`, `/tmp/requirements.txt`, `/tmp/data.csv`
3. Click **Submit Job**

✅ What to watch:
- Status message: `Upload successful! 5 credits deducted.`
- Wallet drops from 100 → **95 credits**
- Job appears as **PROCESSING** then transitions to **RUNNING** with a progress bar showing `0/5 workers done`

---

## Step 5 — Watch the Worker Process Tasks

Switch to **Terminal 3** (worker). You should see:

```
⬇️  Downloading files...
⚙️  Running training in Docker sandbox...
   Exit status: success
📤 Uploading model.pth...
✅ Task 1 complete
```

The Docker container that ran the buyer's code is automatically removed after each task.

Switch to **Tab 2** (seller dashboard) — watch:
- Agent status flips: **IDLE → BUSY → IDLE** per task
- Jobs Completed counter increments
- Wallet increases: **100 → 101 → 102...** (1 credit per completed subtask)

Switch to **Tab 1** (buyer dashboard) — watch the progress bar fill:
```
1/5 workers done → 2/5 → 3/5 → 4/5 → 5/5
```

After all 5 subtasks complete, the backend automatically runs FedAvg aggregation.
The job flips to **COMPLETED** (green badge) and shows:
- `Convergence delta: 0.0001` (or similar small value)
- **⬇ Download Model** button

---

## Step 6 — Verify Weighted FedAvg Ran

Check the backend terminal logs after job completion:

```
🔄 Starting FedAvg aggregation for job 1...
➗ FedAvg: 5 models, 500 total samples
   Worker 1: 100 rows (20.0% weight)
   Worker 2: 100 rows (20.0% weight)
   Worker 3: 100 rows (20.0% weight)
   Worker 4: 100 rows (20.0% weight)
   Worker 5: 100 rows (20.0% weight)
📐 Convergence delta (weighted vs uniform): 0.000000
✅ Aggregation complete!
```

Since all chunks are equal size (100 rows each), weighted and uniform averages are identical — convergence delta is 0. To see a non-zero delta, submit a job with a dataset whose row count isn't divisible by 5 (e.g. 523 rows).

---

## Step 7 — Download and Inspect the Final Model

Click **⬇ Download Model** on the buyer dashboard. This opens the Supabase URL for `final_model.pth`.

Verify it locally:
```bash
python3 -c "
import torch, requests, io

# Replace with the URL from the buyer dashboard download
url = input('Paste the final_model.pth URL: ').strip()
resp = requests.get(url)
state_dict = torch.load(io.BytesIO(resp.content), map_location='cpu')
print('Model keys:', list(state_dict.keys()))
print('Weight shape:', state_dict['weight'].shape)
print('Total parameters:', sum(p.numel() for p in state_dict.values()))
"
```

---

## Step 8 — Dead Worker Requeue Test

Tests fault tolerance: what happens when a worker disappears mid-task.

```bash
# 1. Submit another job (repeat Step 4)

# 2. Let the worker pick up a task — then immediately kill the worker
#    (Ctrl+C in Terminal 3)

# 3. Manually expire the agent heartbeat to simulate it being long dead
python3 -c "
import sqlite3
from datetime import datetime, timedelta, timezone
old = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
db = sqlite3.connect('backend/app/sql_app.db')
db.execute('UPDATE agents SET last_heartbeat=?', (old,))
db.commit()
db.close()
print('Heartbeat expired')
"

# 4. Trigger the requeue check manually (instead of waiting 60s)
cd backend
python3 -c "
import sys; sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('../.env')
from app.requeue import _run_requeue
_run_requeue()
"
```

Expected output:
```
🔁 Requeue check: found 1 stale subtask(s)
   Requeueing subtask X (was assigned to agent_abc123)
   Marking agent agent_abc123 as OFFLINE
✅ Requeued 1 subtask(s)
```

```bash
# 5. Verify subtask is PENDING again
python3 -c "
import sqlite3
db = sqlite3.connect('backend/app/sql_app.db')
for r in db.execute('SELECT id, status, assigned_to FROM subtasks').fetchall():
    print(f'Subtask {r[0]}: {r[1]}, assigned={r[2]}')
db.close()
"
```

Restart the worker — it picks up the requeued task automatically.

---

## Step 9 — Credits Economy Verification

```bash
python3 -c "
import sqlite3
db = sqlite3.connect('backend/app/sql_app.db')
print('User balances:')
for r in db.execute('SELECT email, role, credits FROM users').fetchall():
    print(f'  {r[0]} ({r[1]}): {r[2]} credits')
db.close()
"
```

Expected after one full job (5 subtasks):
- `buyer@test.com`: 95.0 (started at 100, paid 5 for the job)
- `seller@test.com`: 105.0 (started at 100, earned 1 × 5 subtasks)

### Test insufficient credits (402 error):
```bash
# Drain buyer credits
python3 -c "
import sqlite3
db = sqlite3.connect('backend/app/sql_app.db')
db.execute('UPDATE users SET credits=2.0 WHERE email=\"buyer@test.com\"')
db.commit()
db.close()
"
```

Try to submit another job — the frontend should show an error, or via curl:
```bash
BUYER_TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"buyer@test.com","password":"testpass123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://localhost:8000/jobs/upload \
  -H "Authorization: Bearer $BUYER_TOKEN" \
  -F "title=Should Fail" \
  -F "user_id=1" \
  -F "file_code=@/tmp/train.py" \
  -F "file_req=@/tmp/requirements.txt" \
  -F "file_data=@/tmp/data.csv" | python3 -m json.tool
```

Expected: `{"detail": "Insufficient credits..."}` with HTTP 402.

---

## Step 10 — Run the Automated Test Suite

These scripts exercise the full workflow programmatically (no browser needed).

```bash
cd Grid-X

# Quick integration test (~30s)
python3 tests/test_integration_simple.py

# Full end-to-end with aggregation (~60s)
python3 tests/test_full_workflow.py
```

Both scripts:
- Create fresh test accounts
- Upload a training job
- Simulate a worker completing all 5 subtasks
- Verify FedAvg aggregation ran and the final model is downloadable

---

## DB State Inspector

Run at any point to see everything in the database:

```bash
python3 -c "
import sqlite3
db = sqlite3.connect('backend/app/sql_app.db')

print('\n=== USERS ===')
for r in db.execute('SELECT id, email, role, credits FROM users').fetchall():
    print(f'  [{r[0]}] {r[1]} ({r[2]}) — {r[3]:.1f} credits')

print('\n=== JOBS ===')
for r in db.execute('SELECT id, title, status, convergence_delta FROM jobs').fetchall():
    delta = f'{r[3]:.6f}' if r[3] is not None else 'N/A'
    print(f'  [{r[0]}] \"{r[1]}\" — {r[2]} (delta={delta})')

print('\n=== SUBTASKS ===')
for r in db.execute('SELECT id, job_id, status, assigned_to, chunk_row_count FROM subtasks').fetchall():
    print(f'  [{r[0]}] job={r[1]}, {r[2]}, agent={r[3]}, rows={r[4]}')

print('\n=== AGENTS ===')
for r in db.execute('SELECT id, status, gpu_model, ram_total FROM agents').fetchall():
    print(f'  {r[0]} — {r[1]}, GPU: {r[2]}, RAM: {r[3]}')

db.close()
"
```

## Clean Reset

```bash
rm backend/app/sql_app.db
# Restart the backend — SQLAlchemy recreates all tables on startup
```

---

## Common Issues

| Symptom | Cause | Fix |
|---|---|---|
| `RuntimeError: Missing SUPABASE_URL` | `.env` not found | `cp .env.example .env` and fill values |
| `RuntimeError: JWT_SECRET_KEY is not set` | Missing JWT key | Add to `.env`: `JWT_SECRET_KEY=<32-byte hex>` |
| Wallet shows 0 or errors | Old localStorage from before JWT was added | DevTools → Application → Clear Local Storage, log in again |
| Worker shows `CPU only` for GPU | No NVIDIA GPU or pynvml not installed | Expected on laptops without NVIDIA GPUs |
| Worker can't connect to backend | Wrong `BACKEND_URL` in `worker_config.env` | Check the URL, ensure backend is running |
| Job stuck at PROCESSING | Background CSV splitter failed | Check backend terminal for `[Job X]` error logs |
| Docker permission denied in worker | User not in docker group | `sudo usermod -aG docker $USER`, then log out and back in |
| `402 Insufficient credits` | Buyer has < 5 credits | Use DB inspector above to reset credits |
