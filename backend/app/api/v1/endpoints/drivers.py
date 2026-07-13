from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import Driver, User, Vehicle
from app.schemas import DriverCreate, DriverOut, DriverStatus, DriverUpdate, UserRole
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate

router = APIRouter(dependencies=[Depends(get_current_user)])


def driver_out(driver: Driver) -> DriverOut:
    return DriverOut(
        id=driver.id,
        full_name=driver.full_name,
        phone_number=driver.phone_number,
        email=driver.email,
        employee_number=driver.employee_number,
        department=driver.department,
        license_number=driver.license_number,
        license_category=driver.license_category,
        license_expiry_date=format_date(driver.license_expiry_date) or "",
        assigned_vehicle_id=driver.assigned_vehicle_id,
        assigned_license_plate=driver.assigned_vehicle.license_plate if driver.assigned_vehicle else None,
        user_id=driver.user_id,
        status=DriverStatus(driver.status),
        notes=driver.notes,
        created_at=driver.created_at.isoformat(),
        updated_at=driver.updated_at.isoformat(),
    )


def resolve_vehicle_id(db: Session, assigned_vehicle_id: int | None, assigned_license_plate: str | None) -> int | None:
    if assigned_vehicle_id is not None:
        vehicle = db.get(Vehicle, assigned_vehicle_id)
        if not vehicle:
            raise HTTPException(status_code=404, detail="Assigned vehicle not found.")
        return vehicle.id
    if assigned_license_plate:
        vehicle = find_vehicle_by_plate(db, assigned_license_plate)
        if not vehicle:
            raise HTTPException(status_code=404, detail=f"Assigned vehicle '{assigned_license_plate}' not found.")
        return vehicle.id
    return None


def apply_driver_payload(driver: Driver, payload: DriverCreate | DriverUpdate, db: Session) -> None:
    if payload.user_id is not None and not db.get(User, payload.user_id):
        raise HTTPException(status_code=404, detail="Linked user not found.")
    driver.full_name = payload.full_name.strip()
    driver.phone_number = payload.phone_number
    driver.email = payload.email
    driver.employee_number = payload.employee_number.strip()
    driver.department = payload.department
    driver.license_number = payload.license_number.strip()
    driver.license_category = payload.license_category.strip()
    driver.license_expiry_date = parse_date(payload.license_expiry_date, "LicenseExpiryDate")
    driver.assigned_vehicle_id = resolve_vehicle_id(db, payload.assigned_vehicle_id, payload.assigned_license_plate)
    driver.user_id = payload.user_id
    driver.status = payload.status.value
    driver.notes = payload.notes


@router.get("", response_model=list[DriverOut])
def list_drivers(
    search: str | None = None,
    status: DriverStatus | None = None,
    department: str | None = None,
    assigned_vehicle_id: int | None = None,
    license_expiring_before: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Driver).options(joinedload(Driver.assigned_vehicle))
    if search:
        text = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Driver.full_name.ilike(text),
                Driver.phone_number.ilike(text),
                Driver.email.ilike(text),
                Driver.employee_number.ilike(text),
                Driver.department.ilike(text),
                Driver.license_number.ilike(text),
            )
        )
    if status:
        query = query.filter(Driver.status == status.value)
    if department:
        query = query.filter(Driver.department.ilike(f"%{department.strip()}%"))
    if assigned_vehicle_id is not None:
        query = query.filter(Driver.assigned_vehicle_id == assigned_vehicle_id)
    if license_expiring_before:
        query = query.filter(Driver.license_expiry_date <= parse_date(license_expiring_before, "license_expiring_before"))
    return [driver_out(driver) for driver in query.order_by(Driver.id.desc()).all()]


@router.post("", response_model=DriverOut, status_code=201)
def create_driver(payload: DriverCreate, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    driver = Driver()
    apply_driver_payload(driver, payload, db)
    db.add(driver)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Driver email, employee number, license number, or linked user already exists.") from exc
    db.refresh(driver)
    return driver_out(driver)


@router.get("/{driver_id}", response_model=DriverOut)
def get_driver(driver_id: int, db: Session = Depends(get_db)):
    driver = db.query(Driver).options(joinedload(Driver.assigned_vehicle)).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    return driver_out(driver)


@router.put("/{driver_id}", response_model=DriverOut)
def update_driver(driver_id: int, payload: DriverUpdate, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    driver = db.query(Driver).options(joinedload(Driver.assigned_vehicle)).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    apply_driver_payload(driver, payload, db)
    driver.updated_at = datetime.utcnow()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Driver email, employee number, license number, or linked user already exists.") from exc
    db.refresh(driver)
    return driver_out(driver)


@router.delete("/{driver_id}")
def delete_driver(driver_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    driver = db.get(Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    db.delete(driver)
    db.commit()
    return {"message": "Driver deleted."}
