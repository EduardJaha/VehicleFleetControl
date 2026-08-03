from datetime import datetime
import mimetypes

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import (
    Attachment,
    AccidentFile,
    DocumentVersion,
    Inspection,
    ServiceBill,
    User,
    VehicleAccident,
    VehicleFuel,
    VehicleConditionRecord,
    VehiclePaper,
    VehicleService,
    WorkOrder,
)
from app.schemas import AttachmentOut, UserRole
from app.services.audit import record_audit
from app.utils.files import attachment_path, legacy_upload_path, safe_original_filename, store_upload

router = APIRouter()
UPLOAD_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.mechanic, UserRole.finance, UserRole.driver)
ENTITY_MODELS = {
    "VehicleService": VehicleService,
    "VehicleFuel": VehicleFuel,
    "VehiclePaper": VehiclePaper,
    "DocumentVersion": DocumentVersion,
    "VehicleAccident": VehicleAccident,
    "Inspection": Inspection,
    "WorkOrder": WorkOrder,
    "VehicleConditionRecord": VehicleConditionRecord,
}


def authorize_entity_access(current_user: User, entity_type: str, entity) -> None:
    if entity_type == "VehicleAccident" and current_user.role == UserRole.driver.value:
        if not current_user.driver_profile or current_user.driver_profile.id != entity.driver_id:
            raise HTTPException(
                status_code=403,
                detail="Drivers can only access attachments for their own Accident records.",
            )
    if entity_type == "VehicleConditionRecord" and current_user.role == UserRole.driver.value:
        if not current_user.driver_profile or current_user.driver_profile.id != entity.driver_id:
            raise HTTPException(
                status_code=403,
                detail="Drivers can only access attachments for their own Vehicle usage.",
            )
    document = None
    if entity_type == "VehiclePaper":
        document = entity
    elif entity_type == "DocumentVersion":
        document = entity.document
    if document is not None:
        if document.archived:
            raise HTTPException(status_code=404, detail="Related record not found.")
        if current_user.role == UserRole.driver.value:
            if not current_user.driver_profile or current_user.driver_profile.id != document.driver_id:
                raise HTTPException(status_code=403, detail="Drivers can only access their own Documents.")


def attachment_out(row: Attachment) -> AttachmentOut:
    return AttachmentOut(
        id=row.id,
        original_filename=row.original_filename,
        mime_type=row.mime_type,
        file_size=row.file_size,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        uploaded_at=row.uploaded_at.isoformat(),
    )


@router.get("", response_model=list[AttachmentOut])
def list_files(
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model = ENTITY_MODELS.get(entity_type.strip())
    entity = db.get(model, entity_id) if model else None
    if not entity or getattr(entity, "archived", False):
        raise HTTPException(status_code=404, detail="Related record not found.")
    authorize_entity_access(current_user, entity_type.strip(), entity)
    rows = db.query(Attachment).filter(
        Attachment.entity_type == entity_type.strip(),
        Attachment.entity_id == entity_id,
        Attachment.archived.is_(False),
    ).order_by(Attachment.uploaded_at, Attachment.id).all()
    return [attachment_out(row) for row in rows]


@router.post("", response_model=AttachmentOut, status_code=201)
async def upload_file(
    entity_type: str = Form(...),
    entity_id: int = Form(...),
    category: str = Form("auto"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*UPLOAD_ROLES)),
):
    normalized_entity = entity_type.strip()
    if normalized_entity not in ENTITY_MODELS:
        raise HTTPException(status_code=422, detail="Unsupported attachment entity type.")
    if category not in {"auto", "document", "image"}:
        raise HTTPException(status_code=422, detail="category must be auto, document, or image.")
    entity = db.get(ENTITY_MODELS[normalized_entity], entity_id)
    if not entity or getattr(entity, "archived", False):
        raise HTTPException(status_code=404, detail="Related record not found.")
    authorize_entity_access(current_user, normalized_entity, entity)
    stored = await store_upload(file, normalized_entity.lower(), category)
    attachment = Attachment(
        original_filename=stored.original_filename,
        stored_filename=stored.stored_filename,
        storage_path=stored.storage_path,
        mime_type=stored.mime_type,
        file_size=stored.file_size,
        uploaded_by=current_user.id,
        entity_type=normalized_entity,
        entity_id=entity_id,
    )
    db.add(attachment)
    db.flush()
    if normalized_entity == "VehicleAccident":
        db.add(AccidentFile(
            vehicle_accident_id=entity_id,
            file_path=f"/api/v1/files/{attachment.id}/download",
        ))
    record_audit(
        db, action="Document uploaded", entity_type=normalized_entity, entity_id=entity_id,
        user=current_user,
        new_values={"attachment_id": attachment.id, "filename": attachment.original_filename, "mime_type": attachment.mime_type, "file_size": attachment.file_size},
        description=f"Attachment #{attachment.id} uploaded.",
    )
    db.commit()
    return attachment_out(attachment)


@router.get("/legacy/download")
def download_legacy_file(
    path: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    authorized = (
        db.query(VehiclePaper).filter(VehiclePaper.file_path == path, VehiclePaper.archived.is_(False)).first()
        or db.query(VehicleFuel).filter(VehicleFuel.bill_file_path == path, VehicleFuel.archived.is_(False)).first()
        or db.query(ServiceBill).join(ServiceBill.service).filter(
            ServiceBill.file_path == path, VehicleService.archived.is_(False)
        ).first()
        or db.query(AccidentFile).join(AccidentFile.accident).filter(
            AccidentFile.file_path == path, VehicleAccident.archived.is_(False)
        ).first()
    )
    if not authorized:
        raise HTTPException(status_code=404, detail="File not found.")
    if isinstance(authorized, VehiclePaper):
        authorize_entity_access(current_user, "VehiclePaper", authorized)
    file_path = legacy_upload_path(path)
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    record_audit(
        db, action="Document downloaded", entity_type="LegacyAttachment", entity_id=None,
        user=current_user, new_values={"filename": file_path.name},
        description="Legacy attachment downloaded.",
    )
    db.commit()
    return FileResponse(
        file_path, media_type=mime_type, filename=safe_original_filename(file_path.name),
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.get("/{file_id}/download")
def download_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    attachment = db.query(Attachment).filter(Attachment.id == file_id, Attachment.archived.is_(False)).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="File not found.")
    model = ENTITY_MODELS.get(attachment.entity_type)
    entity = db.get(model, attachment.entity_id) if model else None
    if not entity or getattr(entity, "archived", False):
        raise HTTPException(status_code=404, detail="Related record not found.")
    authorize_entity_access(current_user, attachment.entity_type, entity)
    path = attachment_path(attachment.storage_path)
    record_audit(
        db, action="Document downloaded", entity_type=attachment.entity_type,
        entity_id=attachment.entity_id, user=current_user,
        new_values={"attachment_id": attachment.id},
        description=f"Attachment #{attachment.id} downloaded.",
    )
    db.commit()
    return FileResponse(
        path,
        media_type=attachment.mime_type,
        filename=attachment.original_filename,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.delete("/{file_id}")
def archive_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager)),
):
    attachment = db.get(Attachment, file_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="File not found.")
    attachment.archived = True
    attachment.archived_at = datetime.utcnow()
    attachment.archived_by = current_user.id
    record_audit(
        db, action="Document archived", entity_type=attachment.entity_type,
        entity_id=attachment.entity_id, user=current_user,
        new_values={"attachment_id": attachment.id, "archived": True},
        description=f"Attachment #{attachment.id} archived.",
    )
    db.commit()
    return {"message": "File archived."}
