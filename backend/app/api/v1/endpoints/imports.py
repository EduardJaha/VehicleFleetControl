from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.authorization import has_permission, require_permission
from app.core.security import get_current_user
from app.db.session import get_db
from app.models import ImportJob, ImportRowResult, User
from app.schemas import (
    ImportConfirmRequest,
    ImportEntityType,
    ImportFieldDefinition,
    ImportJobOut,
    ImportJobPage,
    ImportRowResultOut,
    ImportUpdateMode,
    ImportUploadOut,
    ImportValidationRequest,
    LanguageCode,
    UserRole,
)
from app.services.audit import record_audit
from app.services.imports import (
    confirm_job,
    error_report,
    fields_for,
    store_import,
    suggested_mapping,
    template_bytes,
    validate_job,
)

router = APIRouter(dependencies=[Depends(require_permission("imports.manage"))])
IMPORT_ROLES = (UserRole.admin, UserRole.fleet_manager)


def authorize_job(job: ImportJob | None, current_user: User, db: Session | None = None) -> ImportJob:
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found.")
    if not has_permission(db, current_user, "users.manage") and job.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="You can only access your own import jobs.")
    return job


def row_out(row: ImportRowResult) -> ImportRowResultOut:
    return ImportRowResultOut(
        id=row.id,
        row_number=row.row_number,
        status=row.status,
        action=row.action,
        raw_data=row.raw_data or {},
        mapped_data=row.mapped_data,
        errors=row.errors or [],
        duplicate_fields=row.duplicate_fields or [],
        target_id=row.target_id,
    )


def job_out(job: ImportJob, rows: list[ImportRowResult] | None = None) -> ImportJobOut:
    return ImportJobOut(
        id=job.id,
        entity_type=job.entity_type,
        filename=job.filename,
        uploaded_by=job.uploaded_by,
        status=job.status,
        column_mapping=job.column_mapping,
        update_mode=job.update_mode,
        transaction_mode=job.transaction_mode,
        source_headers=job.source_headers or [],
        total_rows=job.total_rows,
        valid_rows=job.valid_rows,
        invalid_rows=job.invalid_rows,
        created_rows=job.created_rows,
        updated_rows=job.updated_rows,
        skipped_rows=job.skipped_rows,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        error_report_path=job.error_report_path,
        created_at=job.created_at.isoformat(),
        rows=[row_out(row) for row in (rows or [])],
    )


@router.get("/templates/{entity_type}")
def download_template(
    entity_type: ImportEntityType,
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    language: LanguageCode = LanguageCode.en,
    current_user: User = Depends(require_permission("imports.manage")),
):
    content, filename, media_type = template_bytes(entity_type.value, language.value, format)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/upload", response_model=ImportUploadOut, status_code=201)
async def upload_import(
    entity_type: ImportEntityType = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("imports.manage")),
):
    job = await store_import(file, entity_type.value, current_user, db)
    mapping = suggested_mapping(job.entity_type, job.source_headers or [])
    return ImportUploadOut(
        id=job.id,
        entity_type=job.entity_type,
        filename=job.filename,
        status=job.status,
        headers=job.source_headers or [],
        fields=[ImportFieldDefinition(**field) for field in fields_for(job.entity_type)],
        suggested_mapping=mapping,
    )


@router.get("", response_model=ImportJobPage)
def list_imports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    entity_type: ImportEntityType | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("imports.manage")),
):
    query = db.query(ImportJob)
    if not has_permission(db, current_user, "users.manage"):
        query = query.filter(ImportJob.uploaded_by == current_user.id)
    if entity_type:
        query = query.filter(ImportJob.entity_type == entity_type.value)
    if status:
        query = query.filter(ImportJob.status == status)
    total = query.order_by(None).count()
    rows = query.order_by(ImportJob.created_at.desc(), ImportJob.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ImportJobPage(
        items=[job_out(job) for job in rows], page=page, page_size=page_size,
        total=total, pages=(total + page_size - 1) // page_size,
    )


@router.get("/{job_id}", response_model=ImportJobOut)
def get_import(
    job_id: int,
    row_status: str | None = None,
    row_limit: int = Query(200, ge=0, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("imports.manage")),
):
    job = authorize_job(db.get(ImportJob, job_id), current_user)
    query = db.query(ImportRowResult).filter(ImportRowResult.import_job_id == job.id)
    if row_status:
        query = query.filter(ImportRowResult.status == row_status)
    rows = query.order_by(ImportRowResult.row_number).limit(row_limit).all() if row_limit else []
    return job_out(job, rows)


@router.post("/{job_id}/validate", response_model=ImportJobOut)
def dry_run_import(
    job_id: int,
    payload: ImportValidationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("imports.manage")),
):
    job = authorize_job(db.get(ImportJob, job_id), current_user)
    validated = validate_job(db, job, payload.column_mapping, payload.update_mode)
    rows = db.query(ImportRowResult).filter(ImportRowResult.import_job_id == job.id).order_by(ImportRowResult.row_number).limit(200).all()
    return job_out(validated, rows)


@router.post("/{job_id}/confirm", response_model=ImportJobOut)
def confirm_import(
    job_id: int,
    payload: ImportConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("imports.manage")),
):
    job = authorize_job(db.get(ImportJob, job_id), current_user)
    result = confirm_job(db, job, current_user, payload.update_mode, payload.transaction_mode)
    rows = db.query(ImportRowResult).filter(ImportRowResult.import_job_id == job_id).order_by(ImportRowResult.row_number).limit(200).all()
    return job_out(result, rows)


@router.post("/{job_id}/cancel", response_model=ImportJobOut)
def cancel_import(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("imports.manage")),
):
    job = authorize_job(db.get(ImportJob, job_id), current_user)
    if job.status not in {"Uploaded", "Ready"}:
        raise HTTPException(status_code=409, detail="Only Uploaded or Ready imports can be cancelled.")
    job.status = "Cancelled"
    job.completed_at = datetime.utcnow()
    record_audit(
        db, action="Import cancelled", entity_type="ImportJob", entity_id=job.id, user=current_user,
        new_values={"status": "Cancelled"}, description=f"Import job #{job.id} cancelled.",
    )
    db.commit()
    db.refresh(job)
    return job_out(job)


@router.get("/{job_id}/errors")
def download_errors(
    job_id: int,
    language: LanguageCode = LanguageCode.en,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("imports.manage")),
):
    job = authorize_job(db.get(ImportJob, job_id), current_user)
    rows = db.query(ImportRowResult).filter(ImportRowResult.import_job_id == job.id).order_by(ImportRowResult.row_number).all()
    content = error_report(job, rows, language.value)
    filename = f"import-{job.id}-errors.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
