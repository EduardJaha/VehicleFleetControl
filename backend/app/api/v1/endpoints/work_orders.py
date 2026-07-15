from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import Driver, Inspection, User, Vehicle, VehicleService, WorkOrder
from app.schemas import (
    LinkedInspection, LinkedService, LinkedServiceReminder, ReminderStatus, UserRole,
    WorkOrderCreate, WorkOrderOut, WorkOrderPage, WorkOrderPriority, WorkOrderSource,
    WorkOrderStatus, WorkOrderStatusUpdate, WorkOrderUpdate,
)
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate, normalize_plate

router = APIRouter(dependencies=[Depends(get_current_user)])


def decimal_from_text(value: str | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None and value != "" else None


def optional_date(value: str | None, field_name: str):
    return parse_date(value, field_name) if value else None


def total_cost(labor_cost: Decimal | None, parts_cost: Decimal | None) -> Decimal | None:
    if labor_cost is None and parts_cost is None:
        return None
    return (labor_cost or Decimal("0")) + (parts_cost or Decimal("0"))


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


def validate_optional_links(
    db: Session,
    vehicle_id: int,
    driver_id: int | None,
    inspection_id: int | None,
    reminder_service_id: int | None,
    current_work_order_id: int | None = None,
) -> None:
    if driver_id is not None and not db.get(Driver, driver_id):
        raise HTTPException(status_code=404, detail="Driver not found.")
    if inspection_id is not None:
        inspection = db.get(Inspection, inspection_id)
        if not inspection:
            raise HTTPException(status_code=404, detail="Inspection not found.")
        if inspection.vehicle_id != vehicle_id:
            raise HTTPException(status_code=400, detail="Inspection and Work Order must belong to the same vehicle.")
        duplicate = db.query(WorkOrder).filter(
            WorkOrder.inspection_id == inspection_id,
            WorkOrder.archived.is_(False),
            WorkOrder.status.notin_([WorkOrderStatus.completed.value, WorkOrderStatus.cancelled.value]),
        )
        if current_work_order_id is not None:
            duplicate = duplicate.filter(WorkOrder.id != current_work_order_id)
        if duplicate.first():
            raise HTTPException(status_code=409, detail="An open Work Order already exists for this Inspection.")
    if reminder_service_id is not None:
        reminder = db.get(VehicleService, reminder_service_id)
        if not reminder:
            raise HTTPException(status_code=404, detail="Service Reminder not found.")
        if reminder.vehicle_id != vehicle_id:
            raise HTTPException(status_code=400, detail="Service Reminder and Work Order must belong to the same vehicle.")
        duplicate = db.query(WorkOrder).filter(
            WorkOrder.reminder_service_id == reminder_service_id,
            WorkOrder.archived.is_(False),
            WorkOrder.status.notin_([WorkOrderStatus.completed.value, WorkOrderStatus.cancelled.value]),
        )
        if current_work_order_id is not None:
            duplicate = duplicate.filter(WorkOrder.id != current_work_order_id)
        if duplicate.first():
            raise HTTPException(status_code=409, detail="An open Work Order already exists for this Service Reminder.")


def validate_completed(status: WorkOrderStatus, actual_completion_date: str | None) -> None:
    if status == WorkOrderStatus.completed and not actual_completion_date:
        raise HTTPException(status_code=400, detail="Completed work orders require actual_completion_date.")


def work_order_query(db: Session):
    return db.query(WorkOrder).options(
        joinedload(WorkOrder.vehicle),
        joinedload(WorkOrder.driver),
        joinedload(WorkOrder.inspection),
        joinedload(WorkOrder.reminder_service).joinedload(VehicleService.vehicle),
        joinedload(WorkOrder.linked_service),
    )


def reminder_status(service: VehicleService) -> ReminderStatus:
    if service.reminder_status in {ReminderStatus.resolved.value, ReminderStatus.dismissed.value}:
        return ReminderStatus(service.reminder_status)
    today = datetime.today().date()
    if service.next_service_date:
        days = (service.next_service_date.date() - today).days
        if days < 0:
            return ReminderStatus.overdue
        if days == 0:
            return ReminderStatus.due
        if days <= 30:
            return ReminderStatus.due_soon
    if service.next_service_odometer_km is not None and service.vehicle:
        km_left = service.next_service_odometer_km - (service.vehicle.odometer_km or 0)
        if km_left < 0:
            return ReminderStatus.overdue
        if km_left == 0:
            return ReminderStatus.due
        if km_left <= 1000:
            return ReminderStatus.due_soon
    return ReminderStatus.upcoming


def work_order_out(work_order: WorkOrder) -> WorkOrderOut:
    return WorkOrderOut(
        id=work_order.id,
        vehicle_id=work_order.vehicle_id,
        license_plate=work_order.vehicle.license_plate,
        vehicle_name=f"{work_order.vehicle.brand} {work_order.vehicle.model}",
        driver_id=work_order.driver_id,
        driver_name=work_order.driver.full_name if work_order.driver else None,
        inspection_id=work_order.inspection_id,
        reminder_service_id=work_order.reminder_service_id,
        source=WorkOrderSource(work_order.source or WorkOrderSource.manual.value),
        title=work_order.title,
        description=work_order.description,
        reported_issue=work_order.reported_issue,
        priority=WorkOrderPriority(work_order.priority),
        status=WorkOrderStatus(work_order.status),
        requested_by=work_order.requested_by,
        assigned_to=work_order.assigned_to,
        workshop=work_order.workshop,
        expected_completion_date=format_date(work_order.expected_completion_date),
        actual_completion_date=format_date(work_order.actual_completion_date),
        labor_cost=decimal_from_text(work_order.labor_cost),
        parts_cost=decimal_from_text(work_order.parts_cost),
        total_cost=decimal_from_text(work_order.total_cost),
        notes=work_order.notes,
        completed_odometer_km=work_order.completed_odometer_km,
        completion_notes=work_order.completion_notes,
        completed_by=work_order.completed_by,
        archived=work_order.archived,
        created_by=work_order.created_by,
        source_inspection=LinkedInspection(
            id=work_order.inspection.id,
            inspection_type=work_order.inspection.inspection_type,
            inspection_date=format_date(work_order.inspection.inspection_date) or "",
            overall_status=work_order.inspection.overall_status,
        ) if work_order.inspection else None,
        source_reminder=LinkedServiceReminder(
            id=work_order.reminder_service.id,
            service_type=work_order.reminder_service.service_type,
            due_date=format_date(work_order.reminder_service.next_service_date),
            due_odometer_km=work_order.reminder_service.next_service_odometer_km,
            status=reminder_status(work_order.reminder_service),
        ) if work_order.reminder_service else None,
        linked_service=LinkedService(
            id=work_order.linked_service.id,
            service_type=work_order.linked_service.service_type,
            service_date=format_date(work_order.linked_service.service_date) or "",
            total_cost=decimal_from_text(work_order.linked_service.cost),
        ) if work_order.linked_service else None,
        created_at=work_order.created_at.isoformat(),
        updated_at=work_order.updated_at.isoformat(),
    )


def apply_payload(work_order: WorkOrder, payload: WorkOrderCreate | WorkOrderUpdate, db: Session) -> None:
    validate_completed(payload.status, payload.actual_completion_date)
    vehicle_id = resolve_vehicle_id(db, payload.vehicle_id, payload.license_plate)
    validate_optional_links(db, vehicle_id, payload.driver_id, payload.inspection_id, payload.reminder_service_id, work_order.id)
    labor = payload.labor_cost
    parts = payload.parts_cost
    total = total_cost(labor, parts)
    work_order.vehicle_id = vehicle_id
    work_order.driver_id = payload.driver_id
    work_order.inspection_id = payload.inspection_id
    work_order.reminder_service_id = payload.reminder_service_id
    work_order.source = payload.source.value
    work_order.title = payload.title.strip()
    work_order.description = payload.description
    work_order.reported_issue = payload.reported_issue
    work_order.priority = payload.priority.value
    work_order.status = payload.status.value
    work_order.requested_by = payload.requested_by
    work_order.assigned_to = payload.assigned_to
    work_order.workshop = payload.workshop
    work_order.expected_completion_date = optional_date(payload.expected_completion_date, "ExpectedCompletionDate")
    work_order.actual_completion_date = optional_date(payload.actual_completion_date, "ActualCompletionDate")
    work_order.labor_cost = str(labor) if labor is not None else None
    work_order.parts_cost = str(parts) if parts is not None else None
    work_order.total_cost = str(total) if total is not None else None
    work_order.notes = payload.notes
    work_order.completed_odometer_km = payload.completed_odometer_km
    work_order.completion_notes = payload.completion_notes
    work_order.completed_by = payload.completed_by
    work_order.archived = payload.archived


@router.get("", response_model=WorkOrderPage)
def list_work_orders(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    vehicle_id: int | None = None,
    license_plate: str | None = None,
    status: WorkOrderStatus | None = None,
    priority: WorkOrderPriority | None = None,
    source: WorkOrderSource | None = None,
    assigned_to: str | None = None,
    workshop: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    overdue_only: bool = False,
    has_linked_service: bool | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
):
    query = work_order_query(db)
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page must be at least 1 and page_size must be between 1 and 100.")
    if not include_archived:
        query = query.filter(WorkOrder.archived.is_(False))
    if search:
        text = f"%{search.strip()}%"
        query = query.filter(or_(WorkOrder.title.ilike(text), WorkOrder.description.ilike(text), WorkOrder.reported_issue.ilike(text), WorkOrder.requested_by.ilike(text), WorkOrder.assigned_to.ilike(text)))
    if license_plate:
        query = query.join(WorkOrder.vehicle).filter(Vehicle.license_plate.ilike(f"%{normalize_plate(license_plate)}%"))
    if vehicle_id is not None:
        query = query.filter(WorkOrder.vehicle_id == vehicle_id)
    if status:
        query = query.filter(WorkOrder.status == status.value)
    if priority:
        query = query.filter(WorkOrder.priority == priority.value)
    if source:
        query = query.filter(WorkOrder.source == source.value)
    if assigned_to:
        query = query.filter(WorkOrder.assigned_to.ilike(f"%{assigned_to.strip()}%"))
    if workshop:
        query = query.filter(WorkOrder.workshop.ilike(f"%{workshop.strip()}%"))
    if from_date:
        query = query.filter(WorkOrder.expected_completion_date >= parse_date(from_date, "from_date"))
    if to_date:
        query = query.filter(WorkOrder.expected_completion_date <= parse_date(to_date, "to_date"))
    if overdue_only:
        query = query.filter(
            WorkOrder.expected_completion_date < datetime.now(),
            WorkOrder.status.notin_([WorkOrderStatus.completed.value, WorkOrderStatus.cancelled.value]),
        )
    if has_linked_service is True:
        query = query.filter(WorkOrder.linked_service.has())
    elif has_linked_service is False:
        query = query.filter(~WorkOrder.linked_service.has())
    total = query.order_by(None).count()
    rows = query.order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return WorkOrderPage(items=[work_order_out(row) for row in rows], page=page, page_size=page_size, total=total, pages=(total + page_size - 1) // page_size)


@router.post("", response_model=WorkOrderOut, status_code=201)
def create_work_order(payload: WorkOrderCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager, UserRole.mechanic))):
    work_order = WorkOrder()
    apply_payload(work_order, payload, db)
    work_order.created_by = current_user.full_name
    db.add(work_order)
    db.commit()
    db.refresh(work_order)
    return work_order_out(work_order_query(db).filter(WorkOrder.id == work_order.id).one())


@router.get("/{work_order_id}", response_model=WorkOrderOut)
def get_work_order(work_order_id: int, db: Session = Depends(get_db)):
    work_order = work_order_query(db).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found.")
    return work_order_out(work_order)


@router.put("/{work_order_id}", response_model=WorkOrderOut)
def update_work_order(work_order_id: int, payload: WorkOrderUpdate, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager, UserRole.mechanic))):
    work_order = work_order_query(db).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found.")
    apply_payload(work_order, payload, db)
    work_order.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(work_order)
    return work_order_out(work_order_query(db).filter(WorkOrder.id == work_order.id).one())


@router.put("/{work_order_id}/status", response_model=WorkOrderOut)
def update_work_order_status(work_order_id: int, payload: WorkOrderStatusUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager, UserRole.mechanic))):
    work_order = work_order_query(db).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found.")
    validate_completed(payload.status, payload.actual_completion_date or format_date(work_order.actual_completion_date))
    work_order.status = payload.status.value
    if payload.actual_completion_date:
        work_order.actual_completion_date = parse_date(payload.actual_completion_date, "ActualCompletionDate")
    if payload.status == WorkOrderStatus.completed:
        work_order.completed_by = work_order.completed_by or current_user.full_name
    work_order.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(work_order)
    return work_order_out(work_order)


@router.delete("/{work_order_id}")
def delete_work_order(work_order_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager, UserRole.mechanic))):
    work_order = db.get(WorkOrder, work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found.")
    db.delete(work_order)
    db.commit()
    return {"message": "Work order deleted."}


@router.put("/{work_order_id}/archive", response_model=WorkOrderOut)
def archive_work_order(work_order_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    work_order = work_order_query(db).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found.")
    work_order.archived = True
    work_order.updated_at = datetime.utcnow()
    db.commit()
    return work_order_out(work_order)
