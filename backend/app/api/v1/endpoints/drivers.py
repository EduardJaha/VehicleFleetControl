from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_user, require_roles
from app.core.errors import localized_http_exception
from app.db.session import get_db
from app.models import Driver, User, Vehicle, VehicleAssignment
from app.schemas import DriverCreate, DriverOut, DriverStatus, DriverUpdate, UserRole
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate
from app.services.audit import record_audit, snapshot
from app.services.vehicle_assignments import (
    ACTIVE_ASSIGNMENT_STATUSES,
    ensure_no_active_conflicts,
)

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
        archived=driver.archived,
        archived_at=driver.archived_at.isoformat() if driver.archived_at else None,
        archived_by=driver.archived_by,
    )


def resolve_vehicle_id(db: Session, assigned_vehicle_id: int | None, assigned_license_plate: str | None) -> int | None:
    if assigned_vehicle_id is not None:
        vehicle = db.get(Vehicle, assigned_vehicle_id)
        if not vehicle:
            raise localized_http_exception(404, "assigned_vehicle_not_found")
        if vehicle.archived:
            raise HTTPException(status_code=400, detail="Archived Vehicles cannot receive new assignments.")
        return vehicle.id
    if assigned_license_plate:
        vehicle = find_vehicle_by_plate(db, assigned_license_plate)
        if not vehicle:
            raise localized_http_exception(404, "assigned_vehicle_not_found")
        if vehicle.archived:
            raise HTTPException(status_code=400, detail="Archived Vehicles cannot receive new assignments.")
        return vehicle.id
    return None


def apply_driver_payload(driver: Driver, payload: DriverCreate | DriverUpdate, db: Session) -> None:
    if payload.user_id is not None and not db.get(User, payload.user_id):
        raise localized_http_exception(404, "linked_user_not_found")
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


def sync_compatibility_assignment(
    db: Session,
    *,
    driver: Driver,
    old_vehicle_id: int | None,
    new_vehicle_id: int | None,
    current_user: User,
) -> None:
    if old_vehicle_id == new_vehicle_id:
        return
    now = datetime.utcnow()
    active = db.query(VehicleAssignment).filter(
        VehicleAssignment.driver_id == driver.id,
        VehicleAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
        VehicleAssignment.archived.is_(False),
    ).with_for_update().first()
    if active:
        old_vehicle = db.get(Vehicle, active.vehicle_id)
        end_odometer = max(
            active.start_odometer_km,
            old_vehicle.odometer_km if old_vehicle and old_vehicle.odometer_km is not None else active.start_odometer_km,
        )
        active.status = "Completed"
        active.end_datetime = now
        active.end_odometer_km = end_odometer
        active.ended_by_user_id = current_user.id
        active.return_notes = "Ended from the compatible Driver current Vehicle field."
        active.updated_at = now
        record_audit(
            db,
            action="Vehicle Assignment completed",
            entity_type="VehicleAssignment",
            entity_id=active.id,
            user=current_user,
            new_values=snapshot(active),
            description=f"Assignment #{active.id} ended from the Driver profile.",
        )
    if new_vehicle_id is None:
        return
    vehicle = db.get(Vehicle, new_vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Assigned vehicle not found.")
    ensure_no_active_conflicts(db, vehicle=vehicle, driver=driver)
    assignment = VehicleAssignment(
        vehicle_id=vehicle.id,
        driver_id=driver.id,
        assigned_by_user_id=current_user.id,
        start_datetime=now,
        start_odometer_km=vehicle.odometer_km or 0,
        purpose="Driver profile assignment",
        notes="Created from the compatible Driver current Vehicle field.",
        status="Active",
    )
    db.add(assignment)
    db.flush()
    record_audit(
        db,
        action="Vehicle Assignment started",
        entity_type="VehicleAssignment",
        entity_id=assignment.id,
        user=current_user,
        new_values=snapshot(assignment),
        description=f"Assignment #{assignment.id} created from the Driver profile.",
    )


@router.get("", response_model=list[DriverOut])
def list_drivers(
    search: str | None = None,
    status: DriverStatus | None = None,
    department: str | None = None,
    assigned_vehicle_id: int | None = None,
    license_expiring_before: str | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Driver).options(joinedload(Driver.assigned_vehicle))
    if include_archived and current_user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Only Admin users can include archived Drivers.")
    if not include_archived:
        query = query.filter(Driver.archived.is_(False))
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
def create_driver(payload: DriverCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    driver = Driver()
    apply_driver_payload(driver, payload, db)
    db.add(driver)
    try:
        db.flush()
        sync_compatibility_assignment(
            db,
            driver=driver,
            old_vehicle_id=None,
            new_vehicle_id=driver.assigned_vehicle_id,
            current_user=current_user,
        )
        record_audit(
            db, action="Driver created", entity_type="Driver", entity_id=driver.id,
            user=current_user, new_values=snapshot(driver),
            description=f"Driver {driver.full_name} created.",
        )
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
def update_driver(driver_id: int, payload: DriverUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    driver = db.query(Driver).options(joinedload(Driver.assigned_vehicle)).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    old_values = snapshot(driver)
    old_assignment = driver.assigned_vehicle_id
    apply_driver_payload(driver, payload, db)
    sync_compatibility_assignment(
        db,
        driver=driver,
        old_vehicle_id=old_assignment,
        new_vehicle_id=driver.assigned_vehicle_id,
        current_user=current_user,
    )
    driver.updated_at = datetime.utcnow()
    record_audit(
        db, action="Driver updated", entity_type="Driver", entity_id=driver.id,
        user=current_user, old_values=old_values, new_values=snapshot(driver),
        description=f"Driver {driver.full_name} updated.",
    )
    if old_assignment != driver.assigned_vehicle_id:
        record_audit(
            db,
            action="Vehicle assigned to Driver" if driver.assigned_vehicle_id else "Vehicle unassigned",
            entity_type="Driver", entity_id=driver.id, user=current_user,
            old_values={"assigned_vehicle_id": old_assignment},
            new_values={"assigned_vehicle_id": driver.assigned_vehicle_id},
            description=f"Vehicle assignment changed for {driver.full_name}.",
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Driver email, employee number, license number, or linked user already exists.") from exc
    db.refresh(driver)
    return driver_out(driver)


@router.delete("/{driver_id}")
def delete_driver(driver_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    driver = db.get(Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    active_assignment = db.query(VehicleAssignment).filter(
        VehicleAssignment.driver_id == driver.id,
        VehicleAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
        VehicleAssignment.archived.is_(False),
    ).first()
    if active_assignment:
        raise HTTPException(status_code=409, detail="Complete or cancel the active Vehicle Assignment before archiving this Driver.")
    driver.archived = True
    driver.archived_at = datetime.utcnow()
    driver.archived_by = current_user.id
    record_audit(
        db, action="Driver archived", entity_type="Driver", entity_id=driver.id,
        user=current_user, new_values={"archived": True},
        description=f"Driver {driver.full_name} archived.",
    )
    db.commit()
    return {"message": "Driver archived."}


@router.post("/{driver_id}/restore", response_model=DriverOut)
def restore_driver(
    driver_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    driver = db.query(Driver).options(joinedload(Driver.assigned_vehicle)).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    driver.archived = False
    driver.archived_at = None
    driver.archived_by = None
    driver.updated_at = datetime.utcnow()
    record_audit(
        db, action="Driver restored", entity_type="Driver", entity_id=driver.id,
        user=current_user, new_values={"archived": False},
        description=f"Driver {driver.full_name} restored.",
    )
    db.commit()
    return driver_out(driver)
