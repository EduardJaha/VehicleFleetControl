from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session, joinedload
from app.db.session import get_db
from app.models import VehiclePaper
from app.schemas import VehiclePaperListOut
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate
from app.utils.files import delete_upload, file_url, save_upload

router = APIRouter()


@router.post("/upload")
async def upload_paper(
    license_plate: str = Form(...),
    document_type: str = Form(...),
    issue_date: str = Form(...),
    expiry_date: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"No vehicle found with license plate '{license_plate}'.")
    existing = db.query(VehiclePaper).filter(VehiclePaper.vehicle_id == vehicle.id, VehiclePaper.document_type.ilike(document_type)).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"A document of type '{document_type}' is already registered for vehicle '{vehicle.license_plate}'.")
    issue = parse_date(issue_date, "IssueDate")
    expiry = parse_date(expiry_date, "ExpiryDate")
    if expiry <= issue:
        raise HTTPException(status_code=400, detail="Expiry date must be after issue date.")
    file_path = await save_upload(file)
    paper = VehiclePaper(vehicle_id=vehicle.id, document_type=document_type, file_path=file_path, issue_date=issue, expiry_date=expiry)
    db.add(paper)
    db.commit()
    db.refresh(paper)
    return {"message": f"'{document_type}' document uploaded successfully for vehicle {vehicle.license_plate}.", "id": paper.id}


@router.get("/all", response_model=list[VehiclePaperListOut])
def all_papers(request: Request, db: Session = Depends(get_db)):
    papers = db.query(VehiclePaper).options(joinedload(VehiclePaper.vehicle)).order_by(VehiclePaper.expiry_date.asc()).all()
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
        )
        for p in papers
    ]


@router.delete("/{paper_id}")
def delete_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = db.get(VehiclePaper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Document not found.")
    delete_upload(paper.file_path)
    db.delete(paper)
    db.commit()
    return {"message": "Document deleted successfully."}
