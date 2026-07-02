# Load environment variables FIRST, before any other imports
from dotenv import load_dotenv
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
env_file = project_root / '.env'
load_dotenv(env_file)

import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import engine, Base
from .routers import front_auth, front_job, sellers, agent
from .requeue import requeue_stale_tasks

# ── Initialize database ───────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Grid-X API",
    description="Distributed federated learning marketplace API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup: launch background tasks ─────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    # Requeue any subtasks assigned to workers that have gone silent.
    # Runs every 60 seconds — see requeue.py for details.
    asyncio.create_task(requeue_stale_tasks())

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(front_auth.router, prefix="/auth",  tags=["Auth"])
app.include_router(front_job.router,  prefix="/jobs",  tags=["Jobs"])
app.include_router(sellers.router,    prefix="/stats", tags=["Dashboard"])
app.include_router(agent.router,      prefix="/agent", tags=["Agent"])

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "Grid-X API is running 🚀",
        "docs": "/docs",
    }