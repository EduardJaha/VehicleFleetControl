"""Atomic private progress sidecars remain readable during SQLite write transactions."""
import json
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings


def path_for(job):
    base = get_settings().uploads_path.resolve()
    path = (base / job.source_path).resolve()
    if base not in path.parents:
        raise ValueError("Invalid import source path")
    return Path(str(path) + ".progress.json")


def write_progress(job, status, processed, total):
    path = path_for(job)
    temporary = path.with_name(path.name + "." + uuid4().hex)
    temporary.write_text(json.dumps({"phase": status, "processed_rows": processed,
                                   "progress_percent": min(100, int(processed * 100 / total)) if total else 100}))
    temporary.replace(path)


def read_progress(job):
    if job.status not in {"Validating", "Importing"}:
        return {"phase": job.status, "processed_rows": job.total_rows if job.status != "Uploaded" else 0,
                "progress_percent": 0 if job.status == "Uploaded" else 100}
    try:
        return json.loads(path_for(job).read_text())
    except (OSError, ValueError):
        return {"phase": job.status, "processed_rows": 0, "progress_percent": 0}
