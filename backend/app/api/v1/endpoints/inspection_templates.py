from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.authorization import authorization_scope, require_permission
from app.db.session import get_db
from app.models import (Department, InspectionSchedule, InspectionTemplate, InspectionTemplateAssignment,
                        InspectionTemplateItem, Location, User, Vehicle)
from app.inspection_template_schemas import AssignmentIn, CATEGORIES, ReorderIn, ScheduleIn, TemplateIn, TemplateItemIn
from app.schemas import InspectionType
from app.services.audit import snapshot
from app.services.inspection_templates import audit, fail, generate_scheduled, get_row, resolve_template

router = APIRouter(dependencies=[Depends(require_permission("inspections.view"))])


def manager(db: Session = Depends(get_db), user: User = Depends(require_permission("inspection_templates.manage"))):
    if not authorization_scope(db, user, "inspection_templates.manage").unrestricted:
        fail("insufficient_permissions", 403)
    return user


def finish(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail("inspection_template_conflict", 409)


def template_out(row):
    return {**snapshot(row), "items": [snapshot(i) for i in row.items]}


def editable(db, template_id):
    row = get_row(db, InspectionTemplate, template_id)
    if row.archived:
        fail("record_archived", 409)
    return row


def save(db, row, payload, user):
    values = payload.model_dump(mode="python")
    if "code" in values:
        values["code"] = values["code"].upper()
        query = db.query(type(row)).filter(func.upper(type(row).code) == values["code"])
        if isinstance(row, InspectionTemplateItem):
            query = query.filter(InspectionTemplateItem.template_id == row.template_id)
        if row.id:
            query = query.filter(type(row).id != row.id)
        if query.first():
            fail("inspection_template_conflict", 409)
    for key, value in values.items():
        setattr(row, key, value.value if hasattr(value, "value") else value)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        fail("inspection_template_conflict", 409)
    audit(db, row, "saved", user)
    finish(db)
    return row


@router.get("")
def list_templates(include_archived: bool = False, db: Session = Depends(get_db)):
    query = db.query(InspectionTemplate)
    if not include_archived:
        query = query.filter(InspectionTemplate.archived.is_(False))
    return [template_out(row) for row in query.order_by(InspectionTemplate.name).all()]


@router.get("/options")
def options(db: Session = Depends(get_db), user: User = Depends(manager)):
    vehicles = db.query(Vehicle).filter(Vehicle.archived.is_(False)).all()
    return {"categories": CATEGORIES, "vehicles": [{"id": v.id, "name": v.license_plate} for v in vehicles],
        "vehicle_categories": sorted({v.vehicle_category for v in vehicles if v.vehicle_category}),
        "fuel_types": sorted({v.fuel_type for v in vehicles}),
        "brands": sorted({v.brand for v in vehicles}),
        "models": [{"brand": v.brand, "model": v.model} for v in vehicles],
        "locations": [snapshot(r) for r in db.query(Location).filter(Location.is_active.is_(True)).all()],
        "departments": [snapshot(r) for r in db.query(Department).filter(Department.is_active.is_(True)).all()]}


@router.get("/resolve")
def resolve(vehicle_id: int, inspection_type: InspectionType, driver_id: int | None = None, db: Session = Depends(get_db)):
    vehicle = get_row(db, Vehicle, vehicle_id)
    if driver_id:
        from app.models import Driver
        get_row(db, Driver, driver_id)
    row = resolve_template(db, vehicle, inspection_type.value, driver_id)
    if row is None:
        return None
    result = template_out(row)
    result["items"] = [i for i in result["items"] if i["is_active"]]
    return result


@router.post("/generate")
def generate(db: Session = Depends(get_db), user: User = Depends(manager)):
    rows = generate_scheduled(db)
    finish(db)
    return {"inspection_ids": [r.id for r in rows]}


@router.post("", status_code=201)
def create_template(payload: TemplateIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    return template_out(save(db, InspectionTemplate(), payload, user))


@router.get("/{template_id}")
@router.get("/{template_id}/preview")
def get_template(template_id: int, db: Session = Depends(get_db)):
    return template_out(get_row(db, InspectionTemplate, template_id))


@router.put("/{template_id}")
def update_template(template_id: int, payload: TemplateIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    return template_out(save(db, editable(db, template_id), payload, user))


@router.post("/{template_id}/duplicate", status_code=201)
def duplicate_template(template_id: int, payload: TemplateIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    source = get_row(db, InspectionTemplate, template_id)
    if db.query(InspectionTemplate).filter(func.upper(InspectionTemplate.code) == payload.code.upper()).first():
        fail("inspection_template_conflict", 409)
    row = InspectionTemplate(**payload.model_dump(), archived=False)
    row.code = row.code.upper()
    row.items = [InspectionTemplateItem(**{k: getattr(item, k) for k in TemplateItemIn.model_fields}) for item in source.items]
    db.add(row)
    db.flush()
    audit(db, row, "duplicated", user)
    finish(db)
    return template_out(row)


@router.delete("/{template_id}")
@router.put("/{template_id}/archive")
def archive_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(manager)):
    row = get_row(db, InspectionTemplate, template_id)
    row.archived = True
    audit(db, row, "archived", user)
    finish(db)
    return template_out(row)


@router.post("/{template_id}/restore")
def restore_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(manager)):
    row = get_row(db, InspectionTemplate, template_id)
    row.archived = False
    audit(db, row, "restored", user)
    finish(db)
    return template_out(row)


@router.get("/{template_id}/items")
def list_items(template_id: int, db: Session = Depends(get_db)):
    return template_out(get_row(db, InspectionTemplate, template_id))["items"]


@router.post("/{template_id}/items", status_code=201)
def create_item(template_id: int, payload: TemplateItemIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    editable(db, template_id)
    return snapshot(save(db, InspectionTemplateItem(template_id=template_id), payload, user))


def child(db, model, template_id, row_id):
    editable(db, template_id)
    row = get_row(db, model, row_id)
    if row.template_id != template_id:
        fail("inspection_template_missing", 404)
    return row


@router.put("/{template_id}/items/reorder")
def reorder_items(template_id: int, payload: ReorderIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    row = editable(db, template_id)
    if len(payload.item_ids) != len(set(payload.item_ids)) or set(payload.item_ids) != {i.id for i in row.items}:
        fail("inspection_reorder_invalid")
    positions = {item_id: index for index, item_id in enumerate(payload.item_ids)}
    for item in row.items:
        item.display_order = positions[item.id]
    row.updated_at = datetime.utcnow()
    audit(db, row, "reordered", user)
    finish(db)
    return template_out(row)


@router.put("/{template_id}/items/{item_id}")
def update_item(template_id: int, item_id: int, payload: TemplateItemIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    return snapshot(save(db, child(db, InspectionTemplateItem, template_id, item_id), payload, user))


@router.delete("/{template_id}/items/{item_id}")
def delete_item(template_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(manager)):
    row = child(db, InspectionTemplateItem, template_id, item_id)
    audit(db, row, "item_deleted", user)
    # Snapshots retain the source ID as metadata, intentionally without a live FK.
    db.delete(row)
    finish(db)
    return {"deleted": True}


def validate_assignment(db, payload):
    models = {"Vehicle": Vehicle, "Location": Location, "Department": Department}
    if payload.target_type in models:
        target = get_row(db, models[payload.target_type], int(payload.target_value))
        if getattr(target, "archived", False) or not getattr(target, "is_active", True):
            fail("record_archived", 409)


@router.get("/{template_id}/assignments")
def list_assignments(template_id: int, db: Session = Depends(get_db)):
    get_row(db, InspectionTemplate, template_id)
    return [snapshot(r) for r in db.query(InspectionTemplateAssignment).filter(InspectionTemplateAssignment.template_id == template_id).all()]


@router.post("/{template_id}/assignments", status_code=201)
def create_assignment(template_id: int, payload: AssignmentIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    editable(db, template_id)
    validate_assignment(db, payload)
    return snapshot(save(db, InspectionTemplateAssignment(template_id=template_id), payload, user))


@router.put("/{template_id}/assignments/{assignment_id}")
def update_assignment(template_id: int, assignment_id: int, payload: AssignmentIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    row = child(db, InspectionTemplateAssignment, template_id, assignment_id)
    validate_assignment(db, payload)
    return snapshot(save(db, row, payload, user))


@router.delete("/{template_id}/assignments/{assignment_id}")
def delete_assignment(template_id: int, assignment_id: int, db: Session = Depends(get_db), user: User = Depends(manager)):
    row = child(db, InspectionTemplateAssignment, template_id, assignment_id)
    row.is_active = False
    audit(db, row, "unassigned", user)
    finish(db)
    return snapshot(row)


@router.get("/{template_id}/schedules")
def list_schedules(template_id: int, db: Session = Depends(get_db)):
    get_row(db, InspectionTemplate, template_id)
    return [snapshot(r) for r in db.query(InspectionSchedule).filter(InspectionSchedule.template_id == template_id).all()]


@router.post("/{template_id}/schedules", status_code=201)
def create_schedule(template_id: int, payload: ScheduleIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    editable(db, template_id)
    return snapshot(save(db, InspectionSchedule(template_id=template_id), payload, user))


@router.put("/{template_id}/schedules/{schedule_id}")
def update_schedule(template_id: int, schedule_id: int, payload: ScheduleIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    return snapshot(save(db, child(db, InspectionSchedule, template_id, schedule_id), payload, user))


@router.delete("/{template_id}/schedules/{schedule_id}")
def delete_schedule(template_id: int, schedule_id: int, db: Session = Depends(get_db), user: User = Depends(manager)):
    row = child(db, InspectionSchedule, template_id, schedule_id)
    row.is_active = False
    audit(db, row, "schedule_disabled", user)
    finish(db)
    return snapshot(row)
