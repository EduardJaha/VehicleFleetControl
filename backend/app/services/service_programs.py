"""Deterministic, tenant-owned preventive maintenance scheduling.

Program reminders are deliberately separate from VehicleServices: scheduling is
not evidence of completed maintenance and never changes a manual reminder.
"""
from calendar import monthrange
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import event, func, inspect
from sqlalchemy.orm import Session

from app.models import (Driver, ServiceProgram, ServiceProgramReminder, ServiceProgramRule,
                        ServiceProgramTask, User, Vehicle, VehicleAssignment, VehicleService,
                        VehicleServiceProgram, WorkOrder)
from app.services.audit import record_audit, snapshot
from app.services.notifications import notify_roles, resolve_by_prefix

PRECEDENCE = {"Vehicle": 70, "BrandModel": 50, "Department": 40, "Location": 30, "Category": 20, "FuelType": 10}


def fail(code: str, status=422):
    raise HTTPException(status_code=status, detail={"code": code})


def add_months(day: date, months: int) -> date:
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def audit(db, row, action, user=None, old=None):
    record_audit(db, action=f"Program {action}", action_code=f"program_{action}",
                 entity_type=type(row).__name__, entity_id=row.id, user=user,
                 old_values=old, new_values=snapshot(row),
                 description_key=f"modules:programs.audit.{action}",
                 description_params={"id": row.id})


def departments(db, vehicle):
    active = db.query(Driver).join(VehicleAssignment, VehicleAssignment.driver_id == Driver.id).filter(
        VehicleAssignment.vehicle_id == vehicle.id, VehicleAssignment.company_id == vehicle.company_id,
        VehicleAssignment.archived.is_(False), VehicleAssignment.status.in_(["Active", "Overdue"]),
        Driver.company_id == vehicle.company_id, Driver.archived.is_(False)).all()
    if not active:
        active = db.query(Driver).filter(Driver.assigned_vehicle_id == vehicle.id,
                                        Driver.company_id == vehicle.company_id, Driver.archived.is_(False)).all()
    return {str(driver.department_id) for driver in active if driver.department_id}


def winning_rule(db, vehicle, today=None):
    today = today or date.today()
    rules = db.query(ServiceProgramRule).join(ServiceProgramRule.program).filter(
        ServiceProgramRule.company_id == vehicle.company_id,
        ServiceProgramRule.is_active.is_(True), ServiceProgramRule.effective_from <= today,
        ServiceProgram.company_id == vehicle.company_id, ServiceProgram.is_active.is_(True),
        ServiceProgram.archived.is_(False)).all()
    department_ids = departments(db, vehicle) if any(r.target_type == "Department" for r in rules) else set()
    values = {"Vehicle": str(vehicle.id), "FuelType": vehicle.fuel_type,
              "Category": vehicle.vehicle_category, "Location": str(vehicle.location_id)}
    matches = []
    for rule in rules:
        value = rule.target_value.casefold()
        if rule.target_type == "BrandModel":
            match = vehicle.brand.casefold() == value and (not rule.model or vehicle.model.casefold() == rule.model.casefold())
        elif rule.target_type == "Department":
            match = rule.target_value in department_ids
        else:
            match = str(values.get(rule.target_type) or "").casefold() == value
        if match:
            matches.append(rule)
    return max(matches, key=lambda r: (PRECEDENCE[r.target_type] + (10 if r.model else 0), r.created_at, r.id), default=None)


def reminder_status(reminder, today=None):
    if not reminder.is_active:
        return reminder.resolution or "Resolved"
    today = today or date.today()
    task = reminder.task
    scores = []
    if task.month_interval:
        days = (reminder.due_date - today).days if reminder.due_date else None
        scores.append(-1 if days is None else 3 if days < 0 else 2 if days == 0 else 1 if days <= (task.warning_days or 0) else 0)
    if task.km_interval:
        km = reminder.due_odometer_km - reminder.vehicle.odometer_km if reminder.due_odometer_km is not None and reminder.vehicle.odometer_km is not None else None
        scores.append(-1 if km is None else 3 if km < 0 else 2 if km == 0 else 1 if km <= (task.warning_km or 0) else 0)
    score = max(scores) if task.whichever_occurs_first else min(scores)
    # Missing mileage must not count as compliant even for OR schedules, unless
    # the known date threshold already establishes an actionable condition.
    if -1 in scores and score < 2:
        return "Needs Baseline"
    return { -1: "Needs Baseline", 0: "Current", 1: "Due Soon", 2: "Due", 3: "Overdue" }[score]


def close_reminder(db, reminder, resolution, user=None):
    reminder.is_active = False
    reminder.resolution = resolution
    reminder.resolved_at = datetime.utcnow()
    resolve_by_prefix(db, f"program-reminder:{reminder.id}:")
    order = reminder.work_order
    # Close untouched automatically scheduled work, retaining started work and
    # all cost/clock history for an operator to finish explicitly.
    if order and order.status in {"Open", "Assigned"} and not (
        order.part_lines or order.labor_entries or order.vendor_charges
        or order.labor_cost or order.parts_cost or order.other_cost
    ):
        order.status = "Cancelled"
        audit(db, order, "work_order_cancelled", user)
    audit(db, reminder, "reminder_resolved", user)


def refresh_alert(db, reminder, today):
    prefix = f"program-reminder:{reminder.id}:"
    status = reminder_status(reminder, today)
    if status in {"Current", "Resolved", "Superseded", "Inactive"}:
        resolve_by_prefix(db, prefix)
        return
    notify_roles(db, roles={"admin", "fleet_manager", "mechanic"},
                 notification_type="Program task due", title=reminder.task.title,
                 message=f"{reminder.vehicle.license_plate}: {reminder.task.title} ({status}).",
                 priority=reminder.task.priority, entity_type="ServiceProgramReminder", entity_id=reminder.id,
                 deduplication_key=prefix + "alert", title_key="modules:programs.notification.title",
                 message_key="modules:programs.notification.message",
                 message_params={"plate": reminder.vehicle.license_plate, "title": reminder.task.title, "status": status})


def synchronize_vehicle(db, vehicle, user=None, today=None):
    today = today or date.today()
    # All writers serialize on the Vehicle on databases with row-level locks.
    db.query(Vehicle).filter(Vehicle.id == vehicle.id, Vehicle.company_id == vehicle.company_id).with_for_update().first()
    rule = None if vehicle.archived else winning_rule(db, vehicle, today)
    assignment = db.query(VehicleServiceProgram).filter(
        VehicleServiceProgram.vehicle_id == vehicle.id, VehicleServiceProgram.company_id == vehicle.company_id,
        VehicleServiceProgram.is_active.is_(True)).first()
    if assignment and (not rule or assignment.program_id != rule.program_id or assignment.rule_id != rule.id
                       or assignment.effective_from != rule.effective_from):
        for reminder in db.query(ServiceProgramReminder).filter(
            ServiceProgramReminder.assignment_id == assignment.id, ServiceProgramReminder.company_id == vehicle.company_id,
            ServiceProgramReminder.is_active.is_(True)).all():
            close_reminder(db, reminder, "Superseded", user)
        assignment.is_active = False
        audit(db, assignment, "unassigned", user)
        db.flush()
        assignment = None
    if not rule:
        return None
    if not assignment:
        previous = db.query(VehicleServiceProgram).filter(
            VehicleServiceProgram.vehicle_id == vehicle.id, VehicleServiceProgram.company_id == vehicle.company_id,
            VehicleServiceProgram.rule_id == rule.id, VehicleServiceProgram.effective_from == rule.effective_from,
        ).order_by(VehicleServiceProgram.id).first()
        baseline = previous.baseline_odometer_km if previous else vehicle.odometer_km
        assignment = VehicleServiceProgram(company_id=vehicle.company_id, vehicle_id=vehicle.id,
            program_id=rule.program_id, rule_id=rule.id, effective_from=rule.effective_from,
            assigned_by=rule.assigned_by, baseline_odometer_km=baseline)
        db.add(assignment)
        db.flush()
        audit(db, assignment, "assigned", user)
    active_tasks = db.query(ServiceProgramTask).filter(
        ServiceProgramTask.program_id == assignment.program_id, ServiceProgramTask.company_id == vehicle.company_id,
        ServiceProgramTask.is_active.is_(True)).order_by(ServiceProgramTask.display_order, ServiceProgramTask.id).all()
    existing = {r.task_id: r for r in db.query(ServiceProgramReminder).filter(
        ServiceProgramReminder.assignment_id == assignment.id, ServiceProgramReminder.company_id == vehicle.company_id,
        ServiceProgramReminder.is_active.is_(True)).all()}
    for task_id, reminder in existing.items():
        if task_id not in {task.id for task in active_tasks}:
            close_reminder(db, reminder, "Inactive", user)
    for task in active_tasks:
        history = db.query(VehicleService).filter(
            VehicleService.company_id == vehicle.company_id, VehicleService.vehicle_id == vehicle.id,
            func.lower(func.trim(VehicleService.service_type)) == task.service_type.lower(),
            VehicleService.status == "Completed", VehicleService.archived.is_(False),
            VehicleService.service_date < datetime.combine(today, datetime.max.time()),
        ).order_by(VehicleService.service_date.desc(), VehicleService.id.desc()).all()
        service = history[0] if history else None
        baseline_date = service.service_date.date() if service else assignment.effective_from
        baseline_km = next((s.odometer_km for s in history if s.odometer_km is not None), assignment.baseline_odometer_km)
        due_date = add_months(baseline_date, task.month_interval) if task.month_interval else None
        due_km = baseline_km + task.km_interval if task.km_interval and baseline_km is not None else None
        reminder = existing.get(task.id)
        if reminder and reminder.basis_service_id != (service.id if service else None):
            close_reminder(db, reminder, "Resolved", user)
            db.flush()
            reminder = None
        if not reminder:
            reminder = ServiceProgramReminder(company_id=vehicle.company_id, vehicle_id=vehicle.id,
                assignment_id=assignment.id, task_id=task.id, basis_service_id=service.id if service else None,
                due_date=due_date, due_odometer_km=due_km, task=task, vehicle=vehicle)
            db.add(reminder)
            db.flush()
            audit(db, reminder, "reminder_created", user)
        elif (reminder.due_date, reminder.due_odometer_km) != (due_date, due_km):
            old = snapshot(reminder)
            reminder.due_date, reminder.due_odometer_km = due_date, due_km
            audit(db, reminder, "reminder_updated", user, old)
        # Missing odometers may be supplied later; freeze the first usable value.
        if assignment.baseline_odometer_km is None and vehicle.odometer_km is not None:
            assignment.baseline_odometer_km = vehicle.odometer_km
            if task.km_interval and baseline_km is None:
                reminder.due_odometer_km = vehicle.odometer_km + task.km_interval
        if task.auto_create_work_order and reminder.work_order_id is None:
            order = WorkOrder(company_id=vehicle.company_id, vehicle_id=vehicle.id, source="Service Reminder",
                              title=task.title, description=task.description, priority=task.priority, status="Open",
                              expected_completion_date=datetime.combine(due_date, datetime.min.time()) if due_date else None,
                              created_by=user.full_name if user else "System")
            db.add(order)
            db.flush()
            reminder.work_order = order
            audit(db, order, "work_order_created", user)
        elif reminder.work_order and reminder.work_order.status in {"Open", "Assigned"}:
            reminder.work_order.expected_completion_date = datetime.combine(due_date, datetime.min.time()) if due_date else None
            reminder.work_order.priority = task.priority
        refresh_alert(db, reminder, today)
    db.flush()
    return assignment


def synchronize_all(db, user=None, today=None, vehicle_ids=None):
    query = db.query(Vehicle)
    if vehicle_ids is not None:
        query = query.filter(Vehicle.id.in_(vehicle_ids))
    for vehicle in query.order_by(Vehicle.id).all():
        synchronize_vehicle(db, vehicle, user, today)


def matching_task(db, vehicle, service_type):
    rule = winning_rule(db, vehicle)
    if not rule or vehicle.archived:
        return None
    return db.query(ServiceProgramTask).filter(
        ServiceProgramTask.program_id == rule.program_id, ServiceProgramTask.company_id == vehicle.company_id,
        ServiceProgramTask.is_active.is_(True),
        func.lower(func.trim(ServiceProgramTask.service_type)) == service_type.strip().lower()).first()


# Track at flush boundaries too: service and assignment endpoints frequently
# flush before commit. The scheduler runs in the same atomic transaction.
@event.listens_for(Session, "after_flush")
def track_program_changes(db, _context):
    if db.info.get("program_sync_running"):
        return
    changed = [row for row in db.new.union(db.dirty).union(db.deleted)
               if isinstance(row, (Vehicle, Driver, VehicleAssignment, VehicleService))]
    if changed:
        db.info["program_sync_pending"] = True
        ids = db.info.setdefault("program_sync_vehicle_ids", set())
        for row in changed:
            if isinstance(row, (Driver, VehicleAssignment)):
                # Driver/assignment changes can affect previous and new vehicles.
                db.info["program_sync_all"] = True
            else:
                ids.add(row.id if isinstance(row, Vehicle) else row.vehicle_id)
                if isinstance(row, VehicleService):
                    ids.update(inspect(row).attrs.vehicle_id.history.deleted)


@event.listens_for(Session, "before_commit")
def sync_program_changes(db):
    if db.info.get("program_sync_running"):
        return
    db.flush()
    if not db.info.pop("program_sync_pending", False):
        return
    db.info["program_sync_running"] = True
    try:
        ids = db.info.pop("program_sync_vehicle_ids", set())
        all_vehicles = db.info.pop("program_sync_all", False)
        if db.query(ServiceProgramRule.id).first():
            user = db.query(User).execution_options(skip_tenant_scope=True).filter(User.id == db.info["user_id"]).first() if db.info.get("user_id") else None
            synchronize_all(db, user, vehicle_ids=None if all_vehicles else ids)
    finally:
        db.info.pop("program_sync_running", None)


@event.listens_for(Session, "after_rollback")
def clear_program_changes(db):
    for key in ("program_sync_pending", "program_sync_vehicle_ids", "program_sync_all"):
        db.info.pop(key, None)
