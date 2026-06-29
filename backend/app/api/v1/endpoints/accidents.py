from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session, joinedload
from app.db.session import get_db
from app.models import AccidentFile, VehicleAccident
from app.schemas import AccidentOut
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate
from app.utils.files import file_url, save_upload

router = APIRouter()


@router.post("/report")
async def report_accident(
    license_plate: str = Form(...),
    accident_date: str = Form(...),
    location: str = Form(...),
    description: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Vehicle '{license_plate}' not found.")
    accident = VehicleAccident(vehicle_id=vehicle.id, accident_date=parse_date(accident_date, "AccidentDate"), location=location, description=description)
    db.add(accident)
    db.commit()
    db.refresh(accident)
    for uploaded in files or []:
        if uploaded.filename:
            path = await save_upload(uploaded, "accidents")
            db.add(AccidentFile(vehicle_accident_id=accident.id, file_path=path))
    db.commit()
    return {"message": "Accident reported successfully.", "id": accident.id}


@router.get("/all", response_model=list[AccidentOut])
def all_accidents(request: Request, db: Session = Depends(get_db)):
    accidents = db.query(VehicleAccident).options(joinedload(VehicleAccident.vehicle), joinedload(VehicleAccident.files)).order_by(VehicleAccident.accident_date.desc()).all()
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
        )
        for a in accidents
    ]


@router.get("/{license_plate}", response_model=list[AccidentOut])
def accidents_by_plate(license_plate: str, request: Request, db: Session = Depends(get_db)):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Vehicle '{license_plate}' not found.")
    accidents = db.query(VehicleAccident).options(joinedload(VehicleAccident.files)).filter(VehicleAccident.vehicle_id == vehicle.id).order_by(VehicleAccident.accident_date.desc()).all()
    return [
        AccidentOut(
            id=a.id,
            accident_date=format_date(a.accident_date) or "",
            location=a.location,
            description=a.description,
            files=[file_url(f.file_path, request) or "" for f in a.files],
        )
        for a in accidents
    ]
