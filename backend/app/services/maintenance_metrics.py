"""Shared maintenance aggregations used by maintenance and dashboard views."""

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import Numeric, case, cast, func, or_
from sqlalchemy.orm import Query, Session

from app.models import Vehicle, VehicleService, WorkOrder
from app.schemas import ReminderStatus, WorkOrderStatus


def decimal_value(value) -> Decimal:
    return Decimal(str(value or 0))


def reminder_status_expression(today: datetime):
    due_soon = today + timedelta(days=30)
    return case(
        (VehicleService.reminder_status == ReminderStatus.resolved.value, ReminderStatus.resolved.value),
        (VehicleService.reminder_status == ReminderStatus.dismissed.value, ReminderStatus.dismissed.value),
        (or_(VehicleService.next_service_date < today, VehicleService.next_service_odometer_km < Vehicle.odometer_km), ReminderStatus.overdue.value),
        (or_(func.date(VehicleService.next_service_date) == today.date(), VehicleService.next_service_odometer_km == Vehicle.odometer_km), ReminderStatus.due.value),
        (or_(VehicleService.next_service_date <= due_soon, VehicleService.next_service_odometer_km - Vehicle.odometer_km <= 1000), ReminderStatus.due_soon.value),
        else_=ReminderStatus.upcoming.value,
    )


def current_reminder_status(service: VehicleService, *, today=None) -> ReminderStatus:
    if service.reminder_status in {ReminderStatus.resolved.value, ReminderStatus.dismissed.value}:
        return ReminderStatus(service.reminder_status)
    effective_today = today or datetime.today().date()
    current_odometer = service.vehicle.odometer_km if service.vehicle else None
    if service.next_service_date:
        days_left = (service.next_service_date.date() - effective_today).days
        if days_left < 0:
            return ReminderStatus.overdue
        if days_left == 0:
            return ReminderStatus.due
        if days_left <= 30:
            return ReminderStatus.due_soon
    if service.next_service_odometer_km is not None and current_odometer is not None:
        km_left = service.next_service_odometer_km - current_odometer
        if km_left < 0:
            return ReminderStatus.overdue
        if km_left == 0:
            return ReminderStatus.due
        if km_left <= 1000:
            return ReminderStatus.due_soon
    return ReminderStatus.upcoming


def latest_reminders_query(db: Session) -> Query:
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
    return (
        db.query(VehicleService)
        .join(ranked, VehicleService.id == ranked.c.service_id)
        .filter(ranked.c.row_number == 1)
        .join(VehicleService.vehicle)
    )


def actual_maintenance_cost(
    db: Session,
    start: datetime | None = None,
    end: datetime | None = None,
    vehicle_id: int | None = None,
    vehicle_ids: set[int] | None = None,
) -> Decimal:
    """Return actual service and unlinked completed Work Order costs.

    A linked Service is authoritative and its Work Order cost is excluded.
    """
    service_query = db.query(
        func.coalesce(func.sum(cast(VehicleService.cost, Numeric(14, 2))), 0)
    ).filter(VehicleService.archived.is_(False))
    order_query = db.query(
        func.coalesce(func.sum(cast(WorkOrder.total_cost, Numeric(14, 2))), 0)
    ).filter(
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
    if vehicle_ids is not None:
        if not vehicle_ids:
            return Decimal("0")
        service_query = service_query.filter(VehicleService.vehicle_id.in_(vehicle_ids))
        order_query = order_query.filter(WorkOrder.vehicle_id.in_(vehicle_ids))
    return decimal_value(service_query.scalar()) + decimal_value(order_query.scalar())
