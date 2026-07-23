from datetime import datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models import Driver, Vehicle, VehicleAssignment, VehicleReservation
from app.schemas import VehicleAssignmentOut, VehicleAssignmentStatus

ACTIVE_ASSIGNMENT_STATUSES = ("Active", "Overdue")
HISTORICALLY_ACTIVE_STATUSES = ("Active", "Overdue", "Completed", "Cancelled")


def parse_assignment_datetime(value: str | None, field_name: str) -> datetime:
    if not value or not value.strip():
        raise HTTPException(status_code=400, detail=f"{field_name} is required.")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%d-%m-%Y")
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"{field_name} must be an ISO date/time or dd-MM-yyyy.",
            ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def parse_assignment_filter(value: str, field_name: str, *, end_of_day: bool = False) -> datetime:
    parsed = parse_assignment_datetime(value, field_name)
    if end_of_day and "T" not in value and " " not in value:
        return datetime.combine(parsed.date(), time.max)
    return parsed


def assignment_query(db: Session):
    return db.query(VehicleAssignment).options(
        joinedload(VehicleAssignment.vehicle),
        joinedload(VehicleAssignment.driver),
        joinedload(VehicleAssignment.assigned_by_user),
        joinedload(VehicleAssignment.ended_by_user),
    )


def assignment_out(assignment: VehicleAssignment) -> VehicleAssignmentOut:
    return VehicleAssignmentOut(
        id=assignment.id,
        vehicle_id=assignment.vehicle_id,
        driver_id=assignment.driver_id,
        reservation_id=assignment.reservation_id,
        vehicle_license_plate=assignment.vehicle.license_plate,
        vehicle_name=f"{assignment.vehicle.brand} {assignment.vehicle.model}",
        driver_name=assignment.driver.full_name,
        assigned_by_user_id=assignment.assigned_by_user_id,
        assigned_by_name=assignment.assigned_by_user.full_name if assignment.assigned_by_user else None,
        ended_by_user_id=assignment.ended_by_user_id,
        ended_by_name=assignment.ended_by_user.full_name if assignment.ended_by_user else None,
        start_datetime=assignment.start_datetime.isoformat(),
        end_datetime=assignment.end_datetime.isoformat() if assignment.end_datetime else None,
        start_odometer_km=assignment.start_odometer_km,
        end_odometer_km=assignment.end_odometer_km,
        start_energy_level=assignment.start_energy_level,
        end_energy_level=assignment.end_energy_level,
        purpose=assignment.purpose,
        notes=assignment.notes,
        return_notes=assignment.return_notes,
        status=VehicleAssignmentStatus(assignment.status),
        created_at=assignment.created_at.isoformat(),
        updated_at=assignment.updated_at.isoformat(),
        archived=assignment.archived,
        archived_at=assignment.archived_at.isoformat() if assignment.archived_at else None,
        archived_by=assignment.archived_by,
    )


def validate_assignment_parties(
    db: Session,
    vehicle_id: int,
    driver_id: int,
    reservation_id: int | None,
) -> tuple[Vehicle, Driver, VehicleReservation | None]:
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    driver = db.get(Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    if vehicle.archived:
        raise HTTPException(status_code=400, detail="Archived Vehicles cannot receive new assignments.")
    if driver.archived:
        raise HTTPException(status_code=400, detail="Archived Drivers cannot receive new assignments.")
    reservation = db.get(VehicleReservation, reservation_id) if reservation_id is not None else None
    if reservation_id is not None and not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")
    if reservation:
        if reservation.archived:
            raise HTTPException(status_code=400, detail="An archived Reservation cannot be linked.")
        if reservation.vehicle_id != vehicle.id:
            raise HTTPException(status_code=400, detail="The Reservation belongs to a different Vehicle.")
        if reservation.status in {2, 3}:
            raise HTTPException(status_code=400, detail="Rejected or cancelled Reservations cannot be linked.")
    return vehicle, driver, reservation


def ensure_no_active_conflicts(
    db: Session,
    *,
    vehicle: Vehicle,
    driver: Driver,
    exclude_assignment_id: int | None = None,
) -> None:
    query = db.query(VehicleAssignment).filter(
        VehicleAssignment.archived.is_(False),
        VehicleAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
        or_(
            VehicleAssignment.vehicle_id == vehicle.id,
            VehicleAssignment.driver_id == driver.id,
        ),
    )
    if exclude_assignment_id is not None:
        query = query.filter(VehicleAssignment.id != exclude_assignment_id)
    conflict = query.with_for_update().first()
    if conflict:
        if conflict.vehicle_id == vehicle.id:
            raise HTTPException(status_code=409, detail="This Vehicle already has an active assignment.")
        raise HTTPException(status_code=409, detail="This Driver already has an active assignment.")

    legacy_vehicle_driver = db.query(Driver).filter(
        Driver.assigned_vehicle_id == vehicle.id,
        Driver.id != driver.id,
        Driver.archived.is_(False),
    ).with_for_update().first()
    if legacy_vehicle_driver:
        raise HTTPException(
            status_code=409,
            detail="This Vehicle is already assigned through the current Driver relationship.",
        )
    if driver.assigned_vehicle_id is not None and driver.assigned_vehicle_id != vehicle.id:
        raise HTTPException(
            status_code=409,
            detail="This Driver is already assigned through the current Vehicle relationship.",
        )


def active_assignment_at(
    db: Session,
    *,
    vehicle_id: int,
    occurred_at: datetime,
    driver_id: int | None = None,
) -> VehicleAssignment | None:
    range_end = (
        occurred_at + timedelta(days=1) - timedelta(microseconds=1)
        if occurred_at.time() == time.min
        else occurred_at
    )
    query = db.query(VehicleAssignment).filter(
        VehicleAssignment.vehicle_id == vehicle_id,
        VehicleAssignment.status.in_(HISTORICALLY_ACTIVE_STATUSES),
        VehicleAssignment.start_datetime <= range_end,
        or_(
            VehicleAssignment.end_datetime.is_(None),
            VehicleAssignment.end_datetime >= occurred_at,
        ),
        or_(
            VehicleAssignment.status != "Cancelled",
            VehicleAssignment.end_datetime.is_not(None),
        ),
    )
    if driver_id is not None:
        query = query.filter(VehicleAssignment.driver_id == driver_id)
    return query.order_by(VehicleAssignment.start_datetime.desc(), VehicleAssignment.id.desc()).first()
