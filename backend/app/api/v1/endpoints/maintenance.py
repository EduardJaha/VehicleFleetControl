from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Numeric, case, cast, func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import Inspection, User, Vehicle, VehicleService, WorkOrder
from app.schemas import (
    LinkedService,
    LinkedServiceReminder,
    MaintenanceRecordSummary,
    MaintenanceSummaryOut,
    MaintenanceTimelineEvent,
    MaintenanceTimelinePage,
    ReminderStatus,
    UserRole,
    VehicleMaintenanceSummaryOut,
    WorkOrderStatus,
)
from app.utils.dates import format_date
from app.api.v1.endpoints.services import current_reminder_status, reminder_status_expression

router = APIRouter(dependencies=[Depends(get_current_user)])

SUMMARY_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.mechanic, UserRole.finance, UserRole.viewer)
ACTIVE_WORK_ORDER_STATUSES = ["Open", "Assigned", "In Progress", "Waiting for Parts"]


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = datetime(now.year, now.month, 1)
    end = datetime(now.year + (now.month == 12), 1 if now.month == 12 else now.month + 1, 1)
    return start, end


def decimal_value(value) -> Decimal:
    return Decimal(str(value or 0))


def work_order_summary(order: WorkOrder) -> MaintenanceRecordSummary:
    return MaintenanceRecordSummary(
        id=order.id,
        record_type="Work Order",
        vehicle_id=order.vehicle_id,
        vehicle=f"{order.vehicle.brand} {order.vehicle.model}",
        license_plate=order.vehicle.license_plate,
        title=order.title,
        description=order.reported_issue or order.description,
        status=order.status,
        priority=order.priority,
        date=order.created_at.isoformat(),
        due_date=format_date(order.expected_completion_date),
        assigned_to=order.assigned_to,
        cost=decimal_value(order.total_cost) if order.total_cost not in (None, "") else None,
        href=f"/work-orders/{order.id}",
    )


def service_summary(service: VehicleService) -> MaintenanceRecordSummary:
    return MaintenanceRecordSummary(
        id=service.id,
        record_type="Service",
        vehicle_id=service.vehicle_id,
        vehicle=f"{service.vehicle.brand} {service.vehicle.model}",
        license_plate=service.vehicle.license_plate,
        title=service.service_type,
        description=service.description,
        status=service.status or "Completed",
        date=service.service_date.isoformat(),
        assigned_to=service.workshop,
        cost=decimal_value(service.cost) if service.cost not in (None, "") else None,
        href=f"/services/{service.id}",
    )


def inspection_summary(inspection: Inspection) -> MaintenanceRecordSummary:
    failed = sum(1 for item in inspection.items if item.status == "Fail")
    return MaintenanceRecordSummary(
        id=inspection.id,
        record_type="Inspection",
        vehicle_id=inspection.vehicle_id,
        vehicle=f"{inspection.vehicle.brand} {inspection.vehicle.model}",
        license_plate=inspection.vehicle.license_plate,
        title=f"{inspection.inspection_type} Inspection",
        description=f"{failed} failed checklist item(s)." if failed else inspection.notes,
        status=inspection.overall_status,
        date=inspection.inspection_date.isoformat(),
        assigned_to=inspection.inspector or (inspection.driver.full_name if inspection.driver else None),
        href=f"/inspections/{inspection.id}",
    )


def reminder_summary(service: VehicleService) -> MaintenanceRecordSummary:
    status = current_reminder_status(service)
    priority = "Critical" if status == ReminderStatus.overdue else "High" if status == ReminderStatus.due else "Medium" if status == ReminderStatus.due_soon else "Low"
    return MaintenanceRecordSummary(
        id=service.id,
        record_type="Service Reminder",
        vehicle_id=service.vehicle_id,
        vehicle=f"{service.vehicle.brand} {service.vehicle.model}",
        license_plate=service.vehicle.license_plate,
        title=service.service_type,
        description=(f"Due at {service.next_service_odometer_km:,} km" if service.next_service_odometer_km else None),
        status=status.value,
        priority=priority,
        date=service.service_date.isoformat(),
        due_date=format_date(service.next_service_date),
        href=f"/services/reminders?reminder_id={service.id}",
    )


def latest_reminders_query(db: Session):
    ranked = db.query(
        VehicleService.id.label("service_id"),
        func.row_number().over(
            partition_by=(VehicleService.vehicle_id, VehicleService.service_type),
            order_by=(VehicleService.service_date.desc(), VehicleService.id.desc()),
        ).label("row_number"),
    ).filter(
        VehicleService.archived.is_(False),
        or_(VehicleService.next_service_date.isnot(None), VehicleService.next_service_odometer_km.isnot(None)),
    ).subquery()
    return db.query(VehicleService).join(ranked, VehicleService.id == ranked.c.service_id).filter(ranked.c.row_number == 1).join(VehicleService.vehicle)


def actual_maintenance_cost(db: Session, start: datetime | None = None, end: datetime | None = None, vehicle_id: int | None = None) -> Decimal:
    """Actual cost = Services + completed Work Orders that have no linked Service.

    A linked Work Order and Service describe the same maintenance activity, so the
    Work Order estimate is deliberately excluded once an actual Service exists.
    """
    service_query = db.query(func.coalesce(func.sum(cast(VehicleService.cost, Numeric(14, 2))), 0)).filter(VehicleService.archived.is_(False))
    order_query = db.query(func.coalesce(func.sum(cast(WorkOrder.total_cost, Numeric(14, 2))), 0)).filter(
        WorkOrder.archived.is_(False),
        WorkOrder.status == WorkOrderStatus.completed.value,
        ~WorkOrder.linked_service.has(),
    )
    if start is not None:
        service_query = service_query.filter(VehicleService.service_date >= start)
        order_query = order_query.filter(WorkOrder.actual_completion_date >= start)
    if end is not None:
        service_query = service_query.filter(VehicleService.service_date < end)
        order_query = order_query.filter(WorkOrder.actual_completion_date < end)
    if vehicle_id is not None:
        service_query = service_query.filter(VehicleService.vehicle_id == vehicle_id)
        order_query = order_query.filter(WorkOrder.vehicle_id == vehicle_id)
    return decimal_value(service_query.scalar()) + decimal_value(order_query.scalar())


@router.get("/summary", response_model=MaintenanceSummaryOut)
def maintenance_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*SUMMARY_ROLES)),
):
    now = datetime.now()
    month_start, month_end = month_bounds(now)

    status_counts = dict(db.query(WorkOrder.status, func.count(WorkOrder.id)).filter(WorkOrder.archived.is_(False)).group_by(WorkOrder.status).all())
    priority_counts = dict(db.query(WorkOrder.priority, func.count(WorkOrder.id)).filter(WorkOrder.archived.is_(False)).group_by(WorkOrder.priority).all())

    order_base = db.query(WorkOrder).options(joinedload(WorkOrder.vehicle)).filter(WorkOrder.archived.is_(False))
    overdue_filter = (
        WorkOrder.expected_completion_date < now,
        WorkOrder.status.in_(ACTIVE_WORK_ORDER_STATUSES),
    )
    critical_orders = order_base.filter(WorkOrder.priority == "Critical", WorkOrder.status.in_(ACTIVE_WORK_ORDER_STATUSES)).order_by(WorkOrder.created_at.desc()).limit(8).all()
    overdue_orders = order_base.filter(*overdue_filter).order_by(WorkOrder.expected_completion_date).limit(8).all()

    inspection_base = db.query(Inspection).options(joinedload(Inspection.vehicle), joinedload(Inspection.driver), joinedload(Inspection.items)).filter(Inspection.archived.is_(False))
    failed_inspection_rows = inspection_base.filter(Inspection.overall_status == "Failed").order_by(Inspection.inspection_date.desc()).limit(8).all()

    reminder_query = latest_reminders_query(db).options(joinedload(VehicleService.vehicle))
    status_expr = reminder_status_expression(datetime.combine(now.date(), datetime.min.time()))
    reminder_counts = dict(reminder_query.with_entities(status_expr, func.count(VehicleService.id)).group_by(status_expr).all())
    overdue_reminder_rows = reminder_query.filter(status_expr == ReminderStatus.overdue.value).order_by(VehicleService.next_service_date, VehicleService.id).limit(8).all()

    in_service_vehicles = db.query(Vehicle).filter(Vehicle.status == 1).order_by(Vehicle.license_plate).limit(8).all()
    in_service_items = [MaintenanceRecordSummary(
        id=vehicle.id, record_type="Vehicle", vehicle_id=vehicle.id,
        vehicle=f"{vehicle.brand} {vehicle.model}", license_plate=vehicle.license_plate,
        title="Vehicle currently in service", status="In Service", href=f"/vehicles/{vehicle.id}",
    ) for vehicle in in_service_vehicles]

    recent_created = order_base.order_by(WorkOrder.created_at.desc()).limit(8).all()
    recent_completed = order_base.filter(WorkOrder.status == "Completed").order_by(WorkOrder.actual_completion_date.desc()).limit(8).all()
    recent_services = db.query(VehicleService).options(joinedload(VehicleService.vehicle)).filter(VehicleService.archived.is_(False)).order_by(VehicleService.service_date.desc()).limit(8).all()
    recent_inspections = inspection_base.order_by(Inspection.inspection_date.desc()).limit(8).all()

    return MaintenanceSummaryOut(
        work_orders_by_status={status: int(status_counts.get(status, 0)) for status in ["Open", "Assigned", "In Progress", "Waiting for Parts", "Completed", "Cancelled"]},
        work_orders_by_priority={priority: int(priority_counts.get(priority, 0)) for priority in ["Low", "Medium", "High", "Critical"]},
        open_work_orders=int(status_counts.get("Open", 0)),
        assigned_work_orders=int(status_counts.get("Assigned", 0)),
        in_progress_work_orders=int(status_counts.get("In Progress", 0)),
        waiting_for_parts_work_orders=int(status_counts.get("Waiting for Parts", 0)),
        critical_work_orders_count=order_base.filter(WorkOrder.priority == "Critical", WorkOrder.status.in_(ACTIVE_WORK_ORDER_STATUSES)).count(),
        overdue_work_orders_count=order_base.filter(*overdue_filter).count(),
        completed_work_orders_this_month=order_base.filter(WorkOrder.status == "Completed", WorkOrder.actual_completion_date >= month_start, WorkOrder.actual_completion_date < month_end).count(),
        services_completed_this_month=db.query(func.count(VehicleService.id)).filter(VehicleService.archived.is_(False), VehicleService.service_date >= month_start, VehicleService.service_date < month_end).scalar() or 0,
        upcoming_reminders_count=sum(int(reminder_counts.get(status.value, 0)) for status in [ReminderStatus.upcoming, ReminderStatus.due_soon, ReminderStatus.due]),
        overdue_reminders_count=int(reminder_counts.get(ReminderStatus.overdue.value, 0)),
        failed_inspections_count=inspection_base.filter(Inspection.overall_status == "Failed").count(),
        inspections_needing_review_count=inspection_base.filter(Inspection.overall_status == "Needs Review").count(),
        vehicles_in_service_count=db.query(func.count(Vehicle.id)).filter(Vehicle.status == 1).scalar() or 0,
        monthly_maintenance_cost=actual_maintenance_cost(db, month_start, month_end),
        critical_work_orders=[work_order_summary(row) for row in critical_orders],
        overdue_work_orders=[work_order_summary(row) for row in overdue_orders],
        overdue_service_reminders=[reminder_summary(row) for row in overdue_reminder_rows],
        failed_inspections=[inspection_summary(row) for row in failed_inspection_rows],
        vehicles_in_service=in_service_items,
        recently_created_work_orders=[work_order_summary(row) for row in recent_created],
        recently_completed_work_orders=[work_order_summary(row) for row in recent_completed],
        recent_services=[service_summary(row) for row in recent_services],
        recent_inspections=[inspection_summary(row) for row in recent_inspections],
    )


def vehicle_summary(db: Session, vehicle_id: int) -> VehicleMaintenanceSummaryOut:
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    now = datetime.now()
    month_start, month_end = month_bounds(now)
    year_start = datetime(now.year, 1, 1)
    year_end = datetime(now.year + 1, 1, 1)
    orders = db.query(WorkOrder).filter(WorkOrder.vehicle_id == vehicle_id, WorkOrder.archived.is_(False))
    last_service = db.query(VehicleService).filter(VehicleService.vehicle_id == vehicle_id, VehicleService.archived.is_(False)).order_by(VehicleService.service_date.desc(), VehicleService.id.desc()).first()
    reminders = latest_reminders_query(db).filter(VehicleService.vehicle_id == vehicle_id).options(joinedload(VehicleService.vehicle)).all()
    active_reminders = [service for service in reminders if current_reminder_status(service) not in {ReminderStatus.resolved, ReminderStatus.dismissed}]
    active_reminders.sort(key=lambda service: (
        service.next_service_date or datetime.max,
        (service.next_service_odometer_km or 2_000_000) - (vehicle.odometer_km or 0),
    ))
    next_reminder = active_reminders[0] if active_reminders else None
    next_status = current_reminder_status(next_reminder) if next_reminder else None
    return VehicleMaintenanceSummaryOut(
        vehicle_id=vehicle.id,
        license_plate=vehicle.license_plate,
        open_work_orders=orders.filter(WorkOrder.status.in_(ACTIVE_WORK_ORDER_STATUSES)).count(),
        critical_work_orders=orders.filter(WorkOrder.status.in_(ACTIVE_WORK_ORDER_STATUSES), WorkOrder.priority == "Critical").count(),
        last_service=LinkedService(
            id=last_service.id, service_type=last_service.service_type,
            service_date=format_date(last_service.service_date) or "", total_cost=decimal_value(last_service.cost),
        ) if last_service else None,
        next_service=LinkedServiceReminder(
            id=next_reminder.id, service_type=next_reminder.service_type,
            due_date=format_date(next_reminder.next_service_date), due_odometer_km=next_reminder.next_service_odometer_km,
            status=next_status,
        ) if next_reminder and next_status else None,
        overdue_reminders=sum(1 for service in reminders if current_reminder_status(service) == ReminderStatus.overdue),
        failed_inspections=db.query(func.count(Inspection.id)).filter(Inspection.vehicle_id == vehicle_id, Inspection.archived.is_(False), Inspection.overall_status == "Failed").scalar() or 0,
        maintenance_cost_this_month=actual_maintenance_cost(db, month_start, month_end, vehicle_id),
        maintenance_cost_this_year=actual_maintenance_cost(db, year_start, year_end, vehicle_id),
        lifetime_maintenance_cost=actual_maintenance_cost(db, vehicle_id=vehicle_id),
    )


def vehicle_timeline(db: Session, vehicle_id: int, page: int, page_size: int) -> MaintenanceTimelinePage:
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page must be at least 1 and page_size must be between 1 and 100.")
    if not db.get(Vehicle, vehicle_id):
        raise HTTPException(status_code=404, detail="Vehicle not found.")

    events: list[MaintenanceTimelineEvent] = []
    inspections = db.query(Inspection).options(joinedload(Inspection.items), joinedload(Inspection.driver)).filter(Inspection.vehicle_id == vehicle_id, Inspection.archived.is_(False)).all()
    for inspection in inspections:
        failed = sum(1 for item in inspection.items if item.status == "Fail")
        actor = inspection.inspector or (inspection.driver.full_name if inspection.driver else None)
        events.append(MaintenanceTimelineEvent(
            id=f"inspection-created-{inspection.id}", occurred_at=inspection.created_at.isoformat(), event_type="Inspection created",
            title=f"{inspection.inspection_type} inspection created", description=inspection.notes, status=inspection.overall_status,
            actor=actor, related_record_type="Inspection", related_record_id=inspection.id, href=f"/inspections/{inspection.id}",
        ))
        events.append(MaintenanceTimelineEvent(
            id=f"inspection-status-{inspection.id}", occurred_at=inspection.updated_at.isoformat(),
            event_type=f"Inspection {inspection.overall_status.lower()}", title=f"Inspection {inspection.overall_status}",
            description=f"{failed} checklist item(s) failed." if failed else "No failed checklist items.", status=inspection.overall_status,
            actor=actor, related_record_type="Inspection", related_record_id=inspection.id, href=f"/inspections/{inspection.id}",
        ))

    orders = db.query(WorkOrder).filter(WorkOrder.vehicle_id == vehicle_id, WorkOrder.archived.is_(False)).all()
    status_events = {"Assigned": "Work Order assigned", "In Progress": "Work Order started", "Waiting for Parts": "Work Order waiting for parts", "Completed": "Work Order completed", "Cancelled": "Work Order cancelled"}
    for order in orders:
        events.append(MaintenanceTimelineEvent(
            id=f"work-order-created-{order.id}", occurred_at=order.created_at.isoformat(), event_type="Work Order created",
            title=order.title, description=order.reported_issue or order.description, status=order.status, priority=order.priority,
            actor=order.created_by or order.requested_by, related_record_type="Work Order", related_record_id=order.id, href=f"/work-orders/{order.id}",
        ))
        if order.status in status_events:
            description = order.completion_notes
            if order.status == "Completed" and order.total_cost:
                description = f"Final maintenance cost: {decimal_value(order.total_cost):.2f}." + (f" {description}" if description else "")
            events.append(MaintenanceTimelineEvent(
                id=f"work-order-status-{order.id}", occurred_at=(order.actual_completion_date or order.updated_at).isoformat(),
                event_type=status_events[order.status], title=order.title, description=description,
                status=order.status, priority=order.priority, actor=order.completed_by or order.assigned_to,
                related_record_type="Work Order", related_record_id=order.id, href=f"/work-orders/{order.id}",
            ))

    services = db.query(VehicleService).filter(VehicleService.vehicle_id == vehicle_id, VehicleService.archived.is_(False)).all()
    for service in services:
        created_at = service.created_at or service.service_date
        events.append(MaintenanceTimelineEvent(
            id=f"service-created-{service.id}", occurred_at=created_at.isoformat(), event_type="Service created",
            title=f"{service.service_type} service", description=(f"Completed at {service.odometer_km:,} km." if service.odometer_km else service.description),
            status=service.status, actor=service.workshop, related_record_type="Service", related_record_id=service.id, href=f"/services/{service.id}",
        ))
        if service.updated_at and abs((service.updated_at - created_at).total_seconds()) > 1:
            events.append(MaintenanceTimelineEvent(
                id=f"service-updated-{service.id}", occurred_at=service.updated_at.isoformat(), event_type="Service updated",
                title=f"{service.service_type} service updated", description=service.description,
                status=service.status, actor=service.workshop, related_record_type="Service", related_record_id=service.id,
                href=f"/services/{service.id}",
            ))
        if service.next_service_date or service.next_service_odometer_km:
            status = current_reminder_status(service)
            events.append(MaintenanceTimelineEvent(
                id=f"reminder-created-{service.id}", occurred_at=created_at.isoformat(), event_type="Reminder created",
                title=f"{service.service_type} reminder created",
                description=(f"Due at {service.next_service_odometer_km:,} km." if service.next_service_odometer_km else None),
                status=status.value, related_record_type="Service Reminder", related_record_id=service.id,
                href=f"/services/reminders?reminder_id={service.id}",
            ))
            if status != ReminderStatus.upcoming:
                status_time = service.updated_at if status in {ReminderStatus.resolved, ReminderStatus.dismissed} else service.next_service_date or service.updated_at or service.service_date
                events.append(MaintenanceTimelineEvent(
                    id=f"reminder-status-{service.id}", occurred_at=status_time.isoformat(),
                    event_type=f"Reminder {status.value.lower()}", title=f"{service.service_type} reminder",
                    description=(f"Due at {service.next_service_odometer_km:,} km." if service.next_service_odometer_km else None),
                    status=status.value, related_record_type="Service Reminder", related_record_id=service.id,
                    href=f"/services/reminders?reminder_id={service.id}",
                ))

    events.sort(key=lambda event: event.occurred_at, reverse=True)
    total = len(events)
    start = (page - 1) * page_size
    return MaintenanceTimelinePage(items=events[start:start + page_size], page=page, page_size=page_size, total=total, pages=(total + page_size - 1) // page_size)
