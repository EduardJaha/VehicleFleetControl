"""Permission-aware operational metrics for the management dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.authorization import active_role, authorization_scope, has_permission
from app.models import (
    AccidentClaim,
    AuditLog,
    CostCenter,
    Department,
    Driver,
    Inspection,
    Location,
    User,
    Vehicle,
    VehicleAccident,
    VehicleAssignment,
    VehicleConditionRecord,
    VehicleFuel,
    VehicleOperatingCost,
    VehicleReservation,
    VehicleService,
    WorkOrder,
)
from app.schemas import ReminderStatus
from app.services.document_compliance import compliance_dashboard
from app.services.maintenance_metrics import actual_maintenance_cost, current_reminder_status, latest_reminders_query
from app.services.tco import tco_report


ACTIVE_ASSIGNMENT_STATUSES = ("Active", "Overdue")
ACTIVE_WORK_ORDER_STATUSES = ("Open", "Assigned", "In Progress", "Waiting for Parts")
OPEN_ACCIDENT_STATUSES = ("Reported", "Under Review", "Claim Opened", "Repair Approved", "Repair In Progress")
OPEN_CLAIM_STATUSES = ("Open", "Under Review", "Approved")
OPERATIONAL_VEHICLE_STATUSES = (0, 1, 4)
PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


@dataclass(frozen=True)
class DashboardDateRange:
    period: str
    start: datetime
    end: datetime
    previous_start: datetime
    previous_end: datetime


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)


def resolve_dashboard_period(
    period: str,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    now: datetime | None = None,
) -> DashboardDateRange:
    current = now or datetime.utcnow()
    today = current.date()
    key = (period or "this_month").strip().lower()
    if key == "custom":
        if from_date is None or to_date is None:
            raise HTTPException(status_code=422, detail="from_date and to_date are required for a custom period.")
        if from_date > to_date:
            raise HTTPException(status_code=422, detail="from_date must be on or before to_date.")
        start_date, end_date = from_date, to_date + timedelta(days=1)
    elif key == "today":
        start_date, end_date = today, today + timedelta(days=1)
    elif key == "last_7_days":
        start_date, end_date = today - timedelta(days=6), today + timedelta(days=1)
    elif key == "last_month":
        end_date = _month_start(today)
        start_date = _month_start(end_date - timedelta(days=1))
    elif key == "this_quarter":
        quarter_month = ((today.month - 1) // 3) * 3 + 1
        start_date = date(today.year, quarter_month, 1)
        end_date = date(today.year + (quarter_month == 10), 1 if quarter_month == 10 else quarter_month + 3, 1)
    elif key == "this_year":
        start_date, end_date = date(today.year, 1, 1), date(today.year + 1, 1, 1)
    elif key == "this_month":
        start_date, end_date = _month_start(today), _next_month(today)
    else:
        raise HTTPException(status_code=422, detail="Unsupported dashboard period.")
    start = datetime.combine(start_date, time.min)
    end = datetime.combine(end_date, time.min)
    duration = end - start
    return DashboardDateRange(key, start, end, start - duration, start)


def _validate_filter(db: Session, model, selected_id: int | None, allowed_ids: set[int], label: str) -> None:
    if selected_id is None:
        return
    if db.get(model, selected_id) is None:
        raise HTTPException(status_code=422, detail=f"The selected {label} does not exist.")
    if allowed_ids and selected_id not in allowed_ids:
        raise HTTPException(status_code=403, detail=f"The selected {label} is outside your authorization scope.")


def _vehicle_ids_for_driver_scope(db: Session, driver_id: int) -> set[int]:
    assigned = {
        vehicle_id for (vehicle_id,) in db.query(Driver.assigned_vehicle_id).filter(
            Driver.id == driver_id, Driver.assigned_vehicle_id.isnot(None)
        ).all()
    }
    assigned.update(
        vehicle_id for (vehicle_id,) in db.query(VehicleAssignment.vehicle_id).filter(
            VehicleAssignment.driver_id == driver_id,
            VehicleAssignment.archived.is_(False),
        ).all()
    )
    return assigned


def scoped_dashboard_entities(
    db: Session,
    user: User,
    *,
    location_id: int | None,
    department_id: int | None,
    cost_center_id: int | None,
) -> tuple[set[int], set[int], dict]:
    """Resolve authorized Vehicle and Driver IDs before widget calculations."""
    access = authorization_scope(db, user, "dashboard.view")
    _validate_filter(db, Location, location_id, access.location_ids, "location")
    _validate_filter(db, Department, department_id, access.department_ids, "department")
    _validate_filter(db, CostCenter, cost_center_id, access.cost_center_ids, "cost center")

    vehicle_query = db.query(Vehicle.id).filter(Vehicle.archived.is_(False))
    driver_query = db.query(Driver.id).filter(Driver.archived.is_(False))

    location_ids = {location_id} if location_id is not None else set(access.location_ids)
    department_ids = {department_id} if department_id is not None else set(access.department_ids)
    cost_center_ids = {cost_center_id} if cost_center_id is not None else set(access.cost_center_ids)

    if location_ids:
        vehicle_query = vehicle_query.filter(Vehicle.location_id.in_(location_ids))
        location_vehicle_ids = db.query(Vehicle.id).filter(
            Vehicle.archived.is_(False), Vehicle.location_id.in_(location_ids)
        )
        active_location_drivers = db.query(VehicleAssignment.driver_id).filter(
            VehicleAssignment.vehicle_id.in_(location_vehicle_ids),
            VehicleAssignment.archived.is_(False),
            VehicleAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
        )
        driver_query = driver_query.filter(or_(
            Driver.assigned_vehicle_id.in_(location_vehicle_ids),
            Driver.id.in_(active_location_drivers),
        ))
    if department_ids or cost_center_ids:
        driver_filters = [Driver.archived.is_(False)]
        if department_ids:
            driver_filters.append(Driver.department_id.in_(department_ids))
            driver_query = driver_query.filter(Driver.department_id.in_(department_ids))
        if cost_center_ids:
            driver_filters.append(Driver.cost_center_id.in_(cost_center_ids))
            driver_query = driver_query.filter(Driver.cost_center_id.in_(cost_center_ids))
        direct_ids = db.query(Driver.assigned_vehicle_id).filter(
            *driver_filters, Driver.assigned_vehicle_id.isnot(None)
        )
        active_ids = db.query(VehicleAssignment.vehicle_id).join(Driver, VehicleAssignment.driver_id == Driver.id).filter(
            *driver_filters,
            VehicleAssignment.archived.is_(False),
            VehicleAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
        )
        vehicle_query = vehicle_query.filter(or_(Vehicle.id.in_(direct_ids), Vehicle.id.in_(active_ids)))

    driver_profile = user.driver_profile
    own_only = access.own_records_only or active_role(db, user) == "driver"
    if own_only:
        if driver_profile is None:
            vehicle_query = vehicle_query.filter(False)
            driver_query = driver_query.filter(False)
        else:
            own_vehicle_ids = _vehicle_ids_for_driver_scope(db, driver_profile.id)
            vehicle_query = vehicle_query.filter(Vehicle.id.in_(own_vehicle_ids)) if own_vehicle_ids else vehicle_query.filter(False)
            driver_query = driver_query.filter(Driver.id == driver_profile.id)

    vehicle_ids = {row[0] for row in vehicle_query.distinct().all()}
    driver_ids = {row[0] for row in driver_query.distinct().all()}
    options = {
        "locations": [
            {"id": row.id, "name": row.name}
            for row in db.query(Location).filter(Location.is_active.is_(True)).order_by(Location.name).all()
            if not access.location_ids or row.id in access.location_ids
        ],
        "departments": [
            {"id": row.id, "name": row.name}
            for row in db.query(Department).filter(Department.is_active.is_(True)).order_by(Department.name).all()
            if not access.department_ids or row.id in access.department_ids
        ],
        "cost_centers": [
            {"id": row.id, "name": row.name}
            for row in db.query(CostCenter).filter(CostCenter.is_active.is_(True)).order_by(CostCenter.name).all()
            if not access.cost_center_ids or row.id in access.cost_center_ids
        ],
    }
    return vehicle_ids, driver_ids, options


def calculate_vehicle_availability(db: Session, vehicle_ids: set[int]) -> dict:
    counts = {0: 0, 1: 0, 4: 0}
    if vehicle_ids:
        counts.update({
            int(status): int(count)
            for status, count in db.query(Vehicle.status, func.count(Vehicle.id)).filter(
                Vehicle.id.in_(vehicle_ids),
                Vehicle.archived.is_(False),
                Vehicle.status.in_(OPERATIONAL_VEHICLE_STATUSES),
            ).group_by(Vehicle.status).all()
        })
    operational = sum(counts.values())
    available = counts.get(0, 0)
    total = len(vehicle_ids)
    return {
        "total": total,
        "operational": operational,
        "available": available,
        "in_use": counts.get(4, 0),
        "in_service": counts.get(1, 0),
        "unavailable": max(total - operational, 0),
        "availability_percentage": round(available / total * 100, 1) if total else 0.0,
    }


def _priority_item(
    *,
    item_id: str,
    item_type: str,
    priority: str,
    title_key: str,
    message_key: str,
    params: dict,
    entity_type: str,
    entity_id: int,
    url: str,
    occurred_at: datetime | None,
    due_at: datetime | None = None,
) -> dict:
    return {
        "id": item_id,
        "type": item_type,
        "priority": priority,
        "title_key": title_key,
        "message_key": message_key,
        "params": params,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "url": url,
        "occurred_at": (occurred_at or datetime.utcnow()).isoformat(),
        "due_at": due_at.isoformat() if due_at else None,
    }


def _maintenance_and_attention(
    db: Session,
    user: User,
    vehicle_ids: set[int],
    driver_ids: set[int],
    now: datetime,
) -> tuple[dict | None, list[dict]]:
    if not has_permission(db, user, "maintenance.view") or not vehicle_ids:
        return None, []
    base = db.query(WorkOrder).options(joinedload(WorkOrder.vehicle)).filter(
        WorkOrder.vehicle_id.in_(vehicle_ids), WorkOrder.archived.is_(False)
    )
    status_counts = dict(base.with_entities(WorkOrder.status, func.count(WorkOrder.id)).group_by(WorkOrder.status).all())
    critical_count = base.filter(WorkOrder.priority == "Critical", WorkOrder.status.in_(ACTIVE_WORK_ORDER_STATUSES)).count()
    overdue_count = base.filter(WorkOrder.expected_completion_date < now, WorkOrder.status.in_(ACTIVE_WORK_ORDER_STATUSES)).count()
    failed_count = db.query(func.count(Inspection.id)).filter(
        Inspection.vehicle_id.in_(vehicle_ids), Inspection.archived.is_(False), Inspection.overall_status == "Failed"
    ).scalar() or 0
    reminders = latest_reminders_query(db).options(joinedload(VehicleService.vehicle)).filter(
        VehicleService.vehicle_id.in_(vehicle_ids)
    ).all()
    overdue_reminders = [row for row in reminders if current_reminder_status(row, today=now.date()) == ReminderStatus.overdue]
    maintenance = {
        "open_work_orders": sum(int(status_counts.get(status, 0)) for status in ACTIVE_WORK_ORDER_STATUSES),
        "critical_work_orders": critical_count,
        "overdue_work_orders": overdue_count,
        "waiting_for_parts": int(status_counts.get("Waiting for Parts", 0)),
        "vehicles_in_service": db.query(func.count(Vehicle.id)).filter(Vehicle.id.in_(vehicle_ids), Vehicle.status == 1).scalar() or 0,
        "overdue_reminders": len(overdue_reminders),
        "failed_inspections": int(failed_count),
    }
    attention: list[dict] = []
    orders = base.filter(or_(
        and_(WorkOrder.priority == "Critical", WorkOrder.status.in_(ACTIVE_WORK_ORDER_STATUSES)),
        and_(WorkOrder.expected_completion_date < now, WorkOrder.status.in_(ACTIVE_WORK_ORDER_STATUSES)),
    )).order_by(WorkOrder.expected_completion_date, WorkOrder.created_at).limit(12).all()
    for order in orders:
        overdue = bool(order.expected_completion_date and order.expected_completion_date < now)
        days = max((now - order.expected_completion_date).days, 0) if overdue else 0
        attention.append(_priority_item(
            item_id=f"work-order:{order.id}", item_type="work_order_overdue" if overdue else "work_order_critical",
            priority="Critical", title_key="dashboard.attention.workOrderOverdue" if overdue else "dashboard.attention.workOrderCritical",
            message_key="dashboard.attention.workOrderDescription",
            params={"work_order_id": order.id, "license_plate": order.vehicle.license_plate, "days_overdue": days},
            entity_type="work_order", entity_id=order.id, url=f"/work-orders/{order.id}",
            occurred_at=order.created_at, due_at=order.expected_completion_date,
        ))
    for reminder in overdue_reminders[:6]:
        km_overdue = None
        if reminder.next_service_odometer_km is not None and reminder.vehicle.odometer_km is not None:
            km_overdue = max(reminder.vehicle.odometer_km - reminder.next_service_odometer_km, 0)
        attention.append(_priority_item(
            item_id=f"service-reminder:{reminder.id}", item_type="service_overdue", priority="High",
            title_key="dashboard.attention.serviceOverdue", message_key="dashboard.attention.serviceOverdueDescription",
            params={"service_type": reminder.service_type, "license_plate": reminder.vehicle.license_plate, "km_overdue": km_overdue},
            entity_type="service_reminder", entity_id=reminder.id,
            url=f"/services/reminders?reminder_id={reminder.id}", occurred_at=reminder.service_date, due_at=reminder.next_service_date,
        ))
    inspections = db.query(Inspection).options(joinedload(Inspection.vehicle)).filter(
        Inspection.vehicle_id.in_(vehicle_ids), Inspection.archived.is_(False), Inspection.overall_status == "Failed"
    ).order_by(Inspection.inspection_date.desc()).limit(6).all()
    for inspection in inspections:
        attention.append(_priority_item(
            item_id=f"inspection:{inspection.id}", item_type="inspection_failed", priority="High",
            title_key="dashboard.attention.inspectionFailed", message_key="dashboard.attention.inspectionFailedDescription",
            params={"inspection_type": inspection.inspection_type, "license_plate": inspection.vehicle.license_plate},
            entity_type="inspection", entity_id=inspection.id, url=f"/inspections/{inspection.id}",
            occurred_at=inspection.inspection_date,
        ))
    return maintenance, attention


def _compliance_metrics(db: Session, user: User, vehicle_ids: set[int], driver_ids: set[int], today: date) -> tuple[dict | None, list[dict]]:
    if not has_permission(db, user, "documents.view"):
        return None, []
    result = compliance_dashboard(db, today=today, vehicle_ids=vehicle_ids, driver_ids=driver_ids)
    metrics = {
        "percentage": result["overall_compliance_rate"],
        "missing_required": len(result["missing_required"]),
        "expired": len(result["expired"]),
        "expiring_7_days": len(result["expiring_in_7_days"]),
        "expiring_30_days": len(result["expiring_in_30_days"]),
        "renewal_in_progress": len(result["renewal_in_progress"]),
    }
    attention = []
    for item in (result["expired"][:4] + result["missing_required"][:4]):
        expired = item["status"] == "Expired"
        attention.append(_priority_item(
            item_id=f"document:{item.get('document_id') or item['owner_type'] + ':' + str(item['owner_id']) + ':' + str(item['requirement_id'])}",
            item_type="document_expired" if expired else "document_missing", priority="High",
            title_key="dashboard.attention.documentExpired" if expired else "dashboard.attention.documentMissing",
            message_key="dashboard.attention.documentDescription",
            params={"owner": item["owner_name"], "document_type": item["document_type"]},
            entity_type="document", entity_id=item.get("document_id") or item["owner_id"],
            url=f"/compliance/documents?status={'Expired' if expired else 'Missing'}",
            occurred_at=datetime.combine(date.fromisoformat(item["expiry_date"]), time.min) if item.get("expiry_date") else None,
        ))
    return metrics, attention


def _usage_metrics(db: Session, user: User, vehicle_ids: set[int], driver_ids: set[int], now: datetime) -> tuple[dict | None, list[dict]]:
    if not has_permission(db, user, "assignments.view"):
        return None, []
    query = db.query(VehicleAssignment).options(
        joinedload(VehicleAssignment.vehicle), joinedload(VehicleAssignment.driver), joinedload(VehicleAssignment.reservation)
    ).filter(
        VehicleAssignment.vehicle_id.in_(vehicle_ids) if vehicle_ids else False,
        VehicleAssignment.archived.is_(False),
        VehicleAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
        VehicleAssignment.end_datetime.is_(None),
    )
    if active_role(db, user) == "driver" or authorization_scope(db, user, "dashboard.view").own_records_only:
        query = query.filter(VehicleAssignment.driver_id.in_(driver_ids)) if driver_ids else query.filter(False)
    rows = query.order_by(VehicleAssignment.status.desc(), VehicleAssignment.start_datetime).all()
    records, attention = [], []
    for assignment in rows[:8]:
        expected = assignment.reservation.end_date if assignment.reservation else None
        overdue = assignment.status == "Overdue" or bool(expected and expected < now)
        records.append({
            "assignment_id": assignment.id, "vehicle_id": assignment.vehicle_id, "driver_id": assignment.driver_id,
            "license_plate": assignment.vehicle.license_plate, "vehicle_name": f"{assignment.vehicle.brand} {assignment.vehicle.model}",
            "driver_name": assignment.driver.full_name, "checkout_datetime": assignment.start_datetime.isoformat(),
            "expected_return_datetime": expected.isoformat() if expected else None, "destination": assignment.destination,
            "duration_minutes": max(int((now - assignment.start_datetime).total_seconds() // 60), 0),
            "overdue_minutes": max(int((now - expected).total_seconds() // 60), 0) if expected and overdue else 0,
            "overdue": overdue,
        })
        if overdue:
            attention.append(_priority_item(
                item_id=f"assignment:{assignment.id}", item_type="return_overdue", priority="Critical",
                title_key="dashboard.attention.returnOverdue", message_key="dashboard.attention.returnOverdueDescription",
                params={"license_plate": assignment.vehicle.license_plate, "driver": assignment.driver.full_name,
                        "minutes_overdue": records[-1]["overdue_minutes"]},
                entity_type="vehicle_assignment", entity_id=assignment.id, url=f"/vehicle-assignments/{assignment.id}",
                occurred_at=assignment.start_datetime, due_at=expected,
            ))
    return {"active_count": len(rows), "overdue_returns": sum(1 for row in records if row["overdue"]), "records": records}, attention


def _reservation_metrics(db: Session, user: User, vehicle_ids: set[int], now: datetime) -> dict | None:
    if not has_permission(db, user, "reservations.view"):
        return None
    day_start = datetime.combine(now.date(), time.min)
    day_end = day_start + timedelta(days=1)
    base = db.query(VehicleReservation).filter(
        VehicleReservation.vehicle_id.in_(vehicle_ids) if vehicle_ids else False,
        VehicleReservation.archived.is_(False),
    )
    pending = base.filter(VehicleReservation.status == 0).count()
    today_rows = base.options(joinedload(VehicleReservation.vehicle)).filter(
        VehicleReservation.start_date >= day_start, VehicleReservation.start_date < day_end,
        VehicleReservation.status.in_((0, 1)),
    ).order_by(VehicleReservation.start_date).limit(6).all()
    return {
        "pending": pending,
        "approved_today": sum(1 for row in today_rows if row.status == 1),
        "starting_today": len(today_rows),
        "records": [{
            "id": row.id, "vehicle_id": row.vehicle_id, "license_plate": row.vehicle.license_plate,
            "reserved_by": row.reserved_by, "start_date": row.start_date.isoformat(), "end_date": row.end_date.isoformat(),
            "status": row.status, "status_name": {0: "Pending", 1: "Approved"}.get(row.status, str(row.status)),
        } for row in today_rows],
    }


def _accident_financials(db: Session, vehicle_ids: set[int], start: datetime, end: datetime) -> dict:
    rows = db.query(VehicleAccident).options(joinedload(VehicleAccident.claim)).filter(
        VehicleAccident.vehicle_id.in_(vehicle_ids) if vehicle_ids else False,
        VehicleAccident.archived.is_(False), VehicleAccident.accident_date >= start, VehicleAccident.accident_date < end,
    ).all()
    damage = sum((Decimal(str(row.actual_damage_cost if row.actual_damage_cost is not None else row.estimated_damage_cost or 0)) for row in rows), Decimal("0"))
    recovered = sum((Decimal(str(row.claim.settlement_amount or 0)) for row in rows if row.claim), Decimal("0"))
    return {"rows": rows, "damage": damage, "recovered": recovered, "unrecovered": max(damage - recovered, Decimal("0"))}


def _cost_values(db: Session, vehicle_ids: set[int], start: datetime, end: datetime) -> dict:
    if not vehicle_ids:
        return {key: Decimal("0") for key in ("fuel", "charging", "maintenance", "accidents", "other", "total")}
    fuel_rows = dict(db.query(VehicleFuel.unit, func.coalesce(func.sum(VehicleFuel.total_cost), 0)).filter(
        VehicleFuel.vehicle_id.in_(vehicle_ids), VehicleFuel.archived.is_(False),
        VehicleFuel.refuel_date >= start, VehicleFuel.refuel_date < end,
    ).group_by(VehicleFuel.unit).all())
    fuel = Decimal(str(fuel_rows.get("L", 0)))
    charging = Decimal(str(fuel_rows.get("KWH", 0)))
    maintenance = actual_maintenance_cost(db, start, end, vehicle_ids=vehicle_ids)
    accident = _accident_financials(db, vehicle_ids, start, end)["unrecovered"]
    other = Decimal(str(db.query(func.coalesce(func.sum(VehicleOperatingCost.amount), 0)).filter(
        VehicleOperatingCost.vehicle_id.in_(vehicle_ids), VehicleOperatingCost.archived.is_(False),
        VehicleOperatingCost.cost_date >= start.date(), VehicleOperatingCost.cost_date < end.date(),
    ).scalar() or 0))
    return {"fuel": fuel, "charging": charging, "maintenance": maintenance, "accidents": accident, "other": other,
            "total": fuel + charging + maintenance + accident + other}


def _cost_trend(db: Session, vehicle_ids: set[int], end: datetime) -> list[dict]:
    end_month = _month_start((end - timedelta(microseconds=1)).date())
    months = []
    cursor = end_month
    for _ in range(6):
        months.append(cursor)
        cursor = _month_start(cursor - timedelta(days=1))
    months.reverse()
    return [
        {"period": month.strftime("%Y-%m"), **{key: float(value) for key, value in _cost_values(
            db, vehicle_ids, datetime.combine(month, time.min), datetime.combine(_next_month(month), time.min)
        ).items()}}
        for month in months
    ]


def _cost_and_safety(db: Session, user: User, vehicle_ids: set[int], dates: DashboardDateRange) -> tuple[dict | None, dict | None]:
    can_view_costs = has_permission(db, user, "fuel.view_cost") and has_permission(db, user, "reports.view")
    costs = None
    if can_view_costs:
        current = _cost_values(db, vehicle_ids, dates.start, dates.end)
        previous = _cost_values(db, vehicle_ids, dates.previous_start, dates.previous_end)
        previous_total = previous["total"]
        change = ((current["total"] - previous_total) / previous_total * 100) if previous_total else None
        costs = {
            **{key: float(value) for key, value in current.items()},
            "previous_period_total": float(previous_total),
            "change_percentage": round(float(change), 1) if change is not None else None,
            "trend": _cost_trend(db, vehicle_ids, dates.end),
        }
    safety = None
    if has_permission(db, user, "accidents.view"):
        financials = _accident_financials(db, vehicle_ids, dates.start, dates.end)
        open_accidents = db.query(func.count(VehicleAccident.id)).filter(
            VehicleAccident.vehicle_id.in_(vehicle_ids) if vehicle_ids else False,
            VehicleAccident.archived.is_(False), VehicleAccident.status.in_(OPEN_ACCIDENT_STATUSES),
        ).scalar() or 0
        open_claims = db.query(func.count(AccidentClaim.id)).join(VehicleAccident).filter(
            VehicleAccident.vehicle_id.in_(vehicle_ids) if vehicle_ids else False,
            VehicleAccident.archived.is_(False), AccidentClaim.claim_status.in_(OPEN_CLAIM_STATUSES),
        ).scalar() or 0
        unavailable = db.query(func.count(VehicleAccident.id)).filter(
            VehicleAccident.vehicle_id.in_(vehicle_ids) if vehicle_ids else False,
            VehicleAccident.archived.is_(False), VehicleAccident.status.in_(OPEN_ACCIDENT_STATUSES),
            VehicleAccident.vehicle_available_after_accident.is_(False),
        ).scalar() or 0
        safety = {
            "accidents_period": len(financials["rows"]), "open_accidents": int(open_accidents),
            "open_claims": int(open_claims), "vehicles_unavailable": int(unavailable),
            "damage_cost": float(financials["damage"]) if can_view_costs else None,
            "recovered_cost": float(financials["recovered"]) if can_view_costs else None,
            "unrecovered_cost": float(financials["unrecovered"]) if can_view_costs else None,
        }
    return costs, safety


def _fleet_health(db: Session, user: User, vehicle_ids: set[int], dates: DashboardDateRange) -> dict | None:
    if not (has_permission(db, user, "reports.view") and has_permission(db, user, "fuel.view_cost")):
        return None
    vehicles = db.query(Vehicle).filter(
        Vehicle.id.in_(vehicle_ids) if vehicle_ids else False,
        Vehicle.archived.is_(False), Vehicle.status.in_(OPERATIONAL_VEHICLE_STATUSES),
    ).all()
    report = tco_report(db, vehicles, dates.start.date(), (dates.end - timedelta(days=1)).date())
    candidates = [row for row in report["rows"] if row["recommendation_status"] in {"Replace", "Replace Soon"}]
    return {
        "replace": sum(1 for row in report["rows"] if row["recommendation_status"] == "Replace"),
        "replace_soon": sum(1 for row in report["rows"] if row["recommendation_status"] == "Replace Soon"),
        "high_cost": sum(1 for row in report["rows"] if row["cost_per_km"] is not None and row["cost_per_km"] >= 0.5),
        "anomalies": int(report["kpis"]["anomaly_count"]),
        "candidates": [{
            "vehicle_id": row["vehicle_id"], "license_plate": row["license_plate"], "vehicle": row["vehicle"],
            "status": row["recommendation_status"], "cost_per_km": row["cost_per_km"],
            "downtime_days": row["downtime_days"],
        } for row in candidates[:4]],
    }


ACTIVITY_ACTION_KEYS = {
    "Vehicle created": "dashboard.activity.vehicleCreated",
    "Vehicle returned": "dashboard.activity.vehicleReturned",
    "Vehicle Assignment created": "dashboard.activity.assignmentCreated",
    "Reservation approved": "dashboard.activity.reservationApproved",
    "Inspection created": "dashboard.activity.inspectionCreated",
    "Work Order created": "dashboard.activity.workOrderCreated",
    "Work Order completed": "dashboard.activity.workOrderCompleted",
    "Service created": "dashboard.activity.serviceCompleted",
    "Fuel record created": "dashboard.activity.fuelAdded",
    "Accident reported": "dashboard.activity.accidentReported",
    "Document uploaded": "dashboard.activity.documentRenewed",
}


def _activity_url(row: AuditLog) -> str | None:
    if row.entity_id is None:
        return None
    return {
        "Vehicle": f"/vehicles/{row.entity_id}", "VehicleAssignment": f"/vehicle-assignments/{row.entity_id}",
        "VehicleReservation": "/reservations", "Inspection": f"/inspections/{row.entity_id}",
        "WorkOrder": f"/work-orders/{row.entity_id}", "VehicleService": f"/services/{row.entity_id}",
        "VehicleAccident": f"/accidents/{row.entity_id}", "VehicleFuel": "/fuel",
        "VehiclePaper": "/compliance/documents",
    }.get(row.entity_type)


def _recent_activity(db: Session, user: User) -> list[dict] | None:
    if not has_permission(db, user, "audit_logs.view"):
        return None
    scope = authorization_scope(db, user, "dashboard.view")
    if not scope.unrestricted or active_role(db, user) == "driver":
        return None
    rows = db.query(AuditLog).filter(AuditLog.action.in_(ACTIVITY_ACTION_KEYS)).order_by(
        AuditLog.created_at.desc(), AuditLog.id.desc()
    ).limit(8).all()
    return [{
        "id": row.id, "action_key": row.description_key or ACTIVITY_ACTION_KEYS[row.action],
        "params": row.description_params or {"id": row.entity_id}, "description": row.description,
        "entity_type": row.entity_type, "entity_id": row.entity_id, "url": _activity_url(row),
        "occurred_at": row.created_at.isoformat(),
    } for row in rows]


def build_dashboard_overview(
    db: Session,
    user: User,
    *,
    period: str = "this_month",
    from_date: date | None = None,
    to_date: date | None = None,
    location_id: int | None = None,
    department_id: int | None = None,
    cost_center_id: int | None = None,
    now: datetime | None = None,
) -> dict:
    generated = now or datetime.utcnow()
    dates = resolve_dashboard_period(period, from_date=from_date, to_date=to_date, now=generated)
    vehicle_ids, driver_ids, options = scoped_dashboard_entities(
        db, user, location_id=location_id, department_id=department_id, cost_center_id=cost_center_id
    )
    if not has_permission(db, user, "vehicles.view"):
        vehicle_ids = set()
    fleet = calculate_vehicle_availability(db, vehicle_ids)
    maintenance, attention = _maintenance_and_attention(db, user, vehicle_ids, driver_ids, generated)
    compliance, compliance_attention = _compliance_metrics(db, user, vehicle_ids, driver_ids, generated.date())
    usage, usage_attention = _usage_metrics(db, user, vehicle_ids, driver_ids, generated)
    attention.extend(compliance_attention)
    attention.extend(usage_attention)

    if driver_ids:
        expired_drivers = db.query(Driver).filter(
            Driver.id.in_(driver_ids), Driver.archived.is_(False), Driver.license_expiry_date < generated
        ).order_by(Driver.license_expiry_date).limit(4).all()
        for driver in expired_drivers:
            attention.append(_priority_item(
                item_id=f"driver-license:{driver.id}", item_type="driver_license_expired", priority="High",
                title_key="dashboard.attention.driverLicenceExpired", message_key="dashboard.attention.driverLicenceDescription",
                params={"driver": driver.full_name}, entity_type="driver", entity_id=driver.id,
                url=f"/drivers/{driver.id}", occurred_at=driver.license_expiry_date,
            ))
    if vehicle_ids and has_permission(db, user, "assignments.view"):
        damages = db.query(VehicleConditionRecord).options(joinedload(VehicleConditionRecord.vehicle)).filter(
            VehicleConditionRecord.vehicle_id.in_(vehicle_ids), VehicleConditionRecord.record_type == "Return",
            VehicleConditionRecord.recorded_at >= dates.start, VehicleConditionRecord.recorded_at < dates.end,
            or_(VehicleConditionRecord.damage_description.isnot(None), VehicleConditionRecord.vehicle_condition.notin_(("Good", "Excellent"))),
        ).order_by(VehicleConditionRecord.recorded_at.desc()).limit(4).all()
        for damage in damages:
            attention.append(_priority_item(
                item_id=f"return-damage:{damage.id}", item_type="vehicle_returned_damaged", priority="High",
                title_key="dashboard.attention.vehicleReturnedDamaged", message_key="dashboard.attention.vehicleReturnedDamagedDescription",
                params={"license_plate": damage.vehicle.license_plate}, entity_type="vehicle_assignment",
                entity_id=damage.vehicle_assignment_id, url=f"/vehicle-assignments/{damage.vehicle_assignment_id}",
                occurred_at=damage.recorded_at,
            ))
    if vehicle_ids and has_permission(db, user, "accidents.view"):
        accidents = db.query(VehicleAccident).options(joinedload(VehicleAccident.vehicle)).filter(
            VehicleAccident.vehicle_id.in_(vehicle_ids), VehicleAccident.archived.is_(False),
            VehicleAccident.status.in_(OPEN_ACCIDENT_STATUSES), VehicleAccident.severity.in_(("Severe", "Critical")),
        ).order_by(VehicleAccident.accident_date).limit(4).all()
        for accident in accidents:
            attention.append(_priority_item(
                item_id=f"accident:{accident.id}", item_type="accident_critical", priority="Critical",
                title_key="dashboard.attention.accidentCritical", message_key="dashboard.attention.accidentCriticalDescription",
                params={"license_plate": accident.vehicle.license_plate, "severity": accident.severity},
                entity_type="accident", entity_id=accident.id, url=f"/accidents/{accident.id}", occurred_at=accident.accident_date,
            ))
    attention.sort(key=lambda item: (PRIORITY_ORDER.get(item["priority"], 9), item["due_at"] or item["occurred_at"]))
    attention_total = len(attention)
    costs, safety = _cost_and_safety(db, user, vehicle_ids, dates)
    return {
        "generated_at": generated.replace(tzinfo=timezone.utc).isoformat(),
        "filters": {
            "period": dates.period, "from_date": dates.start.date().isoformat(),
            "to_date": (dates.end - timedelta(days=1)).date().isoformat(),
            "location_id": location_id, "department_id": department_id, "cost_center_id": cost_center_id,
        },
        "filter_options": options,
        "fleet": fleet,
        "attention": attention[:10], "attention_total": attention_total,
        "maintenance": maintenance,
        "compliance": compliance,
        "usage": usage,
        "reservations": _reservation_metrics(db, user, vehicle_ids, generated),
        "costs": costs,
        "can_view_costs": costs is not None,
        "safety": safety,
        "fleet_health": _fleet_health(db, user, vehicle_ids, dates),
        "recent_activity": _recent_activity(db, user),
    }
