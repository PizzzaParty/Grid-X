"""
aggregation.py — Federated Averaging (FedAvg) implementation.

FedAvg (McMahan et al., 2017) is the standard algorithm for aggregating model weights
in federated learning. The key idea: each worker's contribution is weighted proportionally
to how much data it trained on.

Formula: w_global = Σ (n_k / N) * w_k

Where:
  w_k   = model weights from worker k
  n_k   = number of training samples worker k used
  N     = total samples across all workers (Σ n_k)

This differs from a naive uniform average (torch.mean) because if worker A trained
on 400 rows and worker B on 100 rows, worker A's model learned from 4x more data
and should have 4x the influence on the final model.

After aggregation we also compute a convergence_delta — the L2 norm of the difference
between the weighted result and a naive uniform average. A value close to 0 means
the data was evenly distributed across workers; larger values indicate skew.
"""

import torch
import requests
import io
import time
import math
from sqlalchemy.orm import Session
from . import models
from .routers.front_job import upload_bytes_to_supabase


def aggregate_pytorch_weights(job_id: int, db: Session) -> tuple[str, float]:
    """
    Aggregates PyTorch model weights from completed subtasks using weighted FedAvg.

    Returns:
        (final_model_url, convergence_delta)
        convergence_delta: L2 norm of (weighted_avg - uniform_avg), measuring
                           how much data distribution affected the result.
    """
    print(f"🔄 Starting FedAvg aggregation for Job {job_id}...")

    # 1. Get all completed subtasks with their row counts
    subtasks = db.query(models.Subtask).filter(
        models.Subtask.job_id == job_id,
        models.Subtask.status == "COMPLETED",
    ).all()

    if not subtasks:
        raise Exception("No completed subtasks to aggregate")

    # 2. Download all model weights alongside their sample counts
    model_weights = []   # list of state_dict tensors
    sample_counts = []   # list of n_k values

    for subtask in subtasks:
        if not subtask.result_file_url:
            continue

        print(f"⬇️  Downloading result from subtask {subtask.id} ({subtask.chunk_row_count} rows)...")

        success = False
        for attempt in range(3):
            try:
                resp = requests.get(subtask.result_file_url, timeout=30)
                if resp.status_code == 200:
                    weights = torch.load(io.BytesIO(resp.content), map_location="cpu")
                    model_weights.append(weights)
                    # Fall back to 1 if row count wasn't stored (old subtasks)
                    sample_counts.append(subtask.chunk_row_count or 1)
                    success = True
                    break
                else:
                    print(f"   ⚠️  Status {resp.status_code}. Retrying ({attempt+1}/3)...")
                    time.sleep(1)
            except Exception as e:
                print(f"   ⚠️  Download error (attempt {attempt+1}): {e}")
                time.sleep(1)

        if not success:
            print(f"   ❌ Could not download weights for subtask {subtask.id}. Skipping.")

    if not model_weights:
        raise Exception("No model weights could be downloaded")

    # 3. Weighted Federated Averaging
    #    N = total samples across all participating workers
    total_samples = sum(sample_counts)
    print(f"➗ FedAvg: {len(model_weights)} models, {total_samples} total samples")
    for i, count in enumerate(sample_counts):
        weight_pct = (count / total_samples) * 100
        print(f"   Worker {i+1}: {count} rows ({weight_pct:.1f}% weight)")

    keys = model_weights[0].keys()
    averaged_weights = {}

    for key in keys:
        # Weighted sum: Σ (n_k / N) * w_k
        weighted_sum = torch.zeros_like(model_weights[0][key].float())
        for w, n_k in zip(model_weights, sample_counts):
            weighted_sum += (n_k / total_samples) * w[key].float()
        averaged_weights[key] = weighted_sum

    # 4. Compute convergence_delta: how much weighted avg differs from naive uniform avg.
    #    This quantifies the effect of unequal data distribution across workers.
    uniform_weights = {}
    for key in keys:
        tensors = [w[key].float() for w in model_weights]
        uniform_weights[key] = torch.mean(torch.stack(tensors), dim=0)

    delta_sq_sum = 0.0
    for key in keys:
        diff = averaged_weights[key] - uniform_weights[key]
        delta_sq_sum += diff.pow(2).sum().item()
    convergence_delta = math.sqrt(delta_sq_sum)
    print(f"📐 Convergence delta (weighted vs uniform): {convergence_delta:.6f}")

    # 5. Save and upload the aggregated model
    final_bytes = io.BytesIO()
    torch.save(averaged_weights, final_bytes)
    final_bytes.seek(0)

    file_path = f"jobs/{job_id}/final_model.pth"
    final_url = upload_bytes_to_supabase(final_bytes.getvalue(), file_path, "application/octet-stream")

    print(f"✅ Aggregation complete! Final model: {final_url}")
    return final_url, convergence_delta
