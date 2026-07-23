from datetime import datetime
from math import ceil

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import Driver, User, Vehicle, VehicleAssignment
from app.schemas import (
    UserRole,
    VehicleAssignmentComplete,
    VehicleAssignmentCreate,
    VehicleAssignmentOut,
    VehicleAssignmentPage,
    VehicleAssignmentStart,
    VehicleAssignmentStatus,
    VehicleAssignmentUpdate,
)
from app.services.audit import record_audit, snapshot
from app.services.notifications import notify_roles, resolve_by_prefix
from app.services.vehicle_assignments import (
    ACTIVE_ASSIGNMENT_STATUSES,
    assignment_out,
    assignment_query,
    ensure_no_active_conflicts,
    parse_assignment_datetime,
    parse_assignment_filter,
    validate_assignment_parties,
)

router = APIRouter(dependencies=[Depends(get_current_user)])
WRITE_ROLES = (UserRole.admin, UserRole.fleet_manager)


def get_assignment_or_404(db: Session, assignment_id: int) -> VehicleAssignment:
    assignment = assignment_query(db).filter(VehicleAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Vehicle Assignment not found.")
    return assignment


def commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The Vehicle or Driver already has an active assignment.",
        ) from exc


def notify_assignment(db: Session, assignment: VehicleAssignment, event: str, priority: str = "Medium") -> None:
    notify_roles(
        db,
        roles={"admin", "fleet_manager"},
        notification_type=f"Vehicle assignment {event}",
        title=f"Assignment #{assignment.id} {event}",
        message=f"{assignment.vehicle.license_plate} · {assignment.driver.full_name}",
        priority=priority,
        entity_type="VehicleAssignment",
        entity_id=assignment.id,
        deduplication_key=f"vehicle-assignment:{assignment.id}:{event}",
        message_params={
            "id": assignment.id,
            "plate": assignment.vehicle.license_plate,
            "driver": assignment.driver.full_name,
        },
    )


@router.get("", response_model=VehicleAssignmentPage)
def list_vehicle_assignments(
    vehicle_id: int | None = None,
    driver_id: int | None = None,
    search: str | None = None,
    status: VehicleAssignmentStatus | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    active_only: bool = False,
    include_archived: bool = False,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page must be at least 1 and page_size must be between 1 and 100.")
    if include_archived and current_user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Only Admin users can include archived Vehicle Assignments.")
    query = assignment_query(db)
    if not include_archived:
        query = query.filter(VehicleAssignment.archived.is_(False))
    if vehicle_id is not None:
        query = query.filter(VehicleAssignment.vehicle_id == vehicle_id)
    if driver_id is not None:
        query = query.filter(VehicleAssignment.driver_id == driver_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.join(VehicleAssignment.vehicle).join(VehicleAssignment.driver).filter(or_(
            Vehicle.license_plate.ilike(term),
            Vehicle.brand.ilike(term),
            Vehicle.model.ilike(term),
            Driver.full_name.ilike(term),
            VehicleAssignment.purpose.ilike(term),
            VehicleAssignment.notes.ilike(term),
            VehicleAssignment.return_notes.ilike(term),
        ))
    if status is not None:
        query = query.filter(VehicleAssignment.status == status.value)
    if active_only:
        query = query.filter(
            VehicleAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
            VehicleAssignment.end_datetime.is_(None),
        )
    if from_date:
        query = query.filter(VehicleAssignment.start_datetime >= parse_assignment_filter(from_date, "from_date"))
    if to_date:
        query = query.filter(VehicleAssignment.start_datetime <= parse_assignment_filter(to_date, "to_date", end_of_day=True))
    total = query.count()
    rows = query.order_by(VehicleAssignment.start_datetime.desc(), VehicleAssignment.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return VehicleAssignmentPage(
        items=[assignment_out(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
        pages=ceil(total / page_size) if total else 0,
    )


@router.get("/{assignment_id}", response_model=VehicleAssignmentOut)
def get_vehicle_assignment(assignment_id: int, db: Session = Depends(get_db)):
    return assignment_out(get_assignment_or_404(db, assignment_id))


@router.post("", response_model=VehicleAssignmentOut, status_code=201)
def create_vehicle_assignment(
    payload: VehicleAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*WRITE_ROLES)),
):
    vehicle, driver, _ = validate_assignment_parties(
        db, payload.vehicle_id, payload.driver_id, payload.reservation_id
    )
    start_datetime = parse_assignment_datetime(payload.start_datetime, "start_datetime")
    assignment = VehicleAssignment(
        vehicle_id=vehicle.id,
        driver_id=driver.id,
        reservation_id=payload.reservation_id,
        assigned_by_user_id=current_user.id,
        start_datetime=start_datetime,
        start_odometer_km=payload.start_odometer_km,
        start_energy_level=payload.start_energy_level,
        purpose=payload.purpose,
        notes=payload.notes,
        status=VehicleAssignmentStatus.scheduled.value,
    )
    db.add(assignment)
    db.flush()
    record_audit(
        db,
        action="Vehicle Assignment created",
        entity_type="VehicleAssignment",
        entity_id=assignment.id,
        user=current_user,
        new_values=snapshot(assignment),
        description=f"Assignment #{assignment.id} scheduled for {vehicle.license_plate} and {driver.full_name}.",
    )
    notify_assignment(db, assignment, "scheduled")
    commit_or_conflict(db)
    db.refresh(assignment)
    return assignment_out(get_assignment_or_404(db, assignment.id))


@router.put("/{assignment_id}", response_model=VehicleAssignmentOut)
def update_vehicle_assignment(
    assignment_id: int,
    payload: VehicleAssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*WRITE_ROLES)),
):
    assignment = get_assignment_or_404(db, assignment_id)
    if assignment.archived:
        raise HTTPException(status_code=409, detail="Restore the Vehicle Assignment before editing it.")
    if assignment.status != VehicleAssignmentStatus.scheduled.value:
        raise HTTPException(status_code=409, detail="Only Scheduled assignments can be edited.")
    validate_assignment_parties(db, payload.vehicle_id, payload.driver_id, payload.reservation_id)
    old_values = snapshot(assignment)
    assignment.vehicle_id = payload.vehicle_id
    assignment.driver_id = payload.driver_id
    assignment.reservation_id = payload.reservation_id
    assignment.start_datetime = parse_assignment_datetime(payload.start_datetime, "start_datetime")
    assignment.start_odometer_km = payload.start_odometer_km
    assignment.start_energy_level = payload.start_energy_level
    assignment.purpose = payload.purpose
    assignment.notes = payload.notes
    assignment.updated_at = datetime.utcnow()
    record_audit(
        db,
        action="Vehicle Assignment updated",
        entity_type="VehicleAssignment",
        entity_id=assignment.id,
        user=current_user,
        old_values=old_values,
        new_values=snapshot(assignment),
        description=f"Assignment #{assignment.id} updated.",
    )
    commit_or_conflict(db)
    return assignment_out(get_assignment_or_404(db, assignment.id))


@router.post("/{assignment_id}/start", response_model=VehicleAssignmentOut)
def start_vehicle_assignment(
    assignment_id: int,
    payload: VehicleAssignmentStart | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*WRITE_ROLES)),
):
    assignment = get_assignment_or_404(db, assignment_id)
    if assignment.archived:
        raise HTTPException(status_code=409, detail="Restore the Vehicle Assignment before starting it.")
    if assignment.status != VehicleAssignmentStatus.scheduled.value:
        raise HTTPException(status_code=409, detail="Only Scheduled assignments can be started.")
    vehicle = db.query(Vehicle).filter(Vehicle.id == assignment.vehicle_id).with_for_update().one()
    driver = db.query(Driver).filter(Driver.id == assignment.driver_id).with_for_update().one()
    validate_assignment_parties(db, vehicle.id, driver.id, assignment.reservation_id)
    ensure_no_active_conflicts(
        db, vehicle=vehicle, driver=driver, exclude_assignment_id=assignment.id
    )
    request = payload or VehicleAssignmentStart()
    started_at = (
        parse_assignment_datetime(request.start_datetime, "start_datetime")
        if request.start_datetime
        else datetime.utcnow()
    )
    odometer = request.start_odometer_km if request.start_odometer_km is not None else assignment.start_odometer_km
    if vehicle.odometer_km is not None and odometer < vehicle.odometer_km:
        raise HTTPException(
            status_code=400,
            detail=f"Start odometer cannot be lower than the Vehicle odometer of {vehicle.odometer_km:,} km.",
        )
    old_values = snapshot(assignment)
    assignment.start_datetime = started_at
    assignment.start_odometer_km = odometer
    if request.start_energy_level is not None:
        assignment.start_energy_level = request.start_energy_level
    if request.notes:
        assignment.notes = request.notes
    assignment.status = VehicleAssignmentStatus.active.value
    assignment.updated_at = datetime.utcnow()
    driver.assigned_vehicle_id = vehicle.id
    vehicle.odometer_km = odometer
    record_audit(
        db,
        action="Vehicle Assignment started",
        entity_type="VehicleAssignment",
        entity_id=assignment.id,
        user=current_user,
        old_values=old_values,
        new_values=snapshot(assignment),
        description=f"Assignment #{assignment.id} started for {vehicle.license_plate} and {driver.full_name}.",
    )
    notify_assignment(db, assignment, "started", "High")
    commit_or_conflict(db)
    return assignment_out(get_assignment_or_404(db, assignment.id))


@router.post("/{assignment_id}/complete", response_model=VehicleAssignmentOut)
def complete_vehicle_assignment(
    assignment_id: int,
    payload: VehicleAssignmentComplete,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*WRITE_ROLES)),
):
    assignment = get_assignment_or_404(db, assignment_id)
    if assignment.archived:
        raise HTTPException(status_code=409, detail="Restore the Vehicle Assignment before completing it.")
    if assignment.status not in ACTIVE_ASSIGNMENT_STATUSES:
        raise HTTPException(status_code=409, detail="Only an active Vehicle Assignment can be completed.")
    ended_at = parse_assignment_datetime(payload.end_datetime, "end_datetime")
    if ended_at < assignment.start_datetime:
        raise HTTPException(status_code=400, detail="End date and time cannot be before the assignment start.")
    if payload.end_odometer_km < assignment.start_odometer_km:
        raise HTTPException(status_code=400, detail="End odometer cannot be lower than the start odometer.")
    vehicle = db.query(Vehicle).filter(Vehicle.id == assignment.vehicle_id).with_for_update().one()
    driver = db.query(Driver).filter(Driver.id == assignment.driver_id).with_for_update().one()
    if vehicle.odometer_km is not None and payload.end_odometer_km < vehicle.odometer_km:
        raise HTTPException(
            status_code=400,
            detail=f"End odometer cannot be lower than the Vehicle odometer of {vehicle.odometer_km:,} km.",
        )
    old_values = snapshot(assignment)
    assignment.end_datetime = ended_at
    assignment.end_odometer_km = payload.end_odometer_km
    assignment.end_energy_level = payload.end_energy_level
    assignment.return_notes = payload.return_notes
    assignment.ended_by_user_id = current_user.id
    assignment.status = VehicleAssignmentStatus.completed.value
    assignment.updated_at = datetime.utcnow()
    vehicle.odometer_km = payload.end_odometer_km
    if driver.assigned_vehicle_id == vehicle.id:
        driver.assigned_vehicle_id = None
    record_audit(
        db,
        action="Vehicle Assignment completed",
        entity_type="VehicleAssignment",
        entity_id=assignment.id,
        user=current_user,
        old_values=old_values,
        new_values=snapshot(assignment),
        description=f"Assignment #{assignment.id} completed.",
    )
    notify_assignment(db, assignment, "completed")
    resolve_by_prefix(db, f"vehicle-assignment:{assignment.id}:started")
    commit_or_conflict(db)
    return assignment_out(get_assignment_or_404(db, assignment.id))


@router.post("/{assignment_id}/cancel", response_model=VehicleAssignmentOut)
def cancel_vehicle_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*WRITE_ROLES)),
):
    assignment = get_assignment_or_404(db, assignment_id)
    if assignment.archived:
        raise HTTPException(status_code=409, detail="Restore the Vehicle Assignment before cancelling it.")
    if assignment.status not in {
        VehicleAssignmentStatus.scheduled.value,
        VehicleAssignmentStatus.active.value,
        VehicleAssignmentStatus.overdue.value,
    }:
        raise HTTPException(status_code=409, detail="This Vehicle Assignment cannot be cancelled.")
    was_active = assignment.status in ACTIVE_ASSIGNMENT_STATUSES
    old_values = snapshot(assignment)
    if was_active:
        assignment.end_datetime = datetime.utcnow()
        assignment.ended_by_user_id = current_user.id
        driver = db.get(Driver, assignment.driver_id)
        if driver and driver.assigned_vehicle_id == assignment.vehicle_id:
            driver.assigned_vehicle_id = None
    assignment.status = VehicleAssignmentStatus.cancelled.value
    assignment.updated_at = datetime.utcnow()
    record_audit(
        db,
        action="Vehicle Assignment cancelled",
        entity_type="VehicleAssignment",
        entity_id=assignment.id,
        user=current_user,
        old_values=old_values,
        new_values=snapshot(assignment),
        description=f"Assignment #{assignment.id} cancelled.",
    )
    notify_assignment(db, assignment, "cancelled")
    resolve_by_prefix(db, f"vehicle-assignment:{assignment.id}:started")
    commit_or_conflict(db)
    return assignment_out(get_assignment_or_404(db, assignment.id))


@router.delete("/{assignment_id}")
def archive_vehicle_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*WRITE_ROLES)),
):
    assignment = get_assignment_or_404(db, assignment_id)
    if assignment.status in ACTIVE_ASSIGNMENT_STATUSES:
        raise HTTPException(status_code=409, detail="Complete or cancel an active assignment before archiving it.")
    assignment.archived = True
    assignment.archived_at = datetime.utcnow()
    assignment.archived_by = current_user.id
    assignment.updated_at = datetime.utcnow()
    record_audit(
        db,
        action="Vehicle Assignment archived",
        entity_type="VehicleAssignment",
        entity_id=assignment.id,
        user=current_user,
        new_values={"archived": True},
        description=f"Assignment #{assignment.id} archived.",
    )
    db.commit()
    return {"message": "Vehicle Assignment archived."}


@router.post("/{assignment_id}/restore", response_model=VehicleAssignmentOut)
def restore_vehicle_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    assignment = get_assignment_or_404(db, assignment_id)
    assignment.archived = False
    assignment.archived_at = None
    assignment.archived_by = None
    assignment.updated_at = datetime.utcnow()
    record_audit(
        db,
        action="Vehicle Assignment restored",
        entity_type="VehicleAssignment",
        entity_id=assignment.id,
        user=current_user,
        new_values={"archived": False},
        description=f"Assignment #{assignment.id} restored.",
    )
    commit_or_conflict(db)
    return assignment_out(get_assignment_or_404(db, assignment.id))
