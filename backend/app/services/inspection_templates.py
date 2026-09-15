"""Inspection policy resolution, immutable snapshots and idempotent automation.

No operation here rewrites legacy inspections or refreshes an existing snapshot.
All mutations belong to the caller's transaction.
"""
from datetime import datetime, time, timedelta
from calendar import monthrange

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.core.authorization import has_permission

from app.models import (Attachment, Driver, Inspection, InspectionItem, InspectionSchedule,
                        InspectionTemplate, InspectionTemplateAssignment, Vehicle, VehicleAssignment, WorkOrder)
from app.services.audit import record_audit, snapshot
from app.services.notifications import notify_roles, resolve_by_prefix
from app.services.service_programs import departments

PRECEDENCE = {"Vehicle": 60, "BrandModel": 50, "Category": 40, "FuelType": 30, "Location": 20, "Department": 10}


def fail(code, status=422, **params):
    raise HTTPException(status_code=status, detail={"code": code, "params": params})


def get_row(db, model, row_id):
    row = db.query(model).filter(model.id == row_id).first()
    if row is None:
        fail("inspection_template_missing", 404)
    return row


def audit(db, row, action, user=None):
    record_audit(db, action=f"Inspection template {action}", action_code="inspection_template_change",
                 entity_type=type(row).__name__, entity_id=row.id, user=user, new_values=snapshot(row),
                 description_key="modules:inspectionTemplates.audit", description_params={"id": row.id})


def resolve_template(db, vehicle, inspection_type, driver_id=None):
    rules = db.query(InspectionTemplateAssignment).join(InspectionTemplateAssignment.template).filter(
        InspectionTemplateAssignment.company_id == vehicle.company_id,
        InspectionTemplateAssignment.is_active.is_(True), InspectionTemplate.company_id == vehicle.company_id,
        InspectionTemplate.is_active.is_(True), InspectionTemplate.archived.is_(False),
        InspectionTemplate.inspection_type == inspection_type).all()
    department_ids = departments(db, vehicle)
    if driver_id:
        driver = db.query(Driver).filter(Driver.id == driver_id, Driver.company_id == vehicle.company_id).first()
        department_ids = {str(driver.department_id)} if driver and driver.department_id else set()
    values = {"Vehicle": str(vehicle.id), "Category": vehicle.vehicle_category, "FuelType": vehicle.fuel_type,
              "Location": str(vehicle.location_id)}
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
    winner = max(matches, key=lambda r: (PRECEDENCE[r.target_type], bool(r.model), r.priority, -r.id), default=None)
    return winner.template if winner else None


def copy_template(inspection, template):
    if inspection.template_snapshot is not None:
        fail("inspection_snapshot_locked", 409)
    active = [item for item in template.items if item.is_active and item.company_id == template.company_id]
    if not active:
        fail("inspection_template_empty", 409)
    inspection.template_id = template.id
    inspection.template_snapshot = {k: getattr(template, k) for k in ("id", "code", "name", "description", "inspection_type")}
    inspection.items = [InspectionItem(
        company_id=template.company_id, item_name=item.name, template_item_id=item.id,
        item_snapshot={k: v for k, v in snapshot(item).items() if k not in {"company_id", "template_id"}},
        status="Not Checked", photo_attachment_ids=[],
    ) for item in sorted(active, key=lambda i: (i.display_order, i.id))]


def can_record_results(db, user, inspection):
    if has_permission(db, user, "inspections.manage"):
        return True
    if not inspection.template_snapshot or not has_permission(db, user, "inspections.create"):
        return False
    if inspection.created_by_user_id == user.id:
        return True
    return inspection.driver_id is not None and db.query(Driver).filter(
        Driver.id == inspection.driver_id, Driver.user_id == user.id,
        Driver.company_id == inspection.company_id, Driver.archived.is_(False)).first() is not None


def validate_results(db, inspection, results, *, completing=False):
    """Validate the entire submission before mutating results or firing automation."""
    if inspection.completed_at:
        fail("inspection_completed_locked", 409)
    by_id = {item.id: item for item in inspection.items}
    submitted = {}
    for result in results:
        item = by_id.get(result.id)
        if item is None or result.id in submitted:
            fail("inspection_snapshot_locked", 409)
        if result.item_name != item.item_name:
            fail("inspection_snapshot_locked", 409)
        submitted[result.id] = result
    if set(submitted) != set(by_id):
        fail("inspection_snapshot_locked", 409)
    for item_id, result in submitted.items():
        item = by_id[item_id]
        policy = item.item_snapshot or {}
        if completing and policy.get("required") and result.status.value == "Not Checked":
            fail("inspection_required_item", item=item.item_name)
        if result.status.value == "Fail":
            if policy.get("comment_required_on_failure") and not (result.comment or "").strip():
                fail("inspection_comment_required", item=item.item_name)
            if policy.get("photo_required_on_failure") and not result.photo_attachment_ids:
                fail("inspection_photo_required", item=item.item_name)
        for photo_id in result.photo_attachment_ids:
            photo = db.query(Attachment).filter(Attachment.id == photo_id, Attachment.company_id == inspection.company_id,
                Attachment.entity_type == "Inspection", Attachment.entity_id == inspection.id,
                Attachment.archived.is_(False), Attachment.mime_type.in_(["image/jpeg", "image/png", "image/webp", "image/gif"])).first()
            if not photo:
                fail("inspection_photo_required", item=item.item_name)
    for item_id, result in submitted.items():
        item = by_id[item_id]
        item.status = result.status.value
        item.comment = result.comment
        item.photo_attachment_ids = list(dict.fromkeys(result.photo_attachment_ids))
    inspection.overall_status = "Failed" if any(i.status == "Fail" for i in inspection.items) else (
        "Needs Review" if any(i.status == "Not Checked" and (i.item_snapshot or {}).get("required") for i in inspection.items) else "Passed")
    if completing:
        inspection.completed_at = datetime.utcnow()
        resolve_by_prefix(db, f"inspection-required:{inspection.id}:")
    apply_failure_rules(db, inspection)


def apply_failure_rules(db, inspection, user=None):
    db.flush()
    for item in inspection.items:
        policy = item.item_snapshot or {}
        if item.status != "Fail":
            resolve_by_prefix(db, f"inspection-item:{item.id}:")
            continue
        if policy.get("critical"):
            inspection.overall_status = "Failed"
        if policy.get("mark_vehicle_unavailable_on_failure"):
            vehicle = get_row(db, Vehicle, inspection.vehicle_id)
            vehicle.status = 3  # Out of Use; return must not clear this safety state.
        if policy.get("create_work_order_on_failure"):
            existing = db.query(WorkOrder).filter(WorkOrder.inspection_item_id == item.id).first()
            if not existing:
                order = WorkOrder(company_id=inspection.company_id, vehicle_id=inspection.vehicle_id,
                    driver_id=inspection.driver_id, inspection_id=inspection.id, inspection_item_id=item.id,
                    source="Inspection", title=item.item_name, description=item.comment or policy.get("description"),
                    reported_issue=item.comment or item.item_name, priority="Critical" if policy.get("critical") else "High",
                    status="Open", created_by=user.full_name if user else inspection.inspector)
                # The unique item FK also handles concurrent retries, including archived orders.
                try:
                    with db.begin_nested():
                        db.add(order)
                        db.flush()
                except IntegrityError:
                    if not db.query(WorkOrder).filter(WorkOrder.inspection_item_id == item.id).first():
                        raise
                else:
                    audit(db, order, "failure_work_order", user)
        if policy.get("generate_notification_on_failure"):
            notify_roles(db, roles={"admin", "fleet_manager", "mechanic"}, notification_type="Inspection item failed",
                title=f"Inspection #{inspection.id}: {item.item_name}", message=item.comment or item.item_name,
                priority="Critical" if policy.get("critical") else "High", entity_type="Inspection", entity_id=inspection.id,
                deduplication_key=f"inspection-item:{item.id}:failed", message_params={"id": inspection.id, "item": item.item_name})
    db.flush()


def required_notification(db, inspection):
    if inspection.completed_at or inspection.archived:
        return
    notify_roles(db, roles={"admin", "fleet_manager", "mechanic"}, notification_type="Inspection required",
        title=f"Inspection #{inspection.id} required", message=f"{inspection.template_snapshot['name']} · Vehicle #{inspection.vehicle_id}",
        priority="High", entity_type="Inspection", entity_id=inspection.id,
        deduplication_key=f"inspection-required:{inspection.id}:due",
        message_params={"id": inspection.id, "template": inspection.template_snapshot["name"], "vehicle_id": inspection.vehicle_id})


def schedule_occurrence(db, schedule, vehicle, now, assignment=None):
    today = now.date()
    if today < schedule.start_date:
        return None
    frequency = schedule.frequency
    if frequency == "After return":
        return (f"return:{assignment.id}", now) if assignment else None
    if frequency == "Before check-out":
        last = db.query(VehicleAssignment).filter(VehicleAssignment.vehicle_id == vehicle.id,
            VehicleAssignment.company_id == vehicle.company_id, VehicleAssignment.status.in_(["Completed", "Cancelled"])
        ).order_by(VehicleAssignment.id.desc()).first()
        return f"checkout:{last.id if last else 0}:{today.isoformat()}", now
    if frequency == "Mileage":
        if vehicle.odometer_km is None or vehicle.odometer_km < schedule.baseline_odometer_km + schedule.interval_km:
            return None
        step = (vehicle.odometer_km - schedule.baseline_odometer_km) // schedule.interval_km
        return f"km:{schedule.baseline_odometer_km + step * schedule.interval_km}", now
    if frequency == "Monthly":
        months = (today.year - schedule.start_date.year) * 12 + today.month - schedule.start_date.month
        def at_month(offset):
            y, m = divmod(schedule.start_date.year * 12 + schedule.start_date.month - 1 + offset, 12)
            return schedule.start_date.replace(year=y, month=m + 1, day=min(schedule.start_date.day, monthrange(y, m + 1)[1]))
        due = at_month(months)
        if due > today:
            due = at_month(months - 1)
    else:
        days = {"Daily": 1, "Weekly": 7}.get(frequency, schedule.interval_days)
        due = schedule.start_date + timedelta(days=((today - schedule.start_date).days // days) * days)
    return due.isoformat(), datetime.combine(due, time.min)


def generate_scheduled(db, now=None, *, vehicle=None, event=None, assignment=None, driver_id=None):
    now = now or datetime.utcnow()
    schedules = db.query(InspectionSchedule).join(InspectionSchedule.template).filter(
        InspectionSchedule.is_active.is_(True), InspectionTemplate.is_active.is_(True), InspectionTemplate.archived.is_(False)
    ).order_by(InspectionSchedule.id).all()
    vehicles = [vehicle] if vehicle else db.query(Vehicle).filter(Vehicle.archived.is_(False), Vehicle.status.notin_([2])).all()
    rows = []
    for v in vehicles:
        for schedule in schedules:
            if schedule.company_id != v.company_id or schedule.template.company_id != v.company_id:
                continue
            if event is not None and schedule.frequency != event:
                continue
            if event is None and schedule.frequency == "After return":
                continue
            if schedule.frequency == "Before check-out" and event is None and v.status != 0:
                continue
            template = resolve_template(db, v, schedule.template.inspection_type, driver_id or (assignment.driver_id if assignment else None))
            if template is None or template.id != schedule.template_id:
                continue
            if not any(i.is_active for i in template.items):
                if event == "Before check-out":
                    fail("inspection_template_empty", 409)
                continue
            occurrence = schedule_occurrence(db, schedule, v, now, assignment)
            if occurrence is None:
                continue
            token, due = occurrence
            key = f"schedule:{schedule.id}:vehicle:{v.id}:{token}"
            row = db.query(Inspection).filter(Inspection.company_id == v.company_id, Inspection.occurrence_key == key).first()
            if row is None and schedule.frequency not in {"Before check-out", "After return"}:
                # Keep an overdue inspection open instead of generating an unbounded backlog.
                row = db.query(Inspection).filter(Inspection.schedule_id == schedule.id, Inspection.vehicle_id == v.id,
                    Inspection.completed_at.is_(None), Inspection.archived.is_(False)).order_by(Inspection.id).first()
            if schedule.frequency == "Before check-out":
                # A failed completed check can be followed by an explicit recheck.
                # Every retry in the chain retains its own immutable results.
                while row is not None and row.completed_at and row.overall_status != "Passed":
                    key = f"schedule:{schedule.id}:vehicle:{v.id}:recheck:{row.id}"
                    row = db.query(Inspection).filter(Inspection.company_id == v.company_id, Inspection.occurrence_key == key).first()
            if row is None:
                row = Inspection(company_id=v.company_id, vehicle_id=v.id, driver_id=driver_id or (assignment.driver_id if assignment else None),
                    vehicle_assignment_id=assignment.id if assignment else None, inspection_type=template.inspection_type,
                    inspection_date=due, odometer_km=v.odometer_km, schedule_id=schedule.id, occurrence_key=key, overall_status="Needs Review")
                copy_template(row, template)
                try:
                    with db.begin_nested():
                        db.add(row)
                        db.flush()
                except IntegrityError:
                    row = db.query(Inspection).filter(Inspection.company_id == v.company_id, Inspection.occurrence_key == key).first()
                    if row is None:
                        raise
                else:
                    audit(db, row, "scheduled")
            required_notification(db, row)
            rows.append(row)
    db.flush()
    return rows


def require_checkout_inspections(db, vehicle, driver_id, now):
    rows = generate_scheduled(db, now, vehicle=vehicle, event="Before check-out", driver_id=driver_id)
    blocking = [r for r in rows if not r.completed_at or r.overall_status != "Passed" or r.archived
                or r.completed_at.date() != now.date()]
    if blocking:
        # Called only before handover mutations. Persist actionable requirements on rejection.
        db.commit()
        fail("inspection_checkout_required", 409, ids=", ".join(str(r.id) for r in blocking))
