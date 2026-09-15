from datetime import datetime
from math import ceil

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.authorization import has_permission, require_permission
from app.core.security import get_current_user
from app.db.session import get_db
from app.models import (
    Attachment,
    Driver,
    Inspection,
    InspectionItem,
    User,
    Vehicle,
    VehicleAccident,
    VehicleAssignment,
    VehicleConditionRecord,
    VehicleReservation,
    WorkOrder,
)
from app.schemas import (
    UserRole,
    VehicleAssignmentComplete,
    VehicleAssignmentCreate,
    VehicleAssignmentOut,
    VehicleAssignmentPage,
    VehicleAssignmentStart,
    VehicleAssignmentStatus,
    VehicleAssignmentUpdate,
    VehicleCheckoutCreate,
    VehicleCheckoutResult,
    VehicleConditionRecordOut,
    VehicleReturnCreate,
    VehicleReturnResult,
)
from app.services.audit import record_audit, snapshot
from app.services.inspection_templates import copy_template, resolve_template, generate_scheduled, require_checkout_inspections, required_notification
from app.services.notifications import notify_roles, resolve_by_prefix
from app.services.vehicle_assignments import (
    ACTIVE_ASSIGNMENT_STATUSES,
    assignment_out,
    assignment_query,
    condition_record_out,
    ensure_no_active_conflicts,
    parse_assignment_datetime,
    parse_assignment_filter,
    validate_assignment_parties,
)

router = APIRouter(dependencies=[Depends(require_permission("assignments.view"))])
WRITE_ROLES = (UserRole.admin, UserRole.fleet_manager)
ASSIGNED_VEHICLE_STATUS = 4
AVAILABLE_VEHICLE_STATUS = 0
RETURN_ENERGY_POLICY_THRESHOLD = 25
RETURN_INSPECTION_ITEMS = (
    "Tires",
    "Lights",
    "Brakes",
    "Windshield",
    "Mirrors",
    "Body damage",
    "Interior condition",
    "Fuel level",
    "Warning lights",
    "Documents present",
)


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


def notify_usage_event(
    db: Session,
    assignment: VehicleAssignment,
    *,
    notification_type: str,
    event_key: str,
    priority: str = "Medium",
) -> None:
    notify_roles(
        db,
        roles={"admin", "fleet_manager"},
        notification_type=notification_type,
        title=f"{assignment.vehicle.license_plate}: {notification_type}",
        message=f"{assignment.driver.full_name} · Assignment #{assignment.id}",
        priority=priority,
        entity_type="VehicleAssignment",
        entity_id=assignment.id,
        deduplication_key=f"vehicle-usage:{assignment.id}:{event_key}",
        message_params={
            "id": assignment.id,
            "plate": assignment.vehicle.license_plate,
            "driver": assignment.driver.full_name,
        },
    )


def validate_checkout_availability(
    db: Session,
    vehicle: Vehicle,
    driver: Driver,
    checkout_at: datetime,
) -> None:
    if vehicle.status != AVAILABLE_VEHICLE_STATUS:
        raise HTTPException(status_code=409, detail="This Vehicle is unavailable for check-out.")
    if driver.status != "Active":
        raise HTTPException(status_code=409, detail="Only an active Driver can check out a Vehicle.")
    if driver.license_expiry_date < checkout_at:
        raise HTTPException(status_code=409, detail="The Driver licence is expired at check-out.")
    ensure_no_active_conflicts(db, vehicle=vehicle, driver=driver)


def validate_checkout_reservation(
    db: Session,
    reservation: VehicleReservation | None,
    *,
    vehicle: Vehicle,
    checkout_at: datetime,
) -> VehicleAssignment | None:
    if reservation is None:
        return None
    if reservation.status != 1:
        raise HTTPException(status_code=409, detail="Only an approved Reservation can be checked out.")
    if reservation.vehicle_id != vehicle.id:
        raise HTTPException(status_code=409, detail="The Reservation belongs to a different Vehicle.")
    if checkout_at > reservation.end_date:
        raise HTTPException(status_code=409, detail="The Reservation has already ended.")
    linked = db.query(VehicleAssignment).filter(
        VehicleAssignment.reservation_id == reservation.id,
        VehicleAssignment.archived.is_(False),
        VehicleAssignment.status != VehicleAssignmentStatus.cancelled.value,
    ).with_for_update().all()
    scheduled = next((item for item in linked if item.status == VehicleAssignmentStatus.scheduled.value), None)
    if linked and scheduled is None:
        raise HTTPException(status_code=409, detail="This Reservation already has a Vehicle Assignment.")
    return scheduled


def create_return_inspection(
    db: Session,
    assignment: VehicleAssignment,
    payload: VehicleReturnCreate,
    current_user: User,
    ended_at: datetime,
) -> Inspection:
    inspection = Inspection(
        vehicle_id=assignment.vehicle_id,
        driver_id=assignment.driver_id,
        vehicle_assignment_id=assignment.id,
        inspection_type="Return Inspection",
        inspection_date=ended_at,
        overall_status="Needs Review",
        notes=payload.new_damage or payload.driver_comments,
        inspector=current_user.full_name,
    )
    template = resolve_template(db, assignment.vehicle, "Return Inspection", assignment.driver_id)
    if template:
        copy_template(inspection, template)
        inspection.odometer_km = assignment.vehicle.odometer_km
    else:
        inspection.items = [
            InspectionItem(
                item_name=name,
                status="Fail" if name == "Body damage" and payload.new_damage else "Not Checked",
                comment=payload.new_damage if name == "Body damage" and payload.new_damage else None,
            )
            for name in RETURN_INSPECTION_ITEMS
        ]
    db.add(inspection)
    db.flush()
    if template:
        required_notification(db, inspection)
    record_audit(
        db,
        action="Return Inspection created",
        entity_type="Inspection",
        entity_id=inspection.id,
        user=current_user,
        new_values={"vehicle_assignment_id": assignment.id, "vehicle_id": assignment.vehicle_id},
        description=f"Return Inspection #{inspection.id} created from Assignment #{assignment.id}.",
    )
    return inspection


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
    if include_archived and not has_permission(db, current_user, "assignments.manage"):
        raise HTTPException(status_code=403, detail="assignments.manage is required to include archived Vehicle Assignments.")
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
            VehicleAssignment.destination.ilike(term),
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


@router.post("/check-out", response_model=VehicleCheckoutResult, status_code=201)
def checkout_vehicle(
    payload: VehicleCheckoutCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("assignments.manage")),
):
    try:
        checkout_at = parse_assignment_datetime(payload.checkout_datetime, "checkout_datetime")
        vehicle = db.query(Vehicle).filter(Vehicle.id == payload.vehicle_id).with_for_update().one_or_none()
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found.")
        driver = db.query(Driver).filter(Driver.id == payload.driver_id).with_for_update().one_or_none()
        if not driver:
            raise HTTPException(status_code=404, detail="Driver not found.")
        _, _, reservation = validate_assignment_parties(
            db, payload.vehicle_id, payload.driver_id, payload.reservation_id
        )
        validate_checkout_availability(db, vehicle, driver, checkout_at)
        selected_assignment = None
        if payload.assignment_id is not None:
            selected_assignment = db.query(VehicleAssignment).filter(
                VehicleAssignment.id == payload.assignment_id
            ).with_for_update().one_or_none()
            if not selected_assignment:
                raise HTTPException(status_code=404, detail="Vehicle Assignment not found.")
            if selected_assignment.archived:
                raise HTTPException(
                    status_code=409,
                    detail="Restore the Vehicle Assignment before checking out the Vehicle.",
                )
            if selected_assignment.status != VehicleAssignmentStatus.scheduled.value:
                raise HTTPException(
                    status_code=409,
                    detail="Only a Scheduled Vehicle Assignment can be checked out.",
                )
            if (
                selected_assignment.vehicle_id != vehicle.id
                or selected_assignment.driver_id != driver.id
                or selected_assignment.reservation_id != payload.reservation_id
            ):
                raise HTTPException(
                    status_code=409,
                    detail="The selected Vehicle Assignment does not match the check-out details.",
                )

        reservation_assignment = validate_checkout_reservation(
            db, reservation, vehicle=vehicle, checkout_at=checkout_at
        )
        if reservation_assignment and reservation_assignment.driver_id != driver.id:
            raise HTTPException(
                status_code=409,
                detail="The scheduled Reservation Assignment belongs to a different Driver.",
            )
        if (
            selected_assignment
            and reservation_assignment
            and selected_assignment.id != reservation_assignment.id
        ):
            raise HTTPException(
                status_code=409,
                detail="The Reservation is linked to a different Scheduled Vehicle Assignment.",
            )
        if vehicle.odometer_km is not None and payload.starting_odometer_km < vehicle.odometer_km:
            raise HTTPException(
                status_code=400,
                detail=f"Start odometer cannot be lower than the Vehicle odometer of {vehicle.odometer_km:,} km.",
            )

        require_checkout_inspections(db, vehicle, driver.id, checkout_at)

        assignment = selected_assignment or reservation_assignment or VehicleAssignment(
            vehicle_id=vehicle.id,
            driver_id=driver.id,
            reservation_id=reservation.id if reservation else None,
            assigned_by_user_id=current_user.id,
            start_datetime=checkout_at,
            start_odometer_km=payload.starting_odometer_km,
            status=VehicleAssignmentStatus.active.value,
        )
        if selected_assignment is None and reservation_assignment is None:
            db.add(assignment)
        assignment.start_datetime = checkout_at
        assignment.start_odometer_km = payload.starting_odometer_km
        assignment.start_energy_level = payload.energy_level
        assignment.purpose = payload.purpose
        assignment.destination = payload.destination
        assignment.documents_handed_over = payload.documents_handed_over
        assignment.notes = payload.notes
        assignment.vehicle_status_before_checkout = vehicle.status
        assignment.status = VehicleAssignmentStatus.active.value
        assignment.updated_at = datetime.utcnow()
        db.flush()

        condition = VehicleConditionRecord(
            vehicle_assignment_id=assignment.id,
            vehicle_id=vehicle.id,
            driver_id=driver.id,
            record_type="Checkout",
            recorded_at=checkout_at,
            odometer_km=payload.starting_odometer_km,
            energy_level=payload.energy_level,
            vehicle_condition=payload.vehicle_condition,
            damage_description=payload.existing_damage,
            recorded_by_user_id=current_user.id,
        )
        db.add(condition)
        driver.assigned_vehicle_id = vehicle.id
        vehicle.odometer_km = payload.starting_odometer_km
        vehicle.status = ASSIGNED_VEHICLE_STATUS
        db.flush()

        record_audit(
            db,
            action="Vehicle checked out",
            entity_type="VehicleAssignment",
            entity_id=assignment.id,
            user=current_user,
            new_values={
                **snapshot(assignment),
                "condition_record_id": condition.id,
                "vehicle_condition": condition.vehicle_condition,
                "existing_damage": condition.damage_description,
            },
            description=f"{vehicle.license_plate} checked out to {driver.full_name}.",
        )
        notify_usage_event(
            db,
            assignment,
            notification_type="Check-out completed",
            event_key="checkout-completed",
            priority="High",
        )
        commit_or_conflict(db)
        loaded = get_assignment_or_404(db, assignment.id)
        checkout_record = next(
            record for record in loaded.condition_records if record.record_type == "Checkout"
        )
        return VehicleCheckoutResult(
            assignment=assignment_out(loaded),
            condition_record=condition_record_out(checkout_record),
        )
    except Exception:
        if db.in_transaction():
            db.rollback()
        raise


@router.get("/{assignment_id}", response_model=VehicleAssignmentOut)
def get_vehicle_assignment(assignment_id: int, db: Session = Depends(get_db)):
    return assignment_out(get_assignment_or_404(db, assignment_id))


@router.get("/{assignment_id}/conditions", response_model=list[VehicleConditionRecordOut])
def list_condition_records(assignment_id: int, db: Session = Depends(get_db)):
    assignment = get_assignment_or_404(db, assignment_id)
    return [
        condition_record_out(
            record,
            attachment_count=db.query(Attachment).filter(
                    Attachment.entity_type == "VehicleConditionRecord",
                    Attachment.entity_id == record.id,
                    Attachment.archived.is_(False),
                ).count(),
        )
        for record in assignment.condition_records
    ]


@router.post("", response_model=VehicleAssignmentOut, status_code=201)
def create_vehicle_assignment(
    payload: VehicleAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("assignments.manage")),
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
        destination=payload.destination,
        documents_handed_over=payload.documents_handed_over,
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
    current_user: User = Depends(require_permission("assignments.manage")),
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
    assignment.destination = payload.destination
    assignment.documents_handed_over = payload.documents_handed_over
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
    current_user: User = Depends(require_permission("assignments.manage")),
):
    assignment = get_assignment_or_404(db, assignment_id)
    if assignment.archived:
        raise HTTPException(status_code=409, detail="Restore the Vehicle Assignment before starting it.")
    if assignment.status != VehicleAssignmentStatus.scheduled.value:
        raise HTTPException(status_code=409, detail="Only Scheduled assignments can be started.")
    vehicle = db.query(Vehicle).filter(Vehicle.id == assignment.vehicle_id).with_for_update().one()
    driver = db.query(Driver).filter(Driver.id == assignment.driver_id).with_for_update().one()
    validate_assignment_parties(db, vehicle.id, driver.id, assignment.reservation_id)
    if vehicle.status != AVAILABLE_VEHICLE_STATUS:
        raise HTTPException(status_code=409, detail="This Vehicle is unavailable for check-out.")
    if driver.status != "Active" or driver.license_expiry_date < datetime.utcnow():
        raise HTTPException(status_code=409, detail="This Driver is unavailable for check-out.")
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
    require_checkout_inspections(db, vehicle, driver.id, started_at)
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
    assignment.vehicle_status_before_checkout = vehicle.status
    vehicle.status = ASSIGNED_VEHICLE_STATUS
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
    current_user: User = Depends(require_permission("assignments.manage")),
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
    vehicle.status = vehicle.status if vehicle.status == 3 else (
        assignment.vehicle_status_before_checkout
        if assignment.vehicle_status_before_checkout is not None
        else AVAILABLE_VEHICLE_STATUS
    )
    if driver.assigned_vehicle_id == vehicle.id:
        driver.assigned_vehicle_id = None
    if assignment.reservation and assignment.reservation.status == 1:
        assignment.reservation.status = 4
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
    generate_scheduled(db, ended_at, vehicle=vehicle, event="After return", assignment=assignment)
    notify_assignment(db, assignment, "completed")
    resolve_by_prefix(db, f"vehicle-assignment:{assignment.id}:started")
    commit_or_conflict(db)
    return assignment_out(get_assignment_or_404(db, assignment.id))


@router.post("/{assignment_id}/return", response_model=VehicleReturnResult)
def return_vehicle(
    assignment_id: int,
    payload: VehicleReturnCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("assignments.manage")),
):
    try:
        assignment = get_assignment_or_404(db, assignment_id)
        if assignment.archived:
            raise HTTPException(status_code=409, detail="Restore the Vehicle Assignment before returning it.")
        if assignment.status not in ACTIVE_ASSIGNMENT_STATUSES:
            raise HTTPException(status_code=409, detail="Only a checked-out Vehicle can be returned.")
        ended_at = parse_assignment_datetime(payload.return_datetime, "return_datetime")
        if ended_at < assignment.start_datetime:
            raise HTTPException(status_code=400, detail="Return date and time cannot be before check-out.")
        if payload.ending_odometer_km < assignment.start_odometer_km:
            raise HTTPException(status_code=400, detail="Ending odometer cannot be lower than starting odometer.")

        vehicle = db.query(Vehicle).filter(Vehicle.id == assignment.vehicle_id).with_for_update().one()
        driver = db.query(Driver).filter(Driver.id == assignment.driver_id).with_for_update().one()
        if vehicle.odometer_km is not None and payload.ending_odometer_km < vehicle.odometer_km:
            raise HTTPException(
                status_code=400,
                detail=f"Ending odometer cannot be lower than the Vehicle odometer of {vehicle.odometer_km:,} km.",
            )
        existing_return = db.query(VehicleConditionRecord).filter(
            VehicleConditionRecord.vehicle_assignment_id == assignment.id,
            VehicleConditionRecord.record_type == "Return",
        ).first()
        if existing_return:
            raise HTTPException(status_code=409, detail="This Vehicle has already been returned.")

        old_values = snapshot(assignment)
        assignment.end_datetime = ended_at
        assignment.end_odometer_km = payload.ending_odometer_km
        assignment.end_energy_level = payload.energy_level
        assignment.return_notes = payload.driver_comments
        assignment.ended_by_user_id = current_user.id
        assignment.status = VehicleAssignmentStatus.completed.value
        assignment.updated_at = datetime.utcnow()
        vehicle.odometer_km = payload.ending_odometer_km
        vehicle.status = vehicle.status if vehicle.status == 3 else (
            assignment.vehicle_status_before_checkout
            if assignment.vehicle_status_before_checkout is not None
            else AVAILABLE_VEHICLE_STATUS
        )
        if driver.assigned_vehicle_id == vehicle.id:
            driver.assigned_vehicle_id = None
        if assignment.reservation and assignment.reservation.status == 1:
            assignment.reservation.status = 4

        condition = VehicleConditionRecord(
            vehicle_assignment_id=assignment.id,
            vehicle_id=assignment.vehicle_id,
            driver_id=assignment.driver_id,
            record_type="Return",
            recorded_at=ended_at,
            odometer_km=payload.ending_odometer_km,
            energy_level=payload.energy_level,
            vehicle_condition=payload.vehicle_condition,
            damage_description=payload.new_damage,
            driver_comments=payload.driver_comments,
            return_inspection_required=payload.return_inspection_required,
            recorded_by_user_id=current_user.id,
        )
        db.add(condition)
        db.flush()

        scheduled_inspections = generate_scheduled(db, ended_at, vehicle=vehicle, event="After return", assignment=assignment)
        condition.return_inspection_required = bool(scheduled_inspections) or payload.return_inspection_required
        inspection = scheduled_inspections[0] if scheduled_inspections else (
            create_return_inspection(db, assignment, payload, current_user, ended_at)
            if payload.return_inspection_required
            else None
        )
        accident = None
        if payload.create_accident:
            accident = VehicleAccident(
                vehicle_id=assignment.vehicle_id,
                vehicle_assignment_id=assignment.id,
                accident_date=ended_at,
                location=assignment.destination or vehicle.vehicle_location,
                description=payload.new_damage,
            )
            db.add(accident)
            db.flush()
            record_audit(
                db,
                action="Accident reported from return",
                entity_type="VehicleAccident",
                entity_id=accident.id,
                user=current_user,
                new_values={"vehicle_assignment_id": assignment.id, "description": payload.new_damage},
                description=f"Accident #{accident.id} created from Assignment #{assignment.id}.",
            )

        work_order = None
        if payload.create_work_order:
            work_order = WorkOrder(
                vehicle_id=assignment.vehicle_id,
                driver_id=assignment.driver_id,
                inspection_id=inspection.id if inspection else None,
                source="Other",
                title=f"Return damage – {vehicle.license_plate}",
                description=payload.new_damage,
                reported_issue=payload.new_damage,
                priority="High",
                status="Open",
                requested_by=current_user.full_name,
                created_by=current_user.full_name,
            )
            db.add(work_order)
            db.flush()
            record_audit(
                db,
                action="Work Order created from return",
                entity_type="WorkOrder",
                entity_id=work_order.id,
                user=current_user,
                new_values={"vehicle_assignment_id": assignment.id, "reported_issue": payload.new_damage},
                description=f"Work Order #{work_order.id} created from Assignment #{assignment.id}.",
            )

        record_audit(
            db,
            action="Vehicle returned",
            entity_type="VehicleAssignment",
            entity_id=assignment.id,
            user=current_user,
            old_values=old_values,
            new_values={
                **snapshot(assignment),
                "condition_record_id": condition.id,
                "new_damage": payload.new_damage,
                "inspection_id": inspection.id if inspection else None,
                "accident_id": accident.id if accident else None,
                "work_order_id": work_order.id if work_order else None,
            },
            description=f"{vehicle.license_plate} returned by {driver.full_name}.",
        )
        notify_usage_event(
            db,
            assignment,
            notification_type="Vehicle return completed",
            event_key="return-completed",
        )
        if payload.new_damage:
            notify_usage_event(
                db,
                assignment,
                notification_type="Vehicle returned with new damage",
                event_key="returned-new-damage",
                priority="Critical",
            )
        if payload.energy_level is not None and payload.energy_level < RETURN_ENERGY_POLICY_THRESHOLD:
            notify_usage_event(
                db,
                assignment,
                notification_type="Fuel or battery below return policy",
                event_key=f"return-energy-below-{RETURN_ENERGY_POLICY_THRESHOLD}",
                priority="High",
            )
        resolve_by_prefix(db, f"vehicle-assignment:{assignment.id}:started")
        resolve_by_prefix(db, f"vehicle-assignment:{assignment.id}:overdue")
        resolve_by_prefix(db, f"vehicle-usage:{assignment.id}:return-overdue")
        if assignment.reservation_id:
            resolve_by_prefix(db, f"reservation:{assignment.reservation_id}:overdue-return")
        commit_or_conflict(db)
        loaded = get_assignment_or_404(db, assignment.id)
        return_record = next(record for record in loaded.condition_records if record.record_type == "Return")
        return VehicleReturnResult(
            assignment=assignment_out(loaded),
            condition_record=condition_record_out(return_record),
            inspection_id=inspection.id if inspection else None,
            accident_id=accident.id if accident else None,
            work_order_id=work_order.id if work_order else None,
        )
    except Exception:
        if db.in_transaction():
            db.rollback()
        raise


@router.post("/{assignment_id}/cancel", response_model=VehicleAssignmentOut)
def cancel_vehicle_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("assignments.manage")),
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
        vehicle = db.get(Vehicle, assignment.vehicle_id)
        if vehicle and vehicle.status == ASSIGNED_VEHICLE_STATUS:
            vehicle.status = (
                assignment.vehicle_status_before_checkout
                if assignment.vehicle_status_before_checkout is not None
                else AVAILABLE_VEHICLE_STATUS
            )
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
    current_user: User = Depends(require_permission("assignments.manage")),
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
    current_user: User = Depends(require_permission("assignments.manage")),
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
