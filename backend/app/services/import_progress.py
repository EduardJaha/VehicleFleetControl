"""Atomic private progress sidecars remain readable during SQLite write transactions."""
import json
import io
from app.services.storage import get_storage
from pathlib import Path

from app.core.config import get_settings


def path_for(job):
    base = get_settings().uploads_path.resolve()
    path = (base / job.source_path).resolve()
    if base not in path.parents:
        raise ValueError("Invalid import source path")
    return Path(str(path) + ".progress.json")


def write_progress(job, status, processed, total):
    data = json.dumps({"phase": status, "processed_rows": processed,
                       "progress_percent": min(100, int(processed * 100 / total)) if total else 100}).encode()
    get_storage().put(job.source_path + ".progress.json", io.BytesIO(data), "application/json")


def read_progress(job):
    if job.status not in {"Validating", "Importing"}:
        return {"phase": job.status, "processed_rows": job.total_rows if job.status != "Uploaded" else 0,
                "progress_percent": 0 if job.status == "Uploaded" else 100}
    try:
        with get_storage().open(job.source_path + ".progress.json") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return {"phase": job.status, "processed_rows": 0, "progress_percent": 0}
