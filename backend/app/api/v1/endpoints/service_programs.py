from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.authorization import authorization_scope, has_permission, require_permission
from app.db.session import get_db
from app.models import (Department, Driver, Location, ServiceProgram, ServiceProgramReminder,
                        ServiceProgramRule, ServiceProgramTask, User, Vehicle, VehicleAssignment, VehicleServiceProgram)
from app.program_schemas import ProgramIn, ProgramRuleIn, ProgramTaskIn
from app.services.audit import snapshot
from app.services.service_programs import audit, fail, reminder_status, synchronize_all

router = APIRouter(dependencies=[Depends(require_permission("maintenance.view"))])
WRITE = require_permission("maintenance.assign_work_order")


def get_row(db, model, row_id):
    # Query instead of Session.get: tenant criteria must apply even if another
    # company's object was previously loaded into this identity map.
    row = db.query(model).filter(model.id == row_id).first()
    if not row:
        fail("program_not_found", 404)
    return row


def ensure_global_scope(db, user):
    if not authorization_scope(db, user, "maintenance.assign_work_order").unrestricted:
        fail("program_global_scope", 403)


def visible_vehicles(db, user, permission="maintenance.view"):
    scope = authorization_scope(db, user, permission)
    query = db.query(Vehicle)
    if scope.unrestricted:
        return query
    from sqlalchemy import or_
    conditions = []
    if scope.location_ids:
        conditions.append(Vehicle.location_id.in_(scope.location_ids))
    if scope.department_ids or scope.own_records_only:
        drivers = db.query(Driver.id)
        driver_conditions = []
        if scope.department_ids:
            driver_conditions.append(Driver.department_id.in_(scope.department_ids))
        if scope.own_records_only:
            driver_conditions.append(Driver.user_id == user.id)
        drivers = drivers.filter(or_(*driver_conditions), Driver.archived.is_(False))
        assignments = db.query(VehicleAssignment.vehicle_id).filter(
            VehicleAssignment.driver_id.in_(drivers), VehicleAssignment.archived.is_(False),
            VehicleAssignment.status.in_(["Active", "Overdue"]))
        legacy = db.query(Driver.assigned_vehicle_id).filter(Driver.id.in_(drivers))
        conditions.extend([Vehicle.id.in_(assignments), Vehicle.id.in_(legacy)])
    return query.filter(or_(*conditions) if conditions else False)


def finish(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail("program_conflict", 409)


def program_out(row):
    return {**snapshot(row), "tasks": [snapshot(task) for task in row.tasks]}


@router.get("")
def list_programs(include_archived: bool = False, db: Session = Depends(get_db)):
    query = db.query(ServiceProgram)
    if not include_archived:
        query = query.filter(ServiceProgram.archived.is_(False))
    return [program_out(row) for row in query.order_by(ServiceProgram.name).all()]


@router.post("")
def create_program(payload: ProgramIn, db: Session = Depends(get_db), user: User = Depends(WRITE)):
    ensure_global_scope(db, user)
    if db.query(ServiceProgram).filter(func.lower(ServiceProgram.name) == payload.name.lower()).first():
        fail("program_conflict", 409)
    row = ServiceProgram(**payload.model_dump())
    db.add(row)
    db.flush()
    audit(db, row, "created", user)
    finish(db)
    return program_out(row)


@router.get("/rules")
def list_rules(db: Session = Depends(get_db), user: User = Depends(require_permission("maintenance.view"))):
    ids = {str(v.id) for v in visible_vehicles(db, user).all()}
    return [snapshot(r) for r in db.query(ServiceProgramRule).order_by(ServiceProgramRule.id.desc()).all()
            if r.target_type != "Vehicle" or r.target_value in ids]


def validate_rule(db, payload, user):
    program = get_row(db, ServiceProgram, payload.program_id)
    if program.archived or not program.is_active:
        fail("program_inactive", 409)
    if payload.target_type == "Vehicle":
        vehicle = visible_vehicles(db, user, "maintenance.assign_work_order").filter(Vehicle.id == int(payload.target_value)).first()
        if not vehicle:
            fail("program_not_found", 404)
        if vehicle.archived:
            fail("program_inactive", 409)
    else:
        ensure_global_scope(db, user)
    if payload.target_type in {"Location", "Department"}:
        target = get_row(db, Location if payload.target_type == "Location" else Department, int(payload.target_value))
        if not target.is_active:
            fail("program_inactive", 409)
    return program


def assign_rule(db, payload, user):
    validate_rule(db, payload, user)
    # Repeat requests are idempotent, including the legacy bulk adapter.
    query = db.query(ServiceProgramRule).filter(
        ServiceProgramRule.program_id == payload.program_id,
        ServiceProgramRule.target_type == payload.target_type,
        func.lower(ServiceProgramRule.target_value) == payload.target_value.lower(),
        ServiceProgramRule.model == payload.model, ServiceProgramRule.effective_from == payload.effective_from,
        ServiceProgramRule.is_active == payload.is_active)
    row = query.first()
    if row:
        # Re-selecting an older rule is an explicit priority change; a retry
        # remains stable when it already wins within the same selector.
        newer = db.query(ServiceProgramRule).filter(
            ServiceProgramRule.target_type == row.target_type,
            func.lower(ServiceProgramRule.target_value) == row.target_value.lower(),
            ServiceProgramRule.model == row.model, ServiceProgramRule.is_active.is_(True),
            ServiceProgramRule.created_at > row.created_at).first()
        if newer:
            row.created_at = datetime.utcnow()
            audit(db, row, "rule_updated", user)
            db.flush()
        return row
    row = ServiceProgramRule(**payload.model_dump(), assigned_by=user.id)
    db.add(row)
    db.flush()
    audit(db, row, "rule_created", user)
    return row


@router.post("/rules")
def create_rule(payload: ProgramRuleIn, db: Session = Depends(get_db), user: User = Depends(WRITE)):
    row = assign_rule(db, payload, user)
    synchronize_all(db, user)
    finish(db)
    return snapshot(row)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, payload: ProgramRuleIn, db: Session = Depends(get_db), user: User = Depends(WRITE)):
    row = get_row(db, ServiceProgramRule, rule_id)
    # Authorize both the old and new selection, preventing scoped rule theft.
    validate_rule(db, ProgramRuleIn(**{k: getattr(row, k) for k in ProgramRuleIn.model_fields}), user)
    validate_rule(db, payload, user)
    old = snapshot(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    audit(db, row, "rule_updated", user, old)
    db.flush()
    synchronize_all(db, user)
    finish(db)
    return snapshot(row)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(WRITE)):
    row = get_row(db, ServiceProgramRule, rule_id)
    if row.target_type != "Vehicle":
        ensure_global_scope(db, user)
    elif not visible_vehicles(db, user, "maintenance.assign_work_order").filter(Vehicle.id == int(row.target_value)).first():
        fail("program_not_found", 404)
    row.is_active = False
    audit(db, row, "rule_updated", user)
    db.flush()
    synchronize_all(db, user)
    finish(db)
    return snapshot(row)


@router.get("/assignments")
def list_assignments(include_history: bool = False, db: Session = Depends(get_db), user: User = Depends(require_permission("maintenance.view"))):
    ids = [v.id for v in visible_vehicles(db, user).all()]
    query = db.query(VehicleServiceProgram).filter(VehicleServiceProgram.vehicle_id.in_(ids))
    if not include_history:
        query = query.filter(VehicleServiceProgram.is_active.is_(True))
    return [snapshot(row) for row in query.order_by(VehicleServiceProgram.id.desc()).all()]


@router.get("/options")
def options(db: Session = Depends(get_db), user: User = Depends(require_permission("maintenance.view"))):
    vehicles = visible_vehicles(db, user).filter(Vehicle.archived.is_(False)).all()
    return {
        "vehicles": [{"id": v.id, "name": f"{v.license_plate} · {v.brand} {v.model}"} for v in vehicles],
        "brands": sorted({v.brand for v in vehicles}),
        "models": [{"brand": v.brand, "model": v.model} for v in vehicles],
        "fuel_types": sorted({v.fuel_type for v in vehicles}),
        "categories": sorted({v.vehicle_category for v in vehicles if v.vehicle_category}),
        "locations": [{"id": r.id, "name": r.name} for r in db.query(Location).filter(Location.is_active.is_(True)).all()],
        "departments": [{"id": r.id, "name": r.name} for r in db.query(Department).filter(Department.is_active.is_(True)).all()],
    }


def reminder_out(row, today=None):
    return {**snapshot(row), "title": row.task.title, "service_type": row.task.service_type,
            "priority": row.task.priority, "whichever_occurs_first": row.task.whichever_occurs_first,
            "license_plate": row.vehicle.license_plate, "status": reminder_status(row, today)}


def compliance_data(db, vehicles, today=None):
    ids = [v.id for v in vehicles]
    assignments = {a.vehicle_id: a for a in db.query(VehicleServiceProgram).filter(
        VehicleServiceProgram.vehicle_id.in_(ids), VehicleServiceProgram.is_active.is_(True)).all()}
    reminders = db.query(ServiceProgramReminder).filter(ServiceProgramReminder.vehicle_id.in_(ids),
                                                      ServiceProgramReminder.is_active.is_(True)).all()
    items = [reminder_out(r, today) for r in reminders]
    counts = {status: sum(r["status"] == status for r in items)
              for status in ["Current", "Due Soon", "Due", "Overdue", "Needs Baseline"]}
    covered = len(assignments)
    return {"vehicles_with_program": covered, "vehicles_without_program": len(ids) - covered,
            "tasks_current": counts["Current"], "tasks_due_soon": counts["Due Soon"] + counts["Due"],
            "tasks_overdue": counts["Overdue"], "tasks_needing_baseline": counts["Needs Baseline"],
            "compliance_percent": round(100 * (counts["Current"] + counts["Due Soon"]) / len(items), 1) if items else None,
            "coverage_percent": round(100 * covered / len(ids), 1) if ids else None,
            "items": items, "vehicles": [{"vehicle_id": v.id, "license_plate": v.license_plate,
                "assignment": snapshot(assignments[v.id]) if v.id in assignments else None,
                "program_name": assignments[v.id].program.name if v.id in assignments else None} for v in vehicles]}


@router.get("/compliance")
def compliance(vehicle_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(require_permission("maintenance.view"))):
    query = visible_vehicles(db, user).filter(Vehicle.archived.is_(False))
    if vehicle_id is not None:
        query = query.filter(Vehicle.id == vehicle_id)
        if not query.first():
            fail("program_not_found", 404)
    return compliance_data(db, query.order_by(Vehicle.id).all())


@router.post("/synchronize")
def synchronize(db: Session = Depends(get_db), user: User = Depends(WRITE)):
    ids = [v.id for v in visible_vehicles(db, user, "maintenance.assign_work_order").all()]
    synchronize_all(db, user, vehicle_ids=ids)
    finish(db)
    return {"vehicles_evaluated": len(ids)}


@router.get("/{program_id}")
def get_program(program_id: int, db: Session = Depends(get_db)):
    return program_out(get_row(db, ServiceProgram, program_id))


@router.put("/{program_id}")
def update_program(program_id: int, payload: ProgramIn, db: Session = Depends(get_db), user: User = Depends(WRITE)):
    ensure_global_scope(db, user)
    row = get_row(db, ServiceProgram, program_id)
    if db.query(ServiceProgram).filter(func.lower(ServiceProgram.name) == payload.name.lower(), ServiceProgram.id != row.id).first():
        fail("program_conflict", 409)
    old = snapshot(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    audit(db, row, "updated", user, old)
    db.flush()
    synchronize_all(db, user)
    finish(db)
    return program_out(row)


@router.delete("/{program_id}")
@router.put("/{program_id}/archive")
def archive_program(program_id: int, db: Session = Depends(get_db), user: User = Depends(WRITE)):
    ensure_global_scope(db, user)
    row = get_row(db, ServiceProgram, program_id)
    row.archived = True
    audit(db, row, "archived", user)
    db.flush()
    synchronize_all(db, user)
    finish(db)
    return program_out(row)


@router.post("/{program_id}/restore")
def restore_program(program_id: int, db: Session = Depends(get_db), user: User = Depends(WRITE)):
    ensure_global_scope(db, user)
    row = get_row(db, ServiceProgram, program_id)
    row.archived = False
    audit(db, row, "restored", user)
    db.flush()
    synchronize_all(db, user)
    finish(db)
    return program_out(row)


@router.get("/{program_id}/tasks")
def list_tasks(program_id: int, db: Session = Depends(get_db)):
    return program_out(get_row(db, ServiceProgram, program_id))["tasks"]


def save_task(db, program_id, payload, user, task_id=None):
    ensure_global_scope(db, user)
    program = get_row(db, ServiceProgram, program_id)
    if program.archived:
        fail("program_inactive", 409)
    row = get_row(db, ServiceProgramTask, task_id) if task_id else ServiceProgramTask(program_id=program_id)
    if row.program_id != program_id:
        fail("program_not_found", 404)
    if payload.auto_create_work_order and not has_permission(db, user, "maintenance.create_work_order"):
        fail("permission_denied", 403)
    conflict = db.query(ServiceProgramTask).filter(ServiceProgramTask.program_id == program_id,
        func.lower(func.trim(ServiceProgramTask.service_type)) == payload.service_type.lower())
    if task_id:
        conflict = conflict.filter(ServiceProgramTask.id != task_id)
    if conflict.first():
        fail("program_task_conflict", 409)
    # A task with history retains its identity. Rename its title freely; change
    # service type by deactivating it and adding a new task.
    if task_id and row.service_type.casefold() != payload.service_type.casefold() and db.query(ServiceProgramReminder.id).filter(ServiceProgramReminder.task_id == row.id).first():
        fail("program_task_history", 409)
    old = snapshot(row) if task_id else None
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    db.add(row)
    db.flush()
    audit(db, row, "task_updated" if task_id else "task_created", user, old)
    synchronize_all(db, user)
    finish(db)
    return snapshot(row)


@router.post("/{program_id}/tasks")
def create_task(program_id: int, payload: ProgramTaskIn, db: Session = Depends(get_db), user: User = Depends(WRITE)):
    return save_task(db, program_id, payload, user)


@router.put("/{program_id}/tasks/{task_id}")
def update_task(program_id: int, task_id: int, payload: ProgramTaskIn, db: Session = Depends(get_db), user: User = Depends(WRITE)):
    return save_task(db, program_id, payload, user, task_id)


@router.delete("/{program_id}/tasks/{task_id}")
def delete_task(program_id: int, task_id: int, db: Session = Depends(get_db), user: User = Depends(WRITE)):
    row = get_row(db, ServiceProgramTask, task_id)
    values = {k: getattr(row, k) for k in ProgramTaskIn.model_fields}
    values["is_active"] = False
    return save_task(db, program_id, ProgramTaskIn(**values), user, task_id)
