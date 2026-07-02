# Grid-X — Distributed Federated Learning Marketplace

A decentralized platform that connects ML researchers with idle compute power. Buyers upload training jobs; sellers contribute their machines. The platform distributes training across workers using federated learning and aggregates the resulting models using weighted Federated Averaging (FedAvg).

---

## What It Does

**For Buyers (Scientists):**
- Upload a Python training script, a `requirements.txt`, and a CSV dataset
- The platform splits the dataset across available worker nodes
- Each worker trains a local model on its data chunk inside a Docker sandbox
- The server aggregates all local models into a single global model using FedAvg
- Download the final `.pth` model when training is complete

**For Sellers (Providers):**
- Register idle machines as worker nodes
- Workers automatically poll for available training jobs
- Earn credits for each completed subtask
- Real GPU/CPU specs are detected and reported at registration time

---

## Architecture

```
Browser
  └─ Next.js Frontend (port 3000)
       └─ REST API ──► FastAPI Backend (port 8000)
                          ├── SQLite (metadata: users, jobs, subtasks, agents)
                          └── Supabase Storage (files: code, data chunks, model weights)
                                    ▲
                          Worker Nodes (any machine)
                            ├── Poll /agent/request_task every 10s
                            ├── Download code + data chunk from Supabase
                            ├── Train inside Docker sandbox
                            └── Upload model.pth → /agent/complete_task
```

### Federated Averaging

Standard FedAvg (McMahan et al., 2017) with proportional data weighting:

```
w_global = Σ (n_k / N) * w_k
```

Where `n_k` is the number of training rows worker `k` processed and `N` is the total across all workers. This ensures workers that trained on more data have proportionally more influence on the final model — unlike a naive uniform average.

After aggregation, a **convergence delta** is computed: the L2 norm of the difference between the weighted average and a uniform average. This quantifies how much data distribution skew affected the result.

### Job Lifecycle

```
Upload → PROCESSING → (background split) → RUNNING → (all workers done) → COMPLETED
                              ↓                              ↓
                    5 subtasks created              FedAvg aggregation
                    data chunks uploaded            final_model.pth uploaded
```

### Fault Tolerance

A background task runs every 60 seconds checking for subtasks in `RUNNING` state whose assigned worker has gone silent (no heartbeat for 10+ minutes). Those subtasks are automatically reset to `PENDING` and reassigned to the next available worker.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, CSS Modules |
| Backend | Python 3.11, FastAPI, SQLAlchemy, SQLite |
| ML | PyTorch (FedAvg aggregation) |
| Storage | Supabase Storage (files and model weights) |
| Auth | bcrypt (password hashing) + JWT (stateless session tokens) |
| Worker Sandbox | Docker (`python:3.11-slim` with PyTorch CPU) |
| Data Processing | Pandas (CSV splitting) |

---

## Credits System

| Action | Effect |
|---|---|
| Register | +100 credits (welcome bonus) |
| Submit job | -5 credits |
| Complete subtask (seller) | +1 credit per subtask |

---

## Project Structure

```
Grid-X/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app, CORS, startup tasks
│   │   ├── models.py        # SQLAlchemy ORM models
│   │   ├── schemas.py       # Pydantic request/response schemas
│   │   ├── database.py      # SQLite engine + session factory
│   │   ├── security.py      # bcrypt + JWT helpers
│   │   ├── aggregation.py   # Weighted FedAvg implementation
│   │   ├── requeue.py       # Dead worker detection + task requeueing
│   │   └── routers/
│   │       ├── front_auth.py   # /auth — register, login, wallet
│   │       ├── front_job.py    # /jobs — upload, list, status, download
│   │       ├── sellers.py      # /stats — agent lists, task history
│   │       └── agent.py        # /agent — register, heartbeat, tasks
│   └── requirements.txt
├── grid-x/packages/dashboard/   # Next.js frontend
│   └── src/
│       ├── app/
│       │   ├── page.tsx              # Landing page
│       │   ├── login/                # Login page
│       │   ├── registration/         # Registration page
│       │   └── dashboard/
│       │       ├── buyer/            # Scientist workstation
│       │       └── seller/           # Provider dashboard
│       ├── context/AuthContext.tsx   # JWT auth state + authFetch helper
│       └── lib/api.ts                # API_BASE env var
├── Dockerfile.base          # Worker sandbox image
├── force_complete_job.py    # Dev utility: manually trigger aggregation
├── WORKER_SETUP.md          # Worker node setup guide
└── .env.example             # Environment variable reference
```

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker (for worker sandboxes)
- A [Supabase](https://supabase.com) project with a storage bucket named `gridx-files`

### 1. Environment Variables

```bash
cp .env.example .env
```

Fill in your values:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
SUPABASE_BUCKET_NAME=gridx-files
JWT_SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 2. Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs available at `http://localhost:8000/docs`

### 3. Frontend

```bash
cd grid-x/packages/dashboard
cp ../../../.env .env.local   # or set NEXT_PUBLIC_API_URL manually
npm install
npm run dev
```

Open `http://localhost:3000`

### 4. Worker Node

See [WORKER_SETUP.md](./WORKER_SETUP.md) for full instructions.

Quick start:
```bash
# Build the Docker sandbox image first
docker build -f Dockerfile.base -t secure-executor-base .

# Then run the worker (pointing to your backend)
BACKEND_URL=http://localhost:8000 python worker/main.py
```

---

## API Reference

Full interactive docs at `/docs` when the backend is running.

| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/register` | Create account |
| POST | `/auth/login` | Login, returns JWT |
| GET | `/auth/wallet/{user_id}` | Get credit balance |
| POST | `/jobs/upload` | Submit a training job |
| GET | `/jobs/list/{user_id}` | List user's jobs |
| GET | `/jobs/{job_id}` | Job status + subtask progress |
| GET | `/jobs/download/{job_id}` | Get final model URL |
| GET | `/stats/agents/online` | List active worker nodes |
| POST | `/agent/register` | Register a worker |
| POST | `/agent/heartbeat` | Worker keepalive |
| POST | `/agent/request_task` | Worker polls for work |
| POST | `/agent/upload_result` | Worker uploads model.pth |
| POST | `/agent/complete_task` | Worker marks task done |

---

## License

MIT — see [LICENSE](./LICENSE)
