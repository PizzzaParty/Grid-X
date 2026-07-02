"""
worker/main.py — Grid-X Worker Node

This script runs on the seller's machine as a plain Python process.
It does NOT run inside Docker itself — instead it uses Docker to sandbox
each individual training job (via executor.py), keeping the seller's host
system isolated from buyer-uploaded code.

Flow:
  1. Detect real hardware (GPU model, RAM) via pynvml / psutil
  2. Register with the Grid-X backend (links this machine to the seller's account)
  3. Loop:
     a. Send heartbeat so the server knows we're alive
     b. Poll for a PENDING subtask
     c. If task found: download files, run in Docker sandbox, upload result, complete task
     d. Sleep 10s and repeat
"""

import time
import requests
import os
import logging
import uuid
import sys

# Ensure the project root is on the path so `worker.utils` and `worker.executor`
# are importable when this script is launched as `python worker/main.py` from
# the Grid-X/ root directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.utils import create_temp_workspace, clean_workspace, download_file
from worker.executor import run_in_sandbox, build_base_image

# ── Configuration ─────────────────────────────────────────────────────────────

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
WORKER_EMAIL = os.getenv("WORKER_EMAIL", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))  # seconds between polls

# Agent ID is persisted locally so the worker keeps the same identity across restarts.
# If the file doesn't exist, we generate a new UUID and save it.
AGENT_ID_FILE = os.path.join(os.path.dirname(__file__), ".agent_id")

def get_or_create_agent_id() -> str:
    if os.path.exists(AGENT_ID_FILE):
        with open(AGENT_ID_FILE, "r") as f:
            return f.read().strip()
    new_id = f"agent_{uuid.uuid4().hex[:12]}"
    with open(AGENT_ID_FILE, "w") as f:
        f.write(new_id)
    return new_id

AGENT_ID = os.getenv("AGENT_ID") or get_or_create_agent_id()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("worker.log"),
    ],
)
log = logging.getLogger(__name__)

# ── Hardware Detection ────────────────────────────────────────────────────────

def detect_gpu() -> str:
    """
    Returns a human-readable GPU name string.
    Tries NVIDIA (pynvml) first, then Apple MPS, then falls back to 'CPU only'.

    pynvml is NVIDIA's Python management library — it reads GPU info directly
    from the driver without needing nvidia-smi to be in PATH.
    """
    # 1. Try NVIDIA via pynvml
    try:
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        if count > 0:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(handle)
            # nvmlDeviceGetName returns bytes on older pynvml versions
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            vram_bytes = pynvml.nvmlDeviceGetMemoryInfo(handle).total
            vram_gb = round(vram_bytes / (1024 ** 3), 1)
            pynvml.nvmlShutdown()
            return f"{name} ({vram_gb}GB VRAM)"
    except Exception:
        pass

    # 2. Try Apple Silicon MPS
    try:
        import torch
        if torch.backends.mps.is_available():
            import platform
            chip = platform.processor() or "Apple Silicon"
            return f"{chip} (MPS)"
    except Exception:
        pass

    return "CPU only"


def detect_ram() -> str:
    """Returns total system RAM as a human-readable string using psutil."""
    try:
        import psutil
        total_bytes = psutil.virtual_memory().total
        total_gb = round(total_bytes / (1024 ** 3), 1)
        return f"{total_gb}GB"
    except Exception:
        return "Unknown"


# ── Backend Communication ─────────────────────────────────────────────────────

def register_agent(gpu_model: str, ram_total: str):
    """Register this worker with the backend, linked to the seller's account by email."""
    if not WORKER_EMAIL:
        log.error("WORKER_EMAIL is not set. Run setup_worker.sh to configure.")
        sys.exit(1)

    payload = {
        "id": AGENT_ID,
        "email": WORKER_EMAIL,
        "gpu_model": gpu_model,
        "ram_total": ram_total,
    }
    try:
        resp = requests.post(f"{BACKEND_URL}/agent/register", json=payload, timeout=10)
        resp.raise_for_status()
        log.info(f"✅ Registered as {AGENT_ID} | GPU: {gpu_model} | RAM: {ram_total}")
    except Exception as e:
        log.warning(f"Registration failed (will retry on next start): {e}")


def send_heartbeat(status: str = "IDLE"):
    """Keepalive ping. If missed for 10+ minutes the server requeues our tasks."""
    try:
        requests.post(
            f"{BACKEND_URL}/agent/heartbeat",
            json={"id": AGENT_ID, "status": status},
            timeout=5,
        )
    except Exception:
        pass  # Network blip — not fatal


def poll_for_task() -> dict | None:
    """Ask the backend for a PENDING subtask. Returns task data or None."""
    try:
        resp = requests.post(
            f"{BACKEND_URL}/agent/request_task",
            json={"agent_id": AGENT_ID},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("task_id") is not None:
            return data
    except Exception as e:
        log.error(f"Poll error: {e}")
    return None


# ── Task Execution ────────────────────────────────────────────────────────────

def execute_task(task_data: dict):
    """
    Full task lifecycle:
    1. Download training code, requirements, and data chunk from Supabase
    2. Run everything inside a Docker container (secure-executor-base image)
    3. Upload the resulting model.pth back to the backend
    4. Call complete_task so the backend can check if all 5 workers are done
       and trigger FedAvg aggregation
    """
    workspace = create_temp_workspace()
    task_id = task_data["task_id"]
    log.info(f"🔨 Starting task {task_id} in workspace {workspace}")

    try:
        # 1. Download files into the workspace
        log.info("⬇️  Downloading files...")
        download_file(task_data["code_url"],         os.path.join(workspace, "train.py"))
        download_file(task_data["requirements_url"], os.path.join(workspace, "requirements.txt"))
        download_file(task_data["chunk_data_url"],   os.path.join(workspace, "data.csv"))

        # 2. Run inside Docker sandbox
        #    The container gets the workspace mounted as /app and runs train.py.
        #    Network is enabled so pip install works. CPU and RAM are capped.
        log.info("⚙️  Running training in Docker sandbox...")
        result = run_in_sandbox(workspace, entry_point="train.py")
        log.info(f"   Exit status: {result['status']}")
        if result.get("logs"):
            log.info(f"   Logs: {result['logs'][:300]}...")

        # 3. Upload model.pth
        model_path = os.path.join(workspace, "model.pth")
        result_url = None

        if os.path.exists(model_path):
            log.info("📤 Uploading model.pth...")
            with open(model_path, "rb") as f:
                upload_resp = requests.post(
                    f"{BACKEND_URL}/agent/upload_result",
                    files={"file": ("model.pth", f, "application/octet-stream")},
                    data={"agent_id": AGENT_ID, "task_id": task_id},
                    timeout=60,
                )
                upload_resp.raise_for_status()
                result_url = upload_resp.json().get("url")
            log.info(f"   Uploaded: {result_url[:80] if result_url else 'None'}...")
        else:
            log.warning("⚠️  No model.pth found after training.")

        # 4. Complete the task
        complete_resp = requests.post(
            f"{BACKEND_URL}/agent/complete_task",
            json={
                "agent_id": AGENT_ID,
                "task_id": task_id,
                "result_url": result_url or "",
            },
            timeout=30,
        )
        complete_resp.raise_for_status()
        log.info(f"✅ Task {task_id} complete")

    except Exception as e:
        log.error(f"❌ Task {task_id} failed: {e}", exc_info=True)
    finally:
        clean_workspace(workspace)


# ── Main Loop ─────────────────────────────────────────────────────────────────

def main():
    log.info("🚀 Grid-X Worker Starting...")
    log.info(f"   Agent ID:    {AGENT_ID}")
    log.info(f"   Backend URL: {BACKEND_URL}")
    log.info(f"   Email:       {WORKER_EMAIL}")

    # Detect real hardware
    log.info("🔍 Detecting hardware...")
    gpu_model = detect_gpu()
    ram_total = detect_ram()
    log.info(f"   GPU: {gpu_model}")
    log.info(f"   RAM: {ram_total}")

    # Build the Docker sandbox image if it doesn't exist yet
    build_base_image()

    # Register with the backend (links this machine to the seller's account)
    register_agent(gpu_model, ram_total)

    log.info(f"🔄 Polling for tasks every {POLL_INTERVAL}s...")

    while True:
        send_heartbeat("IDLE")
        task = poll_for_task()

        if task:
            send_heartbeat("BUSY")
            execute_task(task)
        else:
            log.debug("No tasks available.")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Worker stopped by user.")
