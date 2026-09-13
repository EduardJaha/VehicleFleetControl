from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.authorization import has_permission, require_permission
from app.core.security import get_current_user
from app.db.session import get_db
from app.models import Driver, Inspection, User, Vehicle, VehicleAccident, VehicleService, WorkOrder
from app.schemas import (
    LinkedInspection, LinkedService, LinkedServiceReminder, ReminderStatus, UserRole,
    WorkOrderCompletionOut, WorkOrderCompletionRequest, WorkOrderCreate, WorkOrderOut,
    WorkOrderPage, WorkOrderPriority, WorkOrderSource,
    WorkOrderStatus, WorkOrderStatusUpdate, WorkOrderUpdate,
)
from app.services.audit import record_audit, snapshot
from app.services.notifications import notify_roles
from app.services.maintenance_supply import editable_order, lock_row, recalculate_work_order_costs, require_no_active_clock
from app.models import Vendor
from app.services.work_order_completion import complete_work_order_transaction
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate, normalize_plate

router = APIRouter(dependencies=[Depends(require_permission("maintenance.view"))])


def decimal_from_text(value) -> Decimal | None:
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
    accident_id: int | None = None,
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
    if accident_id is not None:
        accident = db.get(VehicleAccident, accident_id)
        if not accident or accident.archived:
            raise HTTPException(status_code=404, detail="Accident not found.")
        if accident.vehicle_id != vehicle_id:
            raise HTTPException(status_code=400, detail="Accident and Work Order must belong to the same vehicle.")


def prevent_generic_completion(status: WorkOrderStatus) -> None:
    if status == WorkOrderStatus.completed:
        raise HTTPException(
            status_code=409,
            detail="Use POST /api/v1/work-orders/{work_order_id}/complete to complete a Work Order.",
        )


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
        accident_id=work_order.accident_id,
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
        vendor_id=work_order.vendor_id, external_vendor_cost=work_order.external_vendor_cost, tax_amount=work_order.tax_amount, discount_amount=work_order.discount_amount, other_cost=work_order.other_cost,
        costs_from_parts=bool(work_order.part_lines), costs_from_labor=bool(work_order.labor_entries),
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
    prevent_generic_completion(payload.status)
    vehicle_id = resolve_vehicle_id(db, payload.vehicle_id, payload.license_plate)
    validate_optional_links(
        db, vehicle_id, payload.driver_id, payload.inspection_id,
        payload.reminder_service_id, payload.accident_id, work_order.id,
    )
    if work_order.id:
        editable_order(db, work_order)
        if payload.archived or payload.status == WorkOrderStatus.cancelled:
            require_no_active_clock(db, work_order.id)
        if vehicle_id != work_order.vehicle_id and (work_order.part_lines or work_order.labor_entries or work_order.vendor_charges):
            raise HTTPException(status_code=409, detail="A Work Order with cost lines cannot change vehicles.")
    if payload.vendor_id is not None:
        vendor = db.query(Vendor).filter(Vendor.id == payload.vendor_id, Vendor.archived.is_(False), Vendor.is_active.is_(True)).first()
        if not vendor: raise HTTPException(status_code=404, detail="Vendor not found.")
    if "vendor_id" in payload.model_fields_set:
        work_order.vendor_id = payload.vendor_id
    labor = work_order.labor_cost if work_order.id and work_order.labor_entries else payload.labor_cost
    parts = work_order.parts_cost if work_order.id and work_order.part_lines else payload.parts_cost
    total = total_cost(labor, parts)
    work_order.vehicle_id = vehicle_id
    work_order.driver_id = payload.driver_id
    work_order.inspection_id = payload.inspection_id
    work_order.reminder_service_id = payload.reminder_service_id
    work_order.accident_id = payload.accident_id
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
    work_order.labor_cost = labor
    work_order.parts_cost = parts
    work_order.total_cost = total
    work_order.notes = payload.notes
    work_order.completed_odometer_km = payload.completed_odometer_km
    work_order.completion_notes = payload.completion_notes
    work_order.completed_by = payload.completed_by
    work_order.archived = payload.archived
    if work_order.id:
        recalculate_work_order_costs(db, work_order)


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
    current_user: User = Depends(get_current_user),
):
    query = work_order_query(db)
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page must be at least 1 and page_size must be between 1 and 100.")
    if include_archived and not has_permission(db, current_user, "maintenance.assign_work_order"):
        raise HTTPException(status_code=403, detail="maintenance.assign_work_order is required to include archived Work Orders.")
    if not include_archived:
        query = query.filter(WorkOrder.archived.is_(False))
    if search:
        text = f"%{search.strip()}%"
        query = query.filter(or_(WorkOrder.title.ilike(text), WorkOrder.description.ilike(text), WorkOrder.reported_issue.ilike(text), WorkOrder.requested_by.ilike(text), WorkOrder.assigned_to.ilike(text)))
    if license_plate:
        query = query.join(WorkOrder.vehicle).filter(Vehicle.license_plate_normalized.ilike(f"%{normalize_plate(license_plate)}%"))
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
def create_work_order(payload: WorkOrderCreate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("maintenance.create_work_order"))):
    work_order = WorkOrder()
    apply_payload(work_order, payload, db)
    work_order.created_by = current_user.full_name
    db.add(work_order)
    db.flush()
    record_audit(
        db, action="Work Order created", entity_type="WorkOrder", entity_id=work_order.id,
        user=current_user, new_values=snapshot(work_order),
        description=f"Work Order #{work_order.id} created for vehicle #{work_order.vehicle_id}.",
    )
    if work_order.priority == WorkOrderPriority.critical.value:
        notify_roles(
            db, roles={"admin", "fleet_manager", "mechanic"},
            notification_type="Critical Work Order created",
            title=f"Critical Work Order #{work_order.id}",
            message=work_order.title, priority="Critical", entity_type="WorkOrder",
            entity_id=work_order.id, deduplication_key=f"work-order:{work_order.id}:critical",
            message_params={"id": work_order.id, "title": work_order.title},
        )
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
def update_work_order(work_order_id: int, payload: WorkOrderUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("maintenance.assign_work_order"))):
    work_order = work_order_query(db).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found.")
    old_values = snapshot(work_order)
    apply_payload(work_order, payload, db)
    work_order.updated_at = datetime.utcnow()
    record_audit(
        db, action="Work Order updated", entity_type="WorkOrder", entity_id=work_order.id,
        user=current_user, old_values=old_values, new_values=snapshot(work_order),
        description=f"Work Order #{work_order.id} updated.",
    )
    db.commit()
    db.refresh(work_order)
    return work_order_out(work_order_query(db).filter(WorkOrder.id == work_order.id).one())


@router.put("/{work_order_id}/status", response_model=WorkOrderOut)
def update_work_order_status(work_order_id: int, payload: WorkOrderStatusUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("maintenance.assign_work_order"))):
    work_order = work_order_query(db).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found.")
    prevent_generic_completion(payload.status)
    editable_order(db, work_order)
    if payload.status == WorkOrderStatus.cancelled:
        require_no_active_clock(db, work_order.id)
    old_status = work_order.status
    work_order.status = payload.status.value
    if payload.actual_completion_date:
        work_order.actual_completion_date = parse_date(payload.actual_completion_date, "ActualCompletionDate")
    work_order.updated_at = datetime.utcnow()
    record_audit(
        db, action="Work Order status changed", entity_type="WorkOrder", entity_id=work_order.id,
        user=current_user, old_values={"status": old_status}, new_values={"status": work_order.status},
        description=f"Work Order #{work_order.id} changed from {old_status} to {work_order.status}.",
    )
    if payload.status in {WorkOrderStatus.assigned, WorkOrderStatus.waiting_for_parts}:
        notification_type = "Work Order assigned" if payload.status == WorkOrderStatus.assigned else "Work Order waiting for parts"
        notify_roles(
            db, roles={"admin", "fleet_manager", "mechanic"}, notification_type=notification_type,
            title=f"Work Order #{work_order.id}: {payload.status.value}",
            message=work_order.title, priority=work_order.priority, entity_type="WorkOrder",
            entity_id=work_order.id,
            deduplication_key=f"work-order:{work_order.id}:{payload.status.value.lower().replace(' ', '-')}",
            message_params={"id": work_order.id, "status": payload.status.value, "title": work_order.title},
        )
    db.commit()
    db.refresh(work_order)
    return work_order_out(work_order)


@router.delete("/{work_order_id}")
def delete_work_order(work_order_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission("maintenance.assign_work_order"))):
    work_order = lock_row(db, WorkOrder, work_order_id)
    require_no_active_clock(db, work_order.id)
    work_order.archived = True
    work_order.archived_at = datetime.utcnow()
    work_order.archived_by = current_user.id
    record_audit(
        db, action="Work Order archived", entity_type="WorkOrder", entity_id=work_order.id,
        user=current_user, new_values={"archived": True},
        description=f"Work Order #{work_order.id} archived.",
    )
    db.commit()
    return {"message": "Work Order archived."}


@router.put("/{work_order_id}/archive", response_model=WorkOrderOut)
def archive_work_order(work_order_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission("maintenance.assign_work_order"))):
    work_order = lock_row(db, WorkOrder, work_order_id)
    require_no_active_clock(db, work_order.id)
    work_order.archived = True
    work_order.archived_at = datetime.utcnow()
    work_order.archived_by = current_user.id
    work_order.updated_at = datetime.utcnow()
    record_audit(
        db, action="Work Order archived", entity_type="WorkOrder", entity_id=work_order.id,
        user=current_user, new_values={"archived": True},
        description=f"Work Order #{work_order.id} archived.",
    )
    db.commit()
    return work_order_out(work_order)


@router.post("/{work_order_id}/restore", response_model=WorkOrderOut)
def restore_work_order(
    work_order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("maintenance.assign_work_order")),
):
    work_order = work_order_query(db).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found.")
    work_order.archived = False
    work_order.archived_at = None
    work_order.archived_by = None
    work_order.updated_at = datetime.utcnow()
    record_audit(
        db, action="Work Order restored", entity_type="WorkOrder", entity_id=work_order.id,
        user=current_user, new_values={"archived": False},
        description=f"Work Order #{work_order.id} restored.",
    )
    db.commit()
    return work_order_out(work_order)


@router.post("/{work_order_id}/complete", response_model=WorkOrderCompletionOut)
def complete_work_order(
    work_order_id: int,
    payload: WorkOrderCompletionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("maintenance.complete_work_order")),
):
    try:
        work_order, service, reminder_resolved, next_reminder_created = complete_work_order_transaction(
            db, work_order_id, payload, current_user
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Work Order #{work_order_id} already has a linked Service.") from exc
    except Exception:
        db.rollback()
        raise

    refreshed = work_order_query(db).filter(WorkOrder.id == work_order_id).one()
    linked = None
    if service:
        linked = LinkedService(
            id=service.id,
            service_type=service.service_type,
            service_date=format_date(service.service_date) or "",
            total_cost=service.cost,
        )
    return WorkOrderCompletionOut(
        work_order=work_order_out(refreshed),
        service=linked,
        reminder_resolved=reminder_resolved,
        next_reminder_created=next_reminder_created,
    )
