"""Shared per-worker stats for the YOLO pipeline (multiprocessing-safe)."""
import multiprocessing as mp


MAX_FRAME_IDS_PER_WORKER = 30  # last N frame IDs to show on dashboard


def create_shared_stats(num_workers: int = 4) -> dict:
    """Create a manager-backed dict of worker stats, one dict per worker."""
    manager = mp.Manager()
    workers = manager.list()
    for i in range(num_workers):
        workers.append(
            manager.dict(
                {
                    "worker_id": i + 1,
                    "frames_processed": 0,
                    "last_latency_ms": 0.0,
                    "errors": 0,
                    "frame_ids": manager.list(),
                }
            )
        )
    return {"workers": workers, "manager": manager}


def snapshot_stats(shared: dict) -> list:
    """Return a plain list of worker stat dicts for JSON serialization."""
    out = []
    for w in shared["workers"]:
        out.append({
            "worker_id": w["worker_id"],
            "frames_processed": w["frames_processed"],
            "last_latency_ms": w["last_latency_ms"],
            "errors": w["errors"],
            "frame_ids": list(w["frame_ids"]),
        })
    return out
