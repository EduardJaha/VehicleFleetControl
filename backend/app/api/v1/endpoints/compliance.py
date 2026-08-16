from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.authorization import active_role, own_records_only, require_permission
from app.core.security import get_current_user
from app.db.session import get_db
from app.models import (
    Attachment,
    DocumentRequirement,
    DocumentVersion,
    Driver,
    User,
    Vehicle,
    VehiclePaper,
)
from app.schemas import (
    DocumentComplianceDashboardOut,
    DocumentRequirementCreate,
    DocumentRequirementOut,
    DocumentRequirementUpdate,
    DocumentVerificationRequest,
    DocumentVersionOut,
    UserRole,
)
from app.services.audit import record_audit, snapshot
from app.services.document_compliance import (
    compliance_dashboard,
    requirement_applies_to_driver,
    requirement_applies_to_vehicle,
)
from app.utils.dates import parse_date
from app.utils.files import store_upload

router = APIRouter(dependencies=[Depends(require_permission("documents.view"))])
WRITE_ROLES = (UserRole.admin, UserRole.fleet_manager)


def requirement_out(row: DocumentRequirement) -> DocumentRequirementOut:
    return DocumentRequirementOut(
        id=row.id,
        document_type=row.document_type,
        applies_to_vehicle_category=row.applies_to_vehicle_category,
        applies_to_country=row.applies_to_country,
        applies_to_driver=row.applies_to_driver,
        required=row.required,
        validity_months=row.validity_months,
        warning_days=row.warning_days,
        is_active=row.is_active,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def version_out(row: DocumentVersion) -> DocumentVersionOut:
    return DocumentVersionOut(
        id=row.id,
        document_id=row.document_id,
        version_number=row.version_number,
        file_path=row.file_path,
        document_number=row.document_number,
        issuing_authority=row.issuing_authority,
        issue_date=row.issue_date.date().isoformat(),
        expiry_date=row.expiry_date.date().isoformat(),
        uploaded_by=row.uploaded_by,
        uploaded_at=row.uploaded_at.isoformat(),
        verified_by=row.verified_by,
        verified_at=row.verified_at.isoformat() if row.verified_at else None,
        rejection_reason=row.rejection_reason,
        renewal_status=row.renewal_status,
        is_current=row.is_current,
        archived=row.archived,
    )


def _authorize_document(db: Session, current_user: User, document: VehiclePaper) -> None:
    if active_role(db, current_user) != UserRole.driver.value and not own_records_only(db, current_user, "documents.view"):
        return
    profile = current_user.driver_profile
    if not profile or document.driver_id != profile.id:
        raise HTTPException(status_code=403, detail="Drivers can only access their own Documents.")


def _owner_and_requirement(
    db: Session,
    *,
    owner_type: str,
    owner_id: int,
    requirement_id: int,
    current_user: User,
) -> tuple[Vehicle | Driver, DocumentRequirement]:
    requirement = db.get(DocumentRequirement, requirement_id)
    if not requirement or not requirement.is_active:
        raise HTTPException(status_code=404, detail="Active Document Requirement not found.")
    normalized = owner_type.strip().casefold()
    if normalized == "vehicle":
        owner = db.get(Vehicle, owner_id)
        if not owner or owner.archived:
            raise HTTPException(status_code=404, detail="Vehicle not found.")
        if not requirement_applies_to_vehicle(requirement, owner):
            raise HTTPException(status_code=422, detail="This Requirement does not apply to the selected Vehicle.")
        if active_role(db, current_user) == UserRole.driver.value or own_records_only(db, current_user, "documents.upload"):
            raise HTTPException(status_code=403, detail="Drivers cannot upload Vehicle Documents.")
        return owner, requirement
    if normalized == "driver":
        owner = db.get(Driver, owner_id)
        if not owner or owner.archived:
            raise HTTPException(status_code=404, detail="Driver not found.")
        if not requirement_applies_to_driver(requirement, owner):
            raise HTTPException(status_code=422, detail="This Requirement does not apply to Drivers.")
        if (active_role(db, current_user) == UserRole.driver.value or own_records_only(db, current_user, "documents.upload")) and (
            not current_user.driver_profile or current_user.driver_profile.id != owner.id
        ):
            raise HTTPException(status_code=403, detail="Drivers can only upload their own Documents.")
        return owner, requirement
    raise HTTPException(status_code=422, detail="owner_type must be Vehicle or Driver.")


def _validate_dates(issue_date: str, expiry_date: str):
    issue = parse_date(issue_date, "IssueDate")
    expiry = parse_date(expiry_date, "ExpiryDate")
    if expiry <= issue:
        raise HTTPException(status_code=400, detail="Expiry date must be after issue date.")
    return issue, expiry


@router.get("/document-requirements", response_model=list[DocumentRequirementOut])
def list_requirements(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    query = db.query(DocumentRequirement)
    if not include_inactive:
        query = query.filter(DocumentRequirement.is_active.is_(True))
    return [requirement_out(row) for row in query.order_by(DocumentRequirement.document_type, DocumentRequirement.id).all()]


@router.post("/document-requirements", response_model=DocumentRequirementOut, status_code=201)
def create_requirement(
    payload: DocumentRequirementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("documents.verify")),
):
    row = DocumentRequirement(**payload.model_dump())
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="Document Requirement created",
        entity_type="DocumentRequirement",
        entity_id=row.id,
        user=current_user,
        new_values=snapshot(row),
        description=f"Requirement for {row.document_type} created.",
    )
    db.commit()
    db.refresh(row)
    return requirement_out(row)


@router.put("/document-requirements/{requirement_id}", response_model=DocumentRequirementOut)
def update_requirement(
    requirement_id: int,
    payload: DocumentRequirementUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("documents.verify")),
):
    row = db.get(DocumentRequirement, requirement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document Requirement not found.")
    old_values = snapshot(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    record_audit(
        db,
        action="Document Requirement updated",
        entity_type="DocumentRequirement",
        entity_id=row.id,
        user=current_user,
        old_values=old_values,
        new_values=snapshot(row),
        description=f"Requirement for {row.document_type} updated.",
    )
    db.commit()
    return requirement_out(row)


@router.get("/documents", response_model=DocumentComplianceDashboardOut)
def get_document_compliance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = compliance_dashboard(db)
    if active_role(db, current_user) == UserRole.driver.value or own_records_only(db, current_user, "documents.view"):
        driver_id = current_user.driver_profile.id if current_user.driver_profile else None
        result["items"] = [
            item for item in result["items"]
            if item["owner_type"] == "Driver" and item["owner_id"] == driver_id
        ]
        for key in ("missing_required", "expired", "expiring_in_7_days", "expiring_in_30_days", "renewal_in_progress"):
            allowed_ids = {(item["requirement_id"], item["owner_id"]) for item in result["items"]}
            result[key] = [
                item for item in result[key]
                if (item["requirement_id"], item["owner_id"]) in allowed_ids
            ]
        result["compliance_by_vehicle"] = []
        result["compliance_by_department"] = []
        result["compliance_by_location"] = []
        result["compliance_by_driver"] = [
            row for row in result["compliance_by_driver"]
            if current_user.driver_profile and row["name"] == current_user.driver_profile.full_name
        ]
        compliant = sum(1 for item in result["items"] if item["status"] in {"Valid", "Expiring Soon"})
        result["overall_compliance_rate"] = round(compliant / len(result["items"]) * 100, 2) if result["items"] else 100.0
    return result


@router.post("/documents", response_model=DocumentVersionOut, status_code=201)
async def upload_document(
    owner_type: str = Form(...),
    owner_id: int = Form(...),
    requirement_id: int = Form(...),
    issue_date: str = Form(...),
    expiry_date: str = Form(...),
    document_number: str | None = Form(None),
    issuing_authority: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("documents.upload")),
):
    owner, requirement = _owner_and_requirement(
        db,
        owner_type=owner_type,
        owner_id=owner_id,
        requirement_id=requirement_id,
        current_user=current_user,
    )
    owner_filter = (
        VehiclePaper.vehicle_id == owner.id
        if isinstance(owner, Vehicle)
        else VehiclePaper.driver_id == owner.id
    )
    existing = db.query(VehiclePaper).filter(
        owner_filter,
        VehiclePaper.requirement_id == requirement.id,
        VehiclePaper.archived.is_(False),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="This required Document already exists; use renewal to add a version.")

    issue, expiry = _validate_dates(issue_date, expiry_date)
    stored = await store_upload(file, "documents", "document")
    paper = VehiclePaper(
        vehicle_id=owner.id if isinstance(owner, Vehicle) else None,
        driver_id=owner.id if isinstance(owner, Driver) else None,
        requirement_id=requirement.id,
        document_type=requirement.document_type,
        document_number=(document_number or "").strip() or None,
        issuing_authority=(issuing_authority or "").strip() or None,
        renewal_status="Submitted",
        file_path="",
        issue_date=issue,
        expiry_date=expiry,
    )
    db.add(paper)
    db.flush()
    attachment = Attachment(
        original_filename=stored.original_filename,
        stored_filename=stored.stored_filename,
        storage_path=stored.storage_path,
        mime_type=stored.mime_type,
        file_size=stored.file_size,
        uploaded_by=current_user.id,
        entity_type="DocumentVersion",
        entity_id=0,
    )
    db.add(attachment)
    db.flush()
    version = DocumentVersion(
        document_id=paper.id,
        version_number=1,
        attachment_id=attachment.id,
        file_path=f"/api/v1/files/{attachment.id}/download",
        document_number=paper.document_number,
        issuing_authority=paper.issuing_authority,
        issue_date=issue,
        expiry_date=expiry,
        uploaded_by=current_user.id,
        renewal_status="Submitted",
        is_current=True,
    )
    db.add(version)
    db.flush()
    attachment.entity_id = version.id
    paper.file_path = version.file_path
    record_audit(
        db,
        action="Document uploaded",
        entity_type="VehiclePaper",
        entity_id=paper.id,
        user=current_user,
        new_values={"version_id": version.id, "requirement_id": requirement.id, "owner_type": owner_type, "owner_id": owner.id},
        description=f"{requirement.document_type} version 1 uploaded.",
    )
    db.commit()
    return version_out(version)


@router.get("/documents/{document_id}/versions", response_model=list[DocumentVersionOut])
def list_versions(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = db.query(VehiclePaper).options(joinedload(VehiclePaper.versions)).filter(VehiclePaper.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    _authorize_document(db, current_user, document)
    return [version_out(row) for row in document.versions]


@router.post("/documents/{document_id}/renew", response_model=DocumentVersionOut, status_code=201)
async def renew_document(
    document_id: int,
    issue_date: str = Form(...),
    expiry_date: str = Form(...),
    document_number: str | None = Form(None),
    issuing_authority: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("documents.upload")),
):
    document = db.query(VehiclePaper).options(joinedload(VehiclePaper.versions)).filter(VehiclePaper.id == document_id).first()
    if not document or document.archived:
        raise HTTPException(status_code=404, detail="Document not found.")
    _authorize_document(db, current_user, document)
    issue, expiry = _validate_dates(issue_date, expiry_date)
    stored = await store_upload(file, "documents", "document")
    for previous in document.versions:
        previous.is_current = False
    next_number = (db.query(func.max(DocumentVersion.version_number)).filter(DocumentVersion.document_id == document.id).scalar() or 0) + 1
    attachment = Attachment(
        original_filename=stored.original_filename,
        stored_filename=stored.stored_filename,
        storage_path=stored.storage_path,
        mime_type=stored.mime_type,
        file_size=stored.file_size,
        uploaded_by=current_user.id,
        entity_type="DocumentVersion",
        entity_id=0,
    )
    db.add(attachment)
    db.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=next_number,
        attachment_id=attachment.id,
        file_path=f"/api/v1/files/{attachment.id}/download",
        document_number=(document_number or "").strip() or None,
        issuing_authority=(issuing_authority or "").strip() or None,
        issue_date=issue,
        expiry_date=expiry,
        uploaded_by=current_user.id,
        renewal_status="In Progress",
        is_current=True,
    )
    db.add(version)
    db.flush()
    attachment.entity_id = version.id
    document.file_path = version.file_path
    document.issue_date = issue
    document.expiry_date = expiry
    document.document_number = version.document_number
    document.issuing_authority = version.issuing_authority
    document.renewal_status = "In Progress"
    record_audit(
        db,
        action="Document renewal started",
        entity_type="VehiclePaper",
        entity_id=document.id,
        user=current_user,
        new_values={"version_id": version.id, "version_number": next_number},
        description=f"{document.document_type} renewal version {next_number} uploaded.",
    )
    db.commit()
    return version_out(version)


@router.post("/document-versions/{version_id}/verify", response_model=DocumentVersionOut)
def verify_version(
    version_id: int,
    payload: DocumentVerificationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("documents.verify")),
):
    version = db.query(DocumentVersion).options(joinedload(DocumentVersion.document)).filter(DocumentVersion.id == version_id).first()
    if not version or version.archived:
        raise HTTPException(status_code=404, detail="Document Version not found.")
    old_values = snapshot(version)
    version.verified_by = current_user.id
    version.verified_at = datetime.utcnow()
    version.rejection_reason = None if payload.approved else payload.rejection_reason
    version.renewal_status = "Approved" if payload.approved else "Rejected"
    if version.is_current:
        version.document.renewal_status = version.renewal_status
    record_audit(
        db,
        action="Document version verified" if payload.approved else "Document version rejected",
        entity_type="DocumentVersion",
        entity_id=version.id,
        user=current_user,
        old_values=old_values,
        new_values=snapshot(version),
        description=f"Document version #{version.id} {'approved' if payload.approved else 'rejected'}.",
    )
    db.commit()
    return version_out(version)


@router.delete("/documents/{document_id}")
def archive_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("documents.verify")),
):
    document = db.get(VehiclePaper, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    document.archived = True
    document.archived_at = datetime.utcnow()
    document.archived_by = current_user.id
    record_audit(
        db, action="Document archived", entity_type="VehiclePaper", entity_id=document.id,
        user=current_user, new_values={"archived": True}, description=f"Document #{document.id} archived.",
    )
    db.commit()
    return {"message": "Document archived successfully."}


@router.post("/documents/{document_id}/restore")
def restore_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("documents.verify")),
):
    document = db.get(VehiclePaper, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    document.archived = False
    document.archived_at = None
    document.archived_by = None
    record_audit(
        db, action="Document restored", entity_type="VehiclePaper", entity_id=document.id,
        user=current_user, new_values={"archived": False}, description=f"Document #{document.id} restored.",
    )
    db.commit()
    return {"message": "Document restored successfully."}
