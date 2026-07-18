from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session, joinedload
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import AccidentFile, Attachment, User, VehicleAccident
from app.schemas import AccidentOut, UserRole
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate
from app.utils.files import file_url, store_upload
from app.services.audit import record_audit, snapshot

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/report")
async def report_accident(
    license_plate: str = Form(...),
    accident_date: str = Form(...),
    location: str = Form(...),
    description: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager)),
):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Vehicle '{license_plate}' not found.")
    accident = VehicleAccident(vehicle_id=vehicle.id, accident_date=parse_date(accident_date, "AccidentDate"), location=location, description=description)
    db.add(accident)
    db.flush()
    for uploaded in files or []:
        if uploaded.filename:
            stored = await store_upload(uploaded, "accidents", "image")
            attachment = Attachment(
                original_filename=stored.original_filename, stored_filename=stored.stored_filename,
                storage_path=stored.storage_path, mime_type=stored.mime_type, file_size=stored.file_size,
                uploaded_by=current_user.id, entity_type="VehicleAccident", entity_id=accident.id,
            )
            db.add(attachment)
            db.flush()
            db.add(AccidentFile(vehicle_accident_id=accident.id, file_path=f"/api/v1/files/{attachment.id}/download"))
    record_audit(
        db, action="Accident reported", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values=snapshot(accident),
        description=f"Accident #{accident.id} reported for {vehicle.license_plate}.",
    )
    db.commit()
    return {"message": "Accident reported successfully.", "id": accident.id}


@router.get("/all", response_model=list[AccidentOut])
def all_accidents(
    request: Request,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if include_archived and current_user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Only Admin users can include archived Accidents.")
    query = db.query(VehicleAccident).options(joinedload(VehicleAccident.vehicle), joinedload(VehicleAccident.files))
    if not include_archived:
        query = query.filter(VehicleAccident.archived.is_(False))
    accidents = query.order_by(VehicleAccident.accident_date.desc()).all()
    return [
        AccidentOut(
            id=a.id,
            accident_date=format_date(a.accident_date) or "",
            location=a.location,
            description=a.description,
            license_plate=a.vehicle.license_plate,
            brand=a.vehicle.brand,
            model=a.vehicle.model,
            files=[file_url(f.file_path, request) or "" for f in a.files],
            archived=a.archived,
        )
        for a in accidents
    ]


@router.get("/{license_plate}", response_model=list[AccidentOut])
def accidents_by_plate(license_plate: str, request: Request, db: Session = Depends(get_db)):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Vehicle '{license_plate}' not found.")
    accidents = db.query(VehicleAccident).options(joinedload(VehicleAccident.files)).filter(
        VehicleAccident.vehicle_id == vehicle.id, VehicleAccident.archived.is_(False)
    ).order_by(VehicleAccident.accident_date.desc()).all()
    return [
        AccidentOut(
            id=a.id,
            accident_date=format_date(a.accident_date) or "",
            location=a.location,
            description=a.description,
            files=[file_url(f.file_path, request) or "" for f in a.files],
            archived=a.archived,
        )
        for a in accidents
    ]


@router.delete("/id/{accident_id}")
def archive_accident(
    accident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager)),
):
    accident = db.get(VehicleAccident, accident_id)
    if not accident:
        raise HTTPException(status_code=404, detail="Accident not found.")
    accident.archived = True
    accident.archived_at = datetime.utcnow()
    accident.archived_by = current_user.id
    record_audit(
        db, action="Accident archived", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values={"archived": True},
        description=f"Accident #{accident.id} archived.",
    )
    db.commit()
    return {"message": "Accident archived."}


@router.post("/id/{accident_id}/restore")
def restore_accident(
    accident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    accident = db.get(VehicleAccident, accident_id)
    if not accident:
        raise HTTPException(status_code=404, detail="Accident not found.")
    accident.archived = False
    accident.archived_at = None
    accident.archived_by = None
    record_audit(
        db, action="Accident restored", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values={"archived": False},
        description=f"Accident #{accident.id} restored.",
    )
    db.commit()
    return {"message": "Accident restored."}
