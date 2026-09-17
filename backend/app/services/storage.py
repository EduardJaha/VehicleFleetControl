"""Private storage. Callers must authorize tenant and entity access before reading."""
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import BinaryIO, Protocol
from urllib.parse import quote
import shutil
import mimetypes
import os
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.core.config import get_settings


def validate_key(key: str) -> str:
    if not key or key.startswith('/') or '\\' in key or any(p in {'', '.', '..'} for p in key.split('/')):
        raise ValueError('Invalid storage key')
    return PurePosixPath(key).as_posix()


class StorageProvider(Protocol):
    def put(self, key: str, source: BinaryIO, content_type: str) -> None: ...
    def open(self, key: str) -> BinaryIO: ...
    def check(self) -> None: ...


class LocalStorageProvider:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def path(self, key: str) -> Path:
        path = (self.root / validate_key(key)).resolve()
        if self.root not in path.parents:
            raise ValueError('Invalid storage path')
        return path

    def put(self, key: str, source: BinaryIO, content_type: str) -> None:
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.' + uuid4().hex)
        try:
            with temporary.open('xb') as output:
                shutil.copyfileobj(source, output)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def open(self, key: str) -> BinaryIO:
        return self.path(key).open('rb')

    def check(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not os.access(self.root, os.R_OK | os.W_OK):
            raise OSError('Storage unavailable')


class ObjectStorageProvider:
    def __init__(self, settings):
        import boto3
        from botocore.config import Config
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            's3', endpoint_url=settings.s3_endpoint or None,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
            region_name=settings.s3_region,
            config=Config(connect_timeout=3, read_timeout=30, retries={'max_attempts': 2},
                          s3={'addressing_style': settings.s3_addressing_style}),
        )

    def put(self, key: str, source: BinaryIO, content_type: str) -> None:
        self.client.upload_fileobj(source, self.bucket, validate_key(key), ExtraArgs={'ContentType': content_type})

    def open(self, key: str) -> BinaryIO:
        from botocore.exceptions import ClientError
        try:
            return self.client.get_object(Bucket=self.bucket, Key=validate_key(key))['Body']
        except ClientError as exc:
            if exc.response['Error']['Code'] in {'NoSuchKey', '404', 'NotFound'}:
                raise FileNotFoundError from None
            raise

    def check(self) -> None:
        self.client.head_bucket(Bucket=self.bucket)


def get_storage() -> StorageProvider:
    settings = get_settings()
    if settings.storage_provider == 's3':
        return ObjectStorageProvider(settings)
    return LocalStorageProvider(settings.uploads_path)


@contextmanager
def materialize(key: str):
    """Seekable private temporary copy for XLSX/CSV parsers, removed on every exit."""
    try:
        source = get_storage().open(key)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, 'File not found.') from None
    with source, TemporaryDirectory(prefix='fleet-source-') as folder:
        path = Path(folder) / PurePosixPath(key).name
        with path.open('wb') as output:
            shutil.copyfileobj(source, output)
        yield path


def download_response(key: str, filename: str, media_type: str | None = None, *, inline: bool = False):
    try:
        stream = get_storage().open(key)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, 'File not found.') from None
    except Exception:
        raise HTTPException(503, 'File storage is temporarily unavailable.') from None

    def chunks():
        try:
            while chunk := stream.read(1024 * 1024):
                yield chunk
        finally:
            stream.close()

    return StreamingResponse(chunks(), media_type=media_type or mimetypes.guess_type(filename)[0] or 'application/octet-stream',
        headers={'Content-Disposition': f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(filename, safe='')}",
                 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store'},
        background=BackgroundTask(stream.close))
