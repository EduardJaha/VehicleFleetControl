from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from tempfile import TemporaryDirectory
from starlette.concurrency import run_in_threadpool
from app.services.storage import get_storage, validate_key

from fastapi import HTTPException, Request, UploadFile

from app.core.config import get_settings

settings = get_settings()
CHUNK_SIZE = 1024 * 1024
DOCUMENT_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class StoredUpload:
    original_filename: str
    stored_filename: str
    storage_path: str
    mime_type: str
    file_size: int


class AntivirusScanner:
    """Extension point for a ClamAV or hosted scanning implementation."""

    def scan(self, path: Path) -> None:
        return None


def scanner() -> AntivirusScanner:
    # Local development deliberately uses the no-op provider. A production
    # provider can implement this interface without changing upload routes.
    return AntivirusScanner()


def safe_original_filename(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        return "upload"
    return name[:255]


def _content_matches(mime_type: str, header: bytes) -> bool:
    if mime_type == "application/pdf":
        return header.startswith(b"%PDF-")
    if mime_type == "image/jpeg":
        return header.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/webp":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    return False


def _upload_policy(file: UploadFile, category: str) -> tuple[set[str], set[str], int]:
    mime_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if category == "document":
        return DOCUMENT_EXTENSIONS, settings.document_mime_types, settings.max_document_size
    if category == "image":
        return IMAGE_EXTENSIONS, settings.image_mime_types, settings.max_image_size
    return (
        DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS,
        settings.document_mime_types | settings.image_mime_types,
        max(settings.max_document_size, settings.max_image_size),
    )


async def store_upload(file: UploadFile, subfolder: str = "", category: str = "auto") -> StoredUpload:
    original = safe_original_filename(file.filename or "upload")
    extension = Path(original).suffix.lower()
    allowed_extensions, allowed_mime_types, maximum_size = _upload_policy(file, category)
    mime_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if extension not in allowed_extensions:
        raise HTTPException(status_code=415, detail=f"File extension '{extension or '(none)'}' is not allowed.")
    if mime_type not in allowed_mime_types:
        raise HTTPException(status_code=415, detail=f"MIME type '{mime_type or '(missing)'}' is not allowed.")

    stored_filename = f"{uuid4().hex}{extension}"
    try:
        key = validate_key(f"{subfolder}/{stored_filename}" if subfolder else stored_filename)
    except ValueError:
        raise HTTPException(400, "Invalid upload destination.") from None
    temporary = TemporaryDirectory(prefix="fleet-upload-")
    target = Path(temporary.name) / stored_filename

    file_size = 0
    header = b""
    try:
        with target.open("xb") as output:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                if not header:
                    header = chunk[:32]
                file_size += len(chunk)
                if file_size > maximum_size:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the maximum size of {maximum_size // (1024 * 1024)} MB.",
                    )
                output.write(chunk)
        if file_size == 0:
            raise HTTPException(status_code=400, detail="Empty files are not allowed.")
        if not _content_matches(mime_type, header):
            raise HTTPException(status_code=415, detail="File content does not match its declared type.")
        scanner().scan(target)
        def persist():
            with target.open("rb") as source:
                get_storage().put(key, source, mime_type)
        await run_in_threadpool(persist)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
        temporary.cleanup()

    return StoredUpload(
        original_filename=original,
        stored_filename=stored_filename,
        storage_path=key,
        mime_type=mime_type,
        file_size=file_size,
    )


async def save_upload(file: UploadFile, subfolder: str = "", category: str = "auto") -> str:
    """Compatibility wrapper for legacy file columns, with secure validation."""
    stored = await store_upload(file, subfolder, category)
    return f"{settings.uploads_path.as_posix()}/{stored.storage_path}"


def attachment_path(storage_path: str) -> Path:
    base = settings.uploads_path.resolve()
    path = (base / storage_path).resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return path


def legacy_upload_path(file_path: str) -> Path:
    base = settings.uploads_path.resolve()
    candidate = Path(file_path.replace("\\", "/"))
    if candidate.is_absolute():
        path = candidate.resolve()
    else:
        parts = list(candidate.parts)
        if parts and parts[0] == base.name:
            parts = parts[1:]
        path = base.joinpath(*parts).resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return path


def delete_upload(file_path: str | None) -> None:
    # Physical deletion is reserved for explicit retention jobs. Normal archive
    # operations retain files with their business history.
    return None


def file_url(file_path: str | None, request: Request) -> str | None:
    # Kept for legacy response compatibility. New uploads return authenticated
    # /api/v1/files/{id}/download links instead.
    return file_path


def legacy_storage_key(file_path: str) -> str:
    base = settings.uploads_path.resolve()
    candidate = Path(file_path.replace("\\", "/"))
    if candidate.is_absolute():
        try:
            key = candidate.resolve().relative_to(base).as_posix()
        except ValueError:
            raise HTTPException(404, "File not found.") from None
    else:
        parts = list(candidate.parts)
        if parts and parts[0] == base.name:
            parts = parts[1:]
        key = "/".join(parts)
    try:
        return validate_key(key)
    except ValueError:
        raise HTTPException(404, "File not found.") from None
