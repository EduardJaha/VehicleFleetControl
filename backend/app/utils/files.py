from pathlib import Path
from uuid import uuid4
from fastapi import UploadFile, Request
from app.core.config import get_settings

settings = get_settings()


def safe_filename(filename: str) -> str:
    return Path(filename).name.replace("/", "_").replace("\\", "_")


async def save_upload(file: UploadFile, subfolder: str = "") -> str:
    base = settings.uploads_path
    target_dir = base / subfolder if subfolder else base
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4()}_{safe_filename(file.filename or 'upload')}"
    target = target_dir / filename
    content = await file.read()
    target.write_bytes(content)
    rel = target.as_posix()
    return rel


def delete_upload(file_path: str | None) -> None:
    if not file_path:
        return
    path = Path(file_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except OSError:
        pass


def file_url(file_path: str | None, request: Request) -> str | None:
    if not file_path:
        return None
    path = file_path.replace("\\", "/")
    if "/uploads/" in path:
        path = "uploads/" + path.split("/uploads/", 1)[1]
    elif not path.startswith("uploads/"):
        path = "uploads/" + Path(path).name
    return str(request.base_url).rstrip("/") + "/" + path
