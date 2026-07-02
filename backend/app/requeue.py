"""
requeue.py — Dead worker detection and subtask requeueing.

Problem: A worker takes a subtask (status → RUNNING) then crashes or loses
connection. Without intervention, the subtask stays RUNNING forever and the
job never completes.

Solution: A periodic background task (runs every 60 seconds) checks for
subtasks in RUNNING state where the assigned agent's last_heartbeat is older
than STALE_THRESHOLD. Those subtasks get reset to PENDING so another worker
can pick them up. The stale agent is marked OFFLINE.

This is a standard pattern in distributed task queues (Celery, SQS, etc.)
called "visibility timeout" or "heartbeat-based lease".
"""

import asyncio
from datetime import datetime, timedelta, timezone
from .database import SessionLocal
from . import models

# How long without a heartbeat before we consider a worker dead.
STALE_THRESHOLD_MINUTES = 10


async def requeue_stale_tasks():
    """
    Runs forever, checking for stuck subtasks every 60 seconds.
    Called once at startup via asyncio.create_task().
    """
    while True:
        await asyncio.sleep(60)
        try:
            _run_requeue()
        except Exception as e:
            print(f"⚠️  Requeue check failed: {e}")


def _run_requeue():
    """Synchronous inner function — creates its own DB session."""
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_THRESHOLD_MINUTES)

        # Find all RUNNING subtasks whose assigned agent has gone silent
        stale_subtasks = (
            db.query(models.Subtask)
            .join(models.Agent, models.Subtask.assigned_to == models.Agent.id)
            .filter(
                models.Subtask.status == "RUNNING",
                models.Agent.last_heartbeat < cutoff,
            )
            .all()
        )

        if not stale_subtasks:
            return

        print(f"🔁 Requeue check: found {len(stale_subtasks)} stale subtask(s)")

        stale_agent_ids = set()
        for subtask in stale_subtasks:
            print(f"   Requeueing subtask {subtask.id} (was assigned to {subtask.assigned_to})")
            stale_agent_ids.add(subtask.assigned_to)
            subtask.status = "PENDING"
            subtask.assigned_to = None

        # Mark stale agents OFFLINE
        for agent_id in stale_agent_ids:
            agent = db.query(models.Agent).filter(models.Agent.id == agent_id).first()
            if agent:
                agent.status = "OFFLINE"
                print(f"   Marking agent {agent_id} as OFFLINE")

        db.commit()
        print(f"✅ Requeued {len(stale_subtasks)} subtask(s)")

    finally:
        db.close()
