from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import Driver, Inspection, InspectionItem, User, Vehicle
from app.schemas import (
    InspectionCreate,
    InspectionItemCreate,
    InspectionItemStatus,
    InspectionOverallStatus,
    InspectionOut,
    InspectionType,
    InspectionUpdate,
    UserRole,
)
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate, normalize_plate

router = APIRouter(dependencies=[Depends(get_current_user)])

DEFAULT_CHECKLIST_ITEMS = [
    "Tires",
    "Lights",
    "Brakes",
    "Oil level",
    "Coolant level",
    "Windshield",
    "Mirrors",
    "Body damage",
    "Interior condition",
    "Fuel level",
    "Warning lights",
    "Documents present",
    "Spare tire/tools",
]


def inspection_out(inspection: Inspection) -> InspectionOut:
    return InspectionOut(
        id=inspection.id,
        vehicle_id=inspection.vehicle_id,
        license_plate=inspection.vehicle.license_plate,
        driver_id=inspection.driver_id,
        driver_name=inspection.driver.full_name if inspection.driver else None,
        inspection_type=InspectionType(inspection.inspection_type),
        inspection_date=format_date(inspection.inspection_date) or "",
        overall_status=InspectionOverallStatus(inspection.overall_status),
        notes=inspection.notes,
        items=[
            {
                "id": item.id,
                "item_name": item.item_name,
                "status": InspectionItemStatus(item.status),
                "comment": item.comment,
            }
            for item in inspection.items
        ],
        created_at=inspection.created_at.isoformat(),
        updated_at=inspection.updated_at.isoformat(),
    )


def resolve_vehicle_id(db: Session, vehicle_id: int | None, license_plate: str | None) -> int:
    if vehicle_id is not None:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found.")
        return vehicle.id
    if license_plate:
        vehicle = find_vehicle_by_plate(db, license_plate)
        if not vehicle:
            raise HTTPException(status_code=404, detail=f"Vehicle '{license_plate}' not found.")
        return vehicle.id
    raise HTTPException(status_code=400, detail="vehicle_id or license_plate is required.")


def validate_driver(db: Session, driver_id: int | None) -> int | None:
    if driver_id is None:
        return None
    if not db.get(Driver, driver_id):
        raise HTTPException(status_code=404, detail="Driver not found.")
    return driver_id


def checklist_items(items: list[InspectionItemCreate]) -> list[InspectionItemCreate]:
    if items:
        return items
    return [InspectionItemCreate(item_name=name, status=InspectionItemStatus.not_checked) for name in DEFAULT_CHECKLIST_ITEMS]


def derive_overall_status(items: list[InspectionItemCreate], requested: InspectionOverallStatus | None) -> InspectionOverallStatus:
    statuses = [item.status for item in items]
    has_fail = any(status == InspectionItemStatus.fail for status in statuses)
    has_not_checked = any(status == InspectionItemStatus.not_checked for status in statuses)
    if has_fail:
        if requested in {InspectionOverallStatus.failed, InspectionOverallStatus.needs_review}:
            return requested
        return InspectionOverallStatus.failed
    if requested:
        return requested
    if has_not_checked:
        return InspectionOverallStatus.needs_review
    return InspectionOverallStatus.passed


def replace_items(inspection: Inspection, items: list[InspectionItemCreate]) -> None:
    inspection.items = [
        InspectionItem(item_name=item.item_name.strip(), status=item.status.value, comment=item.comment)
        for item in items
    ]


def apply_payload(inspection: Inspection, payload: InspectionCreate | InspectionUpdate, db: Session) -> None:
    items = checklist_items(payload.items)
    inspection.vehicle_id = resolve_vehicle_id(db, payload.vehicle_id, payload.license_plate)
    inspection.driver_id = validate_driver(db, payload.driver_id)
    inspection.inspection_type = payload.inspection_type.value
    inspection.inspection_date = parse_date(payload.inspection_date, "InspectionDate")
    inspection.overall_status = derive_overall_status(items, payload.overall_status).value
    inspection.notes = payload.notes
    replace_items(inspection, items)


def inspection_query(db: Session):
    return db.query(Inspection).options(
        joinedload(Inspection.vehicle),
        joinedload(Inspection.driver),
        joinedload(Inspection.items),
    )


@router.get("", response_model=list[InspectionOut])
def list_inspections(
    license_plate: str | None = None,
    driver_id: int | None = None,
    inspection_type: InspectionType | None = None,
    overall_status: InspectionOverallStatus | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
):
    query = inspection_query(db)
    if license_plate:
        query = query.join(Inspection.vehicle).filter(Vehicle.license_plate.ilike(f"%{normalize_plate(license_plate)}%"))
    if driver_id is not None:
        query = query.filter(Inspection.driver_id == driver_id)
    if inspection_type:
        query = query.filter(Inspection.inspection_type == inspection_type.value)
    if overall_status:
        query = query.filter(Inspection.overall_status == overall_status.value)
    if from_date:
        query = query.filter(Inspection.inspection_date >= parse_date(from_date, "from_date"))
    if to_date:
        query = query.filter(Inspection.inspection_date <= parse_date(to_date, "to_date"))
    rows = query.order_by(Inspection.inspection_date.desc(), Inspection.id.desc()).all()
    return [inspection_out(row) for row in rows]


@router.post("", response_model=InspectionOut, status_code=201)
def create_inspection(payload: InspectionCreate, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.mechanic))):
    inspection = Inspection()
    apply_payload(inspection, payload, db)
    db.add(inspection)
    db.commit()
    db.refresh(inspection)
    return inspection_out(inspection_query(db).filter(Inspection.id == inspection.id).one())


@router.get("/by-vehicle/{license_plate}", response_model=list[InspectionOut])
def inspections_by_vehicle(license_plate: str, db: Session = Depends(get_db)):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Vehicle '{license_plate}' not found.")
    rows = inspection_query(db).filter(Inspection.vehicle_id == vehicle.id).order_by(Inspection.inspection_date.desc(), Inspection.id.desc()).all()
    return [inspection_out(row) for row in rows]


@router.get("/{inspection_id}", response_model=InspectionOut)
def get_inspection(inspection_id: int, db: Session = Depends(get_db)):
    inspection = inspection_query(db).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found.")
    return inspection_out(inspection)


@router.put("/{inspection_id}", response_model=InspectionOut)
def update_inspection(inspection_id: int, payload: InspectionUpdate, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.mechanic))):
    inspection = inspection_query(db).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found.")
    apply_payload(inspection, payload, db)
    inspection.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(inspection)
    return inspection_out(inspection_query(db).filter(Inspection.id == inspection.id).one())


@router.delete("/{inspection_id}")
def delete_inspection(inspection_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.mechanic))):
    inspection = db.get(Inspection, inspection_id)
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found.")
    db.delete(inspection)
    db.commit()
    return {"message": "Inspection deleted."}
