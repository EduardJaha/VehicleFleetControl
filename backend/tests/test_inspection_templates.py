from datetime import date, datetime, timedelta
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from tests.test_service_programs import ctx
from tests.test_vehicle_checkout_return import make_driver, checkout_payload, return_payload
from app.api.v1.endpoints import inspection_templates as api
from app.api.v1.endpoints.inspections import create_inspection, update_inspection
from app.api.v1.endpoints.vehicle_assignments import checkout_vehicle, return_vehicle, start_vehicle_assignment, complete_vehicle_assignment
from app.api.v1.endpoints.files import archive_file
from app.core.security import get_current_user
from app.db.session import get_db, set_tenant_context
from app.main import app
from app.models import (Attachment, Inspection, InspectionItem, InspectionTemplate, InspectionTemplateItem,
                        InspectionTemplateAssignment, InspectionSchedule, Notification, User, Vehicle, VehicleAssignment, WorkOrder)
from app.inspection_template_schemas import TemplateIn, TemplateItemIn, AssignmentIn, ScheduleIn, ReorderIn
from app.schemas import InspectionCreate, InspectionUpdate, InspectionItemCreate, VehicleAssignmentStart, VehicleAssignmentComplete
from app.services.inspection_templates import generate_scheduled, resolve_template, validate_results, schedule_occurrence


def template(ctx, code="DAILY", inspection_type="Daily", **flags):
    db, user, vehicle, *_ = ctx
    row = api.create_template(TemplateIn(code=code, name=code, inspection_type=inspection_type), db, user)
    item = api.create_item(row["id"], TemplateItemIn(code="BRAKES", name="Brakes", category="Brakes", **flags), db, user)
    api.create_assignment(row["id"], AssignmentIn(target_type="Vehicle", target_value=str(vehicle.id)), db, user)
    return db.query(InspectionTemplate).filter_by(id=row["id"]).one(), item


def begin(ctx, row):
    db, user, v, *_ = ctx
    return create_inspection(InspectionCreate(vehicle_id=v.id, inspection_type=row.inspection_type,
        inspection_date="14-09-2026", template_id=row.id), db, user)


def results(out, status="Pass", **changes):
    return [InspectionItemCreate(id=i.id, item_name=i.item_name, status=status, **changes) for i in out.items]


def update(ctx, out, items, complete=False, **changes):
    return update_inspection(out.id, InspectionUpdate(vehicle_id=out.vehicle_id, inspection_type=out.inspection_type,
        inspection_date=out.inspection_date, items=items, complete=complete, **changes), ctx[0], ctx[1])


def test_template_item_crud_duplicate_preview_archive_restore_reordering(ctx):
    db, user, *_ = ctx
    row, item = template(ctx)
    second = api.create_item(row.id, TemplateItemIn(code="TIRES", name="Tires"), db, user)
    api.reorder_items(row.id, ReorderIn(item_ids=[second["id"], item["id"]]), db, user)
    assert [i["code"] for i in api.get_template(row.id, db)["items"]] == ["TIRES", "BRAKES"]
    with pytest.raises(HTTPException):
        api.reorder_items(row.id, ReorderIn(item_ids=[item["id"], item["id"]]), db, user)
    api.update_template(row.id, TemplateIn(code="daily", name="Updated", inspection_type="Daily"), db, user)
    api.update_item(row.id, item["id"], TemplateItemIn(code="BRAKES", name="Brake pads", critical=True, display_order=1), db, user)
    copied = api.duplicate_template(row.id, TemplateIn(code="COPY", name="Copied", inspection_type="Daily"), db, user)
    assert copied["items"][1]["name"] == "Brake pads"
    assert copied["items"][1]["id"] != item["id"]
    assert api.list_assignments(copied["id"], db) == []
    assert api.list_schedules(copied["id"], db) == []
    api.delete_item(row.id, second["id"], db, user)
    assert len(api.get_template(row.id, db)["items"]) == 1
    api.archive_template(row.id, db, user)
    assert row.id not in [r["id"] for r in api.list_templates(False, db)]
    api.restore_template(row.id, db, user)
    assert row.id in [r["id"] for r in api.list_templates(False, db)]
    with pytest.raises(HTTPException):
        api.create_template(TemplateIn(code="daily", name="Conflict", inspection_type="Daily"), db, user)


def test_assignment_precedence_specificity_priority_and_stable_tie(ctx):
    db, user, vehicle, location, department = ctx
    driver = make_driver(db, 1); driver.department_id = department.id; driver.assigned_vehicle_id = vehicle.id; db.commit()
    rules = []
    targets = [("Department", str(department.id), None), ("Location", str(location.id), None),
               ("FuelType", "diesel", None), ("Category", "Passenger", None), ("BrandModel", "VW", None),
               ("BrandModel", "vw", "golf"), ("Vehicle", str(vehicle.id), None)]
    for index, (kind, value, model) in enumerate(targets):
        row = api.create_template(TemplateIn(code=f"T{index}", name=f"T{index}", inspection_type="Daily"), db, user)
        rule = api.create_assignment(row["id"], AssignmentIn(target_type=kind, target_value=value, model=model), db, user)
        rules.append(rule)
        assert resolve_template(db, vehicle, "Daily").id == row["id"]
    winner = resolve_template(db, vehicle, "Daily")
    newer = api.create_template(TemplateIn(code="TIE", name="Tie", inspection_type="Daily"), db, user)
    tie = api.create_assignment(newer["id"], AssignmentIn(target_type="Vehicle", target_value=str(vehicle.id)), db, user)
    assert resolve_template(db, vehicle, "Daily").id == winner.id
    api.update_assignment(newer["id"], tie["id"], AssignmentIn(target_type="Vehicle", target_value=str(vehicle.id), priority=5), db, user)
    assert resolve_template(db, vehicle, "Daily").id == newer["id"]
    api.delete_assignment(newer["id"], tie["id"], db, user)
    for rule in reversed(rules):
        assert resolve_template(db, vehicle, "Daily").id == rule["template_id"]
        api.delete_assignment(rule["template_id"], rule["id"], db, user)
    assert resolve_template(db, vehicle, "Daily") is None


def test_snapshots_survive_rename_delete_archive_and_completion(ctx):
    db, user, vehicle, *_ = ctx
    # A legacy result remains untouched by configuration operations.
    legacy = create_inspection(InspectionCreate(vehicle_id=vehicle.id, inspection_type="Daily", inspection_date="01-01-2020",
        items=[InspectionItemCreate(item_name="Historical brake label", status="Fail")]), db, user)
    row, item = template(ctx, critical=True, photo_required_on_failure=True)
    original = begin(ctx, row)
    saved_metadata = original.items[0].item_snapshot.copy()
    api.update_item(row.id, item["id"], TemplateItemIn(code="OTHER", name="Renamed", required=False), db, user)
    api.delete_item(row.id, item["id"], db, user)
    api.archive_template(row.id, db, user)
    record = db.query(Inspection).filter_by(id=original.id).one()
    assert record.items[0].item_snapshot == saved_metadata
    assert record.items[0].item_name == "Brakes"
    assert db.query(InspectionItem).filter_by(inspection_id=legacy.id).one().item_name == "Historical brake label"
    assert db.query(Inspection).filter_by(id=legacy.id).one().template_id is None
    completed = update(ctx, original, results(original), complete=True)
    assert completed.completed_at and completed.overall_status == "Passed"
    with pytest.raises(HTTPException) as exc:
        update(ctx, completed, results(completed, "Fail"))
    assert exc.value.detail["code"] == "inspection_completed_locked"


@pytest.mark.parametrize("change", ["omit", "rename", "foreign_id", "duplicate", "vehicle"])
def test_cannot_replace_snapshot_items_or_vehicle(ctx, change):
    row, _ = template(ctx)
    out = begin(ctx, row)
    items = results(out)
    values = {}
    if change == "omit": items = []
    if change == "rename": items[0].item_name = "Different"
    if change == "foreign_id": items[0].id = 9999
    if change == "duplicate": items = items * 2
    if change == "vehicle": values["template_id"] = 999
    with pytest.raises(HTTPException): update(ctx, out, items, **values)


def test_required_items_must_be_checked_and_requested_pass_cannot_override_failure(ctx):
    row, _ = template(ctx, critical=True)
    out = begin(ctx, row)
    with pytest.raises(HTTPException) as exc: update(ctx, out, results(out, "Not Checked"), complete=True)
    assert exc.value.detail["code"] == "inspection_required_item"
    failed = update(ctx, out, results(out, "Fail"), complete=True, overall_status="Passed")
    assert failed.overall_status == "Failed"


def photo(db, out, **changes):
    values = dict(original_filename="brakes.png", stored_filename=f"photo-{out.id}.png", storage_path=f"photos/{out.id}.png",
        mime_type="image/png", file_size=100, entity_type="Inspection", entity_id=out.id)
    values.update(changes)
    attachment = Attachment(**values); db.add(attachment); db.commit(); return attachment


def test_failure_evidence_automation_deduplication_and_vehicle_safety(ctx):
    db, user, vehicle, *_ = ctx
    row, _ = template(ctx, critical=True, photo_required_on_failure=True, comment_required_on_failure=True,
        create_work_order_on_failure=True, mark_vehicle_unavailable_on_failure=True)
    out = begin(ctx, row)
    with pytest.raises(HTTPException) as exc: update(ctx, out, results(out, "Fail"))
    assert exc.value.detail["code"] == "inspection_comment_required"
    with pytest.raises(HTTPException) as exc: update(ctx, out, results(out, "Fail", comment="Cracked"))
    assert exc.value.detail["code"] == "inspection_photo_required"
    assert db.query(WorkOrder).count() == 0 and vehicle.status == 0
    image = photo(db, out)
    failure = results(out, "Fail", comment="Cracked", photo_attachment_ids=[image.id])
    update(ctx, out, failure)
    order = db.query(WorkOrder).one()
    assert order.inspection_item_id == out.items[0].id and order.priority == "Critical"
    assert vehicle.status == 3
    notices = db.query(Notification).filter_by(notification_type="Inspection item failed").count()
    order.archived = True; db.commit()
    update(ctx, out, failure)
    assert db.query(WorkOrder).count() == 1
    assert db.query(Notification).filter_by(notification_type="Inspection item failed").count() == notices
    with pytest.raises(HTTPException): archive_file(image.id, db, user)
    # Automatic reactivation of the vehicle is deliberately not permitted.
    update(ctx, out, results(out, "Pass"))
    assert vehicle.status == 3


@pytest.mark.parametrize("changes", [{"entity_id": 999}, {"mime_type": "application/pdf"}, {"archived": True}, {"entity_type": "WorkOrder"}])
def test_photo_must_be_active_image_owned_by_this_inspection(ctx, changes):
    db = ctx[0]; row, _ = template(ctx, photo_required_on_failure=True); out = begin(ctx, row)
    image = photo(db, out, **changes)
    with pytest.raises(HTTPException): update(ctx, out, results(out, "Fail", photo_attachment_ids=[image.id]))


@pytest.mark.parametrize("frequency,extra,when,expected", [
    ("Daily", {}, datetime(2026, 9, 14), "2026-09-14"),
    ("Weekly", {}, datetime(2026, 9, 14), "2026-09-08"),
    ("Monthly", {}, datetime(2026, 9, 14), "2026-09-01"),
    ("Every X days", {"interval_days": 5}, datetime(2026, 9, 14), "2026-09-11"),
    ("Mileage", {"interval_km": 1000, "baseline_odometer_km": 10000}, datetime(2026, 9, 14), "km:20000"),
])
def test_scheduling_periods_notifications_no_duplicates_and_completion(ctx, frequency, extra, when, expected):
    db, user, vehicle, *_ = ctx
    row, _ = template(ctx)
    api.create_schedule(row.id, ScheduleIn(frequency=frequency, start_date=date(2026, 9, 1), **extra), db, user)
    first = generate_scheduled(db, when); db.commit()
    assert len(first) == 1 and first[0].occurrence_key.endswith(expected)
    assert generate_scheduled(db, when)[0].id == first[0].id
    assert db.query(Inspection).count() == 1
    assert db.query(Notification).filter_by(notification_type="Inspection required").count() == 1
    out = __import__('app.api.v1.endpoints.inspections', fromlist=['inspection_out']).inspection_out(first[0])
    update(ctx, out, results(out), complete=True)
    assert db.query(Notification).filter_by(notification_type="Inspection required").one().status == "Resolved"
    generate_scheduled(db, when); db.commit()
    assert db.query(Notification).filter_by(notification_type="Inspection required").one().status == "Resolved"
    assert db.query(Inspection).count() == 1


def test_month_end_unknown_mileage_future_and_paused_schedules(ctx):
    db, user, v, *_ = ctx
    row, _ = template(ctx)
    schedule = InspectionSchedule(template_id=row.id, frequency="Monthly", start_date=date(2026, 1, 31))
    assert schedule_occurrence(db, schedule, v, datetime(2026, 2, 28))[0] == "2026-02-28"
    assert schedule_occurrence(db, schedule, v, datetime(2026, 3, 30))[0] == "2026-02-28"
    assert schedule_occurrence(db, schedule, v, datetime(2026, 3, 31))[0] == "2026-03-31"
    stored = api.create_schedule(row.id, ScheduleIn(frequency="Mileage", interval_km=1000, baseline_odometer_km=0), db, user)
    v.odometer_km = None; db.commit()
    assert generate_scheduled(db) == []
    api.update_schedule(row.id, stored['id'], ScheduleIn(frequency="Daily", start_date=date(2030,1,1)), db, user)
    assert generate_scheduled(db, datetime(2026,9,14)) == []
    api.delete_schedule(row.id, stored['id'], db, user)
    assert generate_scheduled(db, datetime(2031,1,1)) == []


@pytest.mark.parametrize("kwargs", [{"frequency":"Every X days"}, {"frequency":"Mileage", "interval_km":1000}, {"frequency":"Daily", "interval_days":5}, {"frequency":"Every X days", "interval_days":0}])
def test_schedule_validation(kwargs):
    with pytest.raises(ValidationError): ScheduleIn(**kwargs)


def test_checkout_requires_passed_inspection_and_return_creates_snapshots(ctx):
    db, user, vehicle, *_ = ctx
    driver = make_driver(db, 2)
    pre, _ = template(ctx, code="PRE", inspection_type="Before Trip")
    post, _ = template(ctx, code="RETURN", inspection_type="Return Inspection")
    api.create_schedule(pre.id, ScheduleIn(frequency="Before check-out"), db, user)
    api.create_schedule(post.id, ScheduleIn(frequency="After return"), db, user)
    with pytest.raises(HTTPException) as exc: checkout_vehicle(checkout_payload(vehicle, driver), db, user)
    assert exc.value.detail['code'] == 'inspection_checkout_required'
    assert db.query(VehicleAssignment).count() == 0
    required = db.query(Inspection).one()
    from app.api.v1.endpoints.inspections import inspection_out
    out = inspection_out(required)
    update(ctx, out, results(out), complete=True)
    checkout = checkout_vehicle(checkout_payload(vehicle, driver), db, user)
    assignment = db.query(VehicleAssignment).filter_by(id=checkout.assignment.id).one()
    vehicle.status = 3; db.commit()
    returned = return_vehicle(assignment.id, return_payload(assignment, return_inspection_required=False), db, user)
    assert returned.inspection_id and returned.condition_record.return_inspection_required
    assert db.query(Inspection).filter_by(id=returned.inspection_id).one().template_snapshot['code'] == 'RETURN'
    assert vehicle.status == 3
    assert len(generate_scheduled(db, datetime.utcnow(), vehicle=vehicle, event="After return", assignment=assignment)) == 1
    assert db.query(Inspection).count() == 2


def test_legacy_return_checkbox_uses_resolved_template(ctx):
    db, user, vehicle, *_ = ctx
    row, _ = template(ctx, code="RETURN", inspection_type="Return Inspection")
    driver = make_driver(db, 3)
    checkout = checkout_vehicle(checkout_payload(vehicle, driver), db, user)
    assignment = db.query(VehicleAssignment).filter_by(id=checkout.assignment.id).one()
    returned = return_vehicle(assignment.id, return_payload(assignment, return_inspection_required=True), db, user)
    assert db.query(Inspection).filter_by(id=returned.inspection_id).one().template_id == row.id


def client(ctx):
    db, user, *_ = ctx
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.mark.parametrize("role", ["viewer", "driver", "mechanic", "finance"])
def test_permissions_prevent_template_configuration(ctx, role):
    db, user, *_ = ctx
    user.role = role; db.commit()
    c = client(ctx)
    response = c.post('/api/v1/inspection-templates', json={"code":"TEST", "name":"Test", "inspection_type":"Daily"})
    assert response.status_code == 403
    assert db.query(InspectionTemplate).count() == 0


def test_http_crud_and_localized_validation(ctx):
    c = client(ctx)
    response = c.post('/api/v1/inspection-templates', json={"code":"TEST", "name":"Test", "inspection_type":"Daily"})
    assert response.status_code == 201
    tid = response.json()['id']
    response = c.post(f'/api/v1/inspection-templates/{tid}/schedules', headers={'Accept-Language':'sq'}, json={"frequency":"Mileage"})
    assert response.status_code == 422
    assert response.json()['field_errors'][0]['code'] == 'inspection_schedule_interval'
    missing = c.get('/api/v1/inspection-templates/999999', headers={'Accept-Language':'sq'})
    assert missing.status_code == 404 and 'kompani' in missing.json()['message']
    response = c.put(f'/api/v1/inspection-templates/{tid}/archive', json={})
    assert response.status_code == 200 and response.json()['archived']


def test_tenant_isolation_all_configuration_links_and_cached_identity(ctx):
    db, user, vehicle, *_ = ctx
    row, item = template(ctx)
    out = begin(ctx, row)
    image = photo(db, out)
    schedule = api.create_schedule(row.id, ScheduleIn(frequency="Daily"), db, user)
    # Retain cached Alpha objects; tenant queries must still reject their IDs.
    set_tenant_context(db, 2)
    assert api.list_templates(True, db) == []
    for model, row_id in [(InspectionTemplate,row.id),(InspectionTemplateItem,item['id']), (InspectionSchedule,schedule['id']), (Vehicle,vehicle.id)]:
        with pytest.raises(HTTPException): api.get_row(db, model, row_id)
    with pytest.raises(HTTPException): api.get_template(row.id, db)
    assert generate_scheduled(db) == []
    beta = api.create_template(TemplateIn(code="DAILY", name="Beta", inspection_type="Daily"), db, None)
    with pytest.raises(HTTPException): api.create_assignment(beta['id'], AssignmentIn(target_type="Vehicle",target_value=str(vehicle.id)), db, None)
    with pytest.raises(HTTPException): api.update_item(beta['id'],item['id'], TemplateItemIn(code="x",name="x"),db,None)
    set_tenant_context(db, 1)
    assert api.get_template(row.id, db)['name'] == 'DAILY'
    assert db.query(Attachment).filter_by(id=image.id).one().company_id == 1


def test_notification_i18n_keys_and_admin_labels():
    root = Path(__file__).resolve().parents[2] / 'frontend/src/i18n/locales'
    for language in ['en','sq']:
        data = json.loads((root / language / 'modules.json').read_text())
        section = data['inspectionTemplates']
        for name in ['create','duplicate','preview','archive','restore','assignments','schedules','complete']:
            assert section[name]
        for name in ['inspection_required','inspection_item_failed']:
            assert data['notificationContent'][name]['title'] and data['notificationContent'][name]['message']


def test_multiple_failure_orders_remain_editable_and_keep_source(ctx):
    from app.api.v1.endpoints.work_orders import update_work_order
    from app.schemas import WorkOrderUpdate
    db, user, *_ = ctx
    row, _ = template(ctx, create_work_order_on_failure=True)
    api.create_item(row.id, TemplateItemIn(code="TIRES", name="Tires", create_work_order_on_failure=True), db, user)
    out = begin(ctx, row)
    failed = update(ctx, out, results(out, "Fail"))
    orders = db.query(WorkOrder).order_by(WorkOrder.id).all()
    assert len(orders) == 2 and all(i.work_order_id for i in failed.items)
    order = orders[0]
    saved = update_work_order(order.id, WorkOrderUpdate(vehicle_id=order.vehicle_id, inspection_id=out.id,
        title="Inspect brake pads", source="Inspection", assigned_to="Workshop"), db, user)
    assert saved.assigned_to == "Workshop"
    with pytest.raises(HTTPException):
        update_work_order(order.id, WorkOrderUpdate(vehicle_id=order.vehicle_id, title="Detach source"), db, user)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(WorkOrder(vehicle_id=order.vehicle_id, title="Duplicate item order", inspection_id=out.id,
                inspection_item_id=order.inspection_item_id)); db.flush()


def test_inactive_items_and_templates_do_not_apply_to_new_inspections(ctx):
    db, user, v, *_ = ctx
    row, item = template(ctx)
    api.create_item(row.id, TemplateItemIn(code="INACTIVE", name="Not applicable", is_active=False), db, user)
    out = begin(ctx, row)
    assert [i.item_name for i in out.items] == ["Brakes"]
    api.archive_template(row.id, db, user)
    assert resolve_template(db, v, 'Daily') is None
    assert db.query(Inspection).filter_by(id=out.id).one().items[0].item_snapshot['name'] == 'Brakes'


def test_start_and_complete_assignment_cannot_bypass_event_schedules(ctx):
    db, user, vehicle, *_ = ctx
    driver = make_driver(db, 4)
    pre, _ = template(ctx, code='PRE', inspection_type='Before Trip')
    post, _ = template(ctx, code='POST', inspection_type='After Trip')
    api.create_schedule(pre.id, ScheduleIn(frequency='Before check-out'), db, user)
    api.create_schedule(post.id, ScheduleIn(frequency='After return'), db, user)
    assignment = VehicleAssignment(vehicle_id=vehicle.id, driver_id=driver.id, start_datetime=datetime.utcnow(),
        start_odometer_km=vehicle.odometer_km, status='Scheduled')
    db.add(assignment); db.commit()
    with pytest.raises(HTTPException): start_vehicle_assignment(assignment.id, VehicleAssignmentStart(), db, user)
    from app.api.v1.endpoints.inspections import inspection_out
    out = inspection_out(db.query(Inspection).one())
    update(ctx, out, results(out), complete=True)
    start_vehicle_assignment(assignment.id, VehicleAssignmentStart(), db, user)
    complete_vehicle_assignment(assignment.id, VehicleAssignmentComplete(end_datetime=(datetime.utcnow()+timedelta(hours=1)).isoformat(),
        end_odometer_km=vehicle.odometer_km+10), db, user)
    assert db.query(Inspection).filter_by(template_id=post.id).count() == 1


def test_failed_checkout_can_be_rechecked_without_overwriting_failure(ctx):
    db, user, vehicle, *_ = ctx
    row, _ = template(ctx, inspection_type='Before Trip')
    api.create_schedule(row.id, ScheduleIn(frequency='Before check-out'), db, user)
    from app.api.v1.endpoints.inspections import inspection_out
    first = generate_scheduled(db, vehicle=vehicle, event='Before check-out')[0]; db.commit()
    out = inspection_out(first)
    update(ctx, out, results(out,'Fail'), complete=True)
    second = generate_scheduled(db, vehicle=vehicle, event='Before check-out')[0]; db.commit()
    assert first.id != second.id and first.overall_status == 'Failed'
    assert generate_scheduled(db, vehicle=vehicle, event='Before check-out')[0].id == second.id
    assert db.query(Inspection).count() == 2


def test_each_return_gets_its_own_required_inspection_even_if_previous_is_pending(ctx):
    db, user, vehicle, *_ = ctx
    row, _ = template(ctx, inspection_type='Return Inspection')
    api.create_schedule(row.id, ScheduleIn(frequency='After return'), db, user)
    driver = make_driver(db, 5)
    assignments = [VehicleAssignment(vehicle_id=vehicle.id, driver_id=driver.id, start_datetime=datetime.utcnow(),
        start_odometer_km=vehicle.odometer_km, status='Completed') for _ in range(2)]
    db.add_all(assignments); db.commit()
    first = generate_scheduled(db, vehicle=vehicle, event='After return', assignment=assignments[0])[0]
    second = generate_scheduled(db, vehicle=vehicle, event='After return', assignment=assignments[1])[0]
    assert first.id != second.id and not first.completed_at
    assert first.vehicle_assignment_id != second.vehicle_assignment_id


def test_scoped_template_manager_is_denied_shared_configuration(ctx):
    from app.models import Role, Permission, RolePermission, UserRole
    db, user, _, location, _ = ctx
    view = Permission(code='inspections.view', name='View', module='Inspections')
    manage = Permission(code='inspection_templates.manage', name='Manage', module='Inspections')
    role = Role(code='scoped', name='Scoped')
    db.add_all([view,manage,role]); db.flush()
    db.add_all([RolePermission(role_id=role.id,permission_id=view.id), RolePermission(role_id=role.id,permission_id=manage.id),
        UserRole(user_id=user.id,role_id=role.id,location_id=location.id)]); db.commit()
    response = client(ctx).post('/api/v1/inspection-templates', json={'code':'SCOPE','name':'Scope','inspection_type':'Daily'})
    assert response.status_code == 403


def test_foreign_inspection_and_photo_ids_cannot_be_used_in_another_tenant(ctx):
    db, user, _, _, _ = ctx
    alpha, _ = template(ctx)
    alpha_out = begin(ctx, alpha)
    alpha_photo = photo(db, alpha_out)
    set_tenant_context(db, 2)
    beta_vehicle = Vehicle(brand='Beta', model='EV', fuel_type='Electric', vehicle_location='Other',
        license_plate='02-222-BB', registration_country='XK', license_plate_normalized='02222BB')
    db.add(beta_vehicle); db.commit()
    beta_ctx = (db, user, beta_vehicle, None, None)
    beta, _ = template(beta_ctx, photo_required_on_failure=True)
    beta_out = begin(beta_ctx, beta)
    assert beta_out.template_id != alpha_out.template_id
    with pytest.raises(HTTPException) as exc:
        update(ctx, alpha_out, results(alpha_out))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        update(beta_ctx, beta_out, results(beta_out, 'Fail', photo_attachment_ids=[alpha_photo.id]))
    assert exc.value.detail['code'] == 'inspection_photo_required'
    assert db.query(WorkOrder).count() == 0
    set_tenant_context(db, 1)
    assert db.query(Inspection).filter_by(id=alpha_out.id).one().items[0].status == 'Not Checked'


def test_empty_template_cannot_silently_bypass_checkout_schedule(ctx):
    db, user, vehicle, *_ = ctx
    row, item = template(ctx, inspection_type='Before Trip')
    api.create_schedule(row.id, ScheduleIn(frequency='Before check-out'), db, user)
    api.delete_item(row.id, item['id'], db, user)
    driver = make_driver(db, 6)
    with pytest.raises(HTTPException) as exc:
        checkout_vehicle(checkout_payload(vehicle,driver),db,user)
    assert exc.value.detail['code'] == 'inspection_template_empty'
    assert db.query(VehicleAssignment).count() == 0


def test_inspector_can_finish_own_draft_but_not_another_users_draft_or_legacy(ctx):
    db, admin, vehicle, *_ = ctx
    row, _ = template(ctx)
    other = begin(ctx, row)
    inspector = User(email='inspector@test.local',full_name='Inspector',role='driver',hashed_password='unused')
    db.add(inspector); db.commit()
    own_ctx=(db, inspector, vehicle, None, None)
    own=begin(own_ctx,row)
    assert own.created_by_user_id == inspector.id
    with pytest.raises(HTTPException) as exc: update(own_ctx,other,results(other),complete=True)
    assert exc.value.status_code == 403
    completed=update(own_ctx,own,results(own),complete=True)
    assert completed.completed_at
    with pytest.raises(HTTPException): update(own_ctx,completed,results(completed))


def test_linked_driver_can_record_return_inspection(ctx):
    from app.api.v1.endpoints.inspections import inspection_out
    db, user, vehicle, *_ = ctx
    row,_=template(ctx,inspection_type='Return Inspection')
    driver=make_driver(db,7)
    login=User(email='return-driver@test.local',full_name=driver.full_name,role='driver',hashed_password='unused')
    db.add(login); db.flush(); driver.user_id=login.id; db.commit()
    checked=checkout_vehicle(checkout_payload(vehicle,driver),db,user)
    assignment=db.query(VehicleAssignment).filter_by(id=checked.assignment.id).one()
    returned=return_vehicle(assignment.id,return_payload(assignment,return_inspection_required=True),db,user)
    out=inspection_out(db.query(Inspection).filter_by(id=returned.inspection_id).one())
    completed=update((db,login,vehicle,None,None),out,results(out),complete=True)
    assert completed.completed_at
