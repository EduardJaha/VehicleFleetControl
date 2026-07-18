from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session, joinedload
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import Attachment, User, VehiclePaper
from app.schemas import UserRole, VehiclePaperListOut
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate
from app.utils.files import file_url, store_upload
from app.services.audit import record_audit, snapshot

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/upload")
async def upload_paper(
    license_plate: str = Form(...),
    document_type: str = Form(...),
    issue_date: str = Form(...),
    expiry_date: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager)),
):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"No vehicle found with license plate '{license_plate}'.")
    existing = db.query(VehiclePaper).filter(
        VehiclePaper.vehicle_id == vehicle.id,
        VehiclePaper.document_type.ilike(document_type),
        VehiclePaper.archived.is_(False),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"A document of type '{document_type}' is already registered for vehicle '{vehicle.license_plate}'.")
    issue = parse_date(issue_date, "IssueDate")
    expiry = parse_date(expiry_date, "ExpiryDate")
    if expiry <= issue:
        raise HTTPException(status_code=400, detail="Expiry date must be after issue date.")
    stored = await store_upload(file, "documents", "document")
    paper = VehiclePaper(vehicle_id=vehicle.id, document_type=document_type, file_path="", issue_date=issue, expiry_date=expiry)
    db.add(paper)
    db.flush()
    attachment = Attachment(
        original_filename=stored.original_filename, stored_filename=stored.stored_filename,
        storage_path=stored.storage_path, mime_type=stored.mime_type, file_size=stored.file_size,
        uploaded_by=current_user.id, entity_type="VehiclePaper", entity_id=paper.id,
    )
    db.add(attachment)
    db.flush()
    paper.file_path = f"/api/v1/files/{attachment.id}/download"
    record_audit(
        db, action="Document uploaded", entity_type="VehiclePaper", entity_id=paper.id,
        user=current_user, new_values=snapshot(paper),
        description=f"{document_type} uploaded for {vehicle.license_plate}.",
    )
    db.commit()
    db.refresh(paper)
    return {"message": f"'{document_type}' document uploaded successfully for vehicle {vehicle.license_plate}.", "id": paper.id}


@router.get("/all", response_model=list[VehiclePaperListOut])
def all_papers(
    request: Request,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if include_archived and current_user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Only Admin users can include archived Documents.")
    query = db.query(VehiclePaper).options(joinedload(VehiclePaper.vehicle))
    if not include_archived:
        query = query.filter(VehiclePaper.archived.is_(False))
    papers = query.order_by(VehiclePaper.expiry_date.asc()).all()
    return [
        VehiclePaperListOut(
            id=p.id,
            license_plate=p.vehicle.license_plate,
            vehicle_location=p.vehicle.vehicle_location,
            brand=p.vehicle.brand,
            model=p.vehicle.model,
            document_type=p.document_type,
            issue_date=format_date(p.issue_date) or "",
            expiry_date=format_date(p.expiry_date) or "",
            file_path=file_url(p.file_path, request) or "",
            archived=p.archived,
        )
        for p in papers
    ]


@router.delete("/{paper_id}")
def delete_paper(paper_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    paper = db.get(VehiclePaper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Document not found.")
    paper.archived = True
    paper.archived_at = datetime.utcnow()
    paper.archived_by = current_user.id
    record_audit(
        db, action="Document archived", entity_type="VehiclePaper", entity_id=paper.id,
        user=current_user, new_values={"archived": True},
        description=f"Document #{paper.id} archived.",
    )
    db.commit()
    return {"message": "Document archived successfully."}


@router.post("/{paper_id}/restore", response_model=VehiclePaperListOut)
def restore_paper(
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    paper = db.query(VehiclePaper).options(joinedload(VehiclePaper.vehicle)).filter(VehiclePaper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Document not found.")
    paper.archived = False
    paper.archived_at = None
    paper.archived_by = None
    record_audit(
        db, action="Document restored", entity_type="VehiclePaper", entity_id=paper.id,
        user=current_user, new_values={"archived": False},
        description=f"Document #{paper.id} restored.",
    )
    db.commit()
    return VehiclePaperListOut(
        id=paper.id, license_plate=paper.vehicle.license_plate,
        vehicle_location=paper.vehicle.vehicle_location, brand=paper.vehicle.brand,
        model=paper.vehicle.model, document_type=paper.document_type,
        issue_date=format_date(paper.issue_date) or "", expiry_date=format_date(paper.expiry_date) or "",
        file_path=paper.file_path, archived=False,
    )
