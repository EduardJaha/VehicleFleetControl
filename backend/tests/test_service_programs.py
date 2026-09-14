from datetime import date, datetime, timedelta
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import service_programs as api
from app.api.v1.endpoints.services import add_service, update_service, archive_service, restore_service
from app.api.v1.endpoints.work_orders import complete_work_order
from app.core.authorization import require_permission, seed_authorization_defaults
from app.core.security import get_current_user
from app.db.session import Base, TenantSession, get_db, set_tenant_context
from app.main import app
from app.models import (AuditLog, Company, CompanyUser, Department, Driver, Location, Notification, Role,
                        ServiceProgram, ServiceProgramReminder, ServiceProgramRule, ServiceProgramTask,
                        User, UserRole, Vehicle, VehicleAssignment, VehicleService, VehicleServiceProgram, WorkOrder)
from app.program_schemas import ProgramIn, ProgramRuleIn, ProgramTaskIn
from app.schemas import AddService, WorkOrderCompletionRequest
from app.services.service_programs import add_months, reminder_status, synchronize_all, winning_rule


@pytest.fixture()
def ctx():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = TenantSession(engine)
    db.add_all([Company(id=1, name="Alpha", slug="alpha"), Company(id=2, name="Beta", slug="beta")])
    db.commit()
    set_tenant_context(db, 1)
    user = User(email="admin@alpha.test", full_name="Admin", role="admin", hashed_password="unused")
    db.add(user); db.flush()
    db.add(CompanyUser(user_id=user.id, company_id=1, role="admin"))
    location = Location(name="Depot", code="DEPOT")
    department = Department(name="Operations", code="OPS")
    db.add_all([location, department]); db.flush()
    vehicle = Vehicle(brand="VW", model="Golf", fuel_type="Diesel", vehicle_category="Passenger",
                      vehicle_location="Depot", location_id=location.id, license_plate="01-111-AA",
                      registration_country="XK", license_plate_normalized="01111AA", odometer_km=20000)
    db.add(vehicle); db.commit()
    yield db, user, vehicle, location, department
    app.dependency_overrides.clear()
    db.close(); engine.dispose()


def program(ctx, name="Diesel Passenger", **task_values):
    db, user, *_ = ctx
    row = api.create_program(ProgramIn(name=name), db, user)
    task = api.create_task(row["id"], ProgramTaskIn(service_type="Oil Change", title="Oil Change",
        **({"km_interval": 10000, "month_interval": 12, "warning_km": 1000, "warning_days": 30} | task_values)), db, user)
    return row["id"], task["id"]


def assign(ctx, program_id, target_type="Vehicle", value=None, **kwargs):
    db, user, vehicle, *_ = ctx
    return api.create_rule(ProgramRuleIn(program_id=program_id, target_type=target_type,
        target_value=value or str(vehicle.id), **kwargs), db, user)


def active(ctx):
    return ctx[0].query(ServiceProgramReminder).filter_by(is_active=True).one()


def test_program_task_crud_archive_restore_and_audits(ctx):
    db, user, vehicle, *_ = ctx
    pid, tid = program(ctx)
    assign(ctx, pid)
    assert api.get_program(pid, db)["tasks"][0]["id"] == tid
    api.update_program(pid, ProgramIn(name="Updated", description="Fleet policy"), db, user)
    api.update_task(pid, tid, ProgramTaskIn(service_type="Oil Change", title="Engine Oil", km_interval=5000), db, user)
    assert active(ctx).due_odometer_km == 25000
    api.delete_task(pid, tid, db, user)
    assert db.query(ServiceProgramReminder).filter_by(is_active=True).count() == 0
    api.update_task(pid, tid, ProgramTaskIn(service_type="Oil Change", title="Oil", km_interval=5000), db, user)
    api.archive_program(pid, db, user)
    assert api.list_programs(False, db) == []
    assert len(api.list_programs(True, db)) == 1
    assert not db.query(VehicleServiceProgram).filter_by(is_active=True).count()
    api.restore_program(pid, db, user)
    assert active(ctx).due_odometer_km == 25000
    assert db.query(VehicleService).count() == 0
    codes = {a.action_code for a in db.query(AuditLog).all()}
    assert {"program_created", "program_updated", "program_task_created", "program_task_updated", "program_archived", "program_restored", "program_assigned", "program_reminder_created"} <= codes


@pytest.mark.parametrize("kwargs", [{}, {"km_interval": 0}, {"month_interval": -1}, {"km_interval": 100, "warning_km": 101}, {"km_interval": 100, "warning_days": 5}])
def test_task_interval_validation(kwargs):
    with pytest.raises(ValidationError):
        ProgramTaskIn(service_type="Inspection", title="Inspection", **kwargs)


@pytest.mark.parametrize("km,months", [(5000, None), (None, 12), (10000, 12)])
def test_km_date_and_combined_history_generation(ctx, km, months):
    db, user, vehicle, *_ = ctx
    db.add(VehicleService(vehicle_id=vehicle.id, service_type="Oil Change", service_date=datetime(2025, 1, 31), odometer_km=10000))
    db.commit()
    pid, _ = program(ctx, km_interval=km, month_interval=months, warning_km=None, warning_days=None)
    assign(ctx, pid)
    row = active(ctx)
    assert row.due_odometer_km == (10000 + km if km else None)
    assert row.due_date == (date(2026, 1, 31) if months else None)


def test_calendar_month_end_and_leap_year():
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert add_months(date(2025, 12, 31), 2) == date(2026, 2, 28)


@pytest.mark.parametrize("first,km,days,expected", [
    (True, 10001, 500, "Overdue"), (True, 1, -1, "Overdue"),
    (True, 10000, 500, "Due"), (True, 9500, 500, "Due Soon"),
    (True, 0, 31, "Current"), (False, 10001, 500, "Current"),
    (False, 10001, -1, "Overdue"), (False, 10001, 15, "Due Soon"),
    (False, 10000, 0, "Due"),
])
def test_whichever_first_and_both_thresholds(ctx, first, km, days, expected):
    pid, _ = program(ctx, whichever_occurs_first=first)
    assign(ctx, pid)
    row = active(ctx)
    row.vehicle.odometer_km = 20000 + km
    row.due_date = date.today() + timedelta(days=days)
    assert reminder_status(row) == expected


def test_missing_odometer_not_fabricated_or_counted_compliant(ctx):
    db, user, vehicle, *_ = ctx
    vehicle.odometer_km = None; db.commit()
    pid, _ = program(ctx, month_interval=None, warning_days=None)
    assign(ctx, pid)
    assert active(ctx).due_odometer_km is None
    assert reminder_status(active(ctx)) == "Needs Baseline"
    assert api.compliance(None, db, user)["compliance_percent"] == 0
    vehicle.odometer_km = 30000; db.commit()
    assert active(ctx).due_odometer_km == 40000
    vehicle.odometer_km = 31000; db.commit()
    assert active(ctx).due_odometer_km == 40000


def test_priority_resolution_all_selectors_and_newest_rule(ctx):
    db, user, vehicle, location, department = ctx
    driver = Driver(full_name="Driver", employee_number="D1", license_number="L1", license_category="B",
        license_expiry_date=datetime(2030,1,1), department_id=department.id)
    db.add(driver); db.flush()
    db.add(VehicleAssignment(vehicle_id=vehicle.id, driver_id=driver.id, assigned_by_user_id=user.id,
                             start_datetime=datetime.utcnow(), start_odometer_km=20000, status="Active"))
    db.commit()
    for i, (kind, value, model) in enumerate([
        ("FuelType", "Diesel", None), ("Category", "Passenger", None),
        ("Location", str(location.id), None), ("Department", str(department.id), None),
        ("BrandModel", "VW", None), ("BrandModel", "VW", "Golf"), ("Vehicle", str(vehicle.id), None),
    ]):
        pid, _ = program(ctx, name=f"Program {i}")
        assign(ctx, pid, kind, value, model=model)
        assert winning_rule(db, vehicle).program_id == pid
        assert db.query(VehicleServiceProgram).filter_by(is_active=True).count() == 1
        assert db.query(ServiceProgramReminder).filter_by(is_active=True).count() == 1
    pid, _ = program(ctx, name="Last")
    last = assign(ctx, pid)
    assert winning_rule(db, vehicle).program_id == pid
    api.delete_rule(last["id"], db, user)
    assert winning_rule(db, vehicle).program_id != pid


def test_rules_follow_vehicle_changes_and_future_effective_dates(ctx):
    db, user, vehicle, *_ = ctx
    pid, _ = program(ctx)
    assign(ctx, pid, "FuelType", "Diesel")
    vehicle.fuel_type = "Petrol"; db.commit()
    assert not db.query(VehicleServiceProgram).filter_by(is_active=True).count()
    vehicle.fuel_type = "Diesel"; db.commit()
    assert active(ctx)
    future, _ = program(ctx, name="Future")
    assign(ctx, future, effective_from=date.today() + timedelta(days=2))
    assert winning_rule(db, vehicle).program_id == pid
    synchronize_all(db, today=date.today() + timedelta(days=2)); db.commit()
    assert db.query(VehicleServiceProgram).filter_by(is_active=True).one().program_id == future


def test_duplicate_prevention_and_database_guards(ctx):
    db, user, vehicle, *_ = ctx
    pid, tid = program(ctx)
    first = assign(ctx, pid)
    assign(ctx, pid)
    synchronize_all(db); synchronize_all(db); db.commit()
    assert db.query(ServiceProgramRule).count() == 1
    assert db.query(ServiceProgramReminder).count() == 1
    assert db.query(VehicleServiceProgram).count() == 1
    with pytest.raises(HTTPException) as exc:
        api.create_task(pid, ProgramTaskIn(service_type="oil change", title="Duplicate", km_interval=5000), db, user)
    assert exc.value.status_code == 409
    row = active(ctx)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(ServiceProgramReminder(vehicle_id=vehicle.id, assignment_id=row.assignment_id, task_id=tid))
            db.flush()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(VehicleServiceProgram(vehicle_id=vehicle.id, program_id=pid, rule_id=first["id"], effective_from=date.today()))
            db.flush()


def test_service_completion_regenerates_and_preserves_manual_reminders(ctx):
    db, user, vehicle, *_ = ctx
    manual = VehicleService(vehicle_id=vehicle.id, service_type="Oil Change", service_date=datetime(2025,1,1),
                            odometer_km=10000, next_service_odometer_km=30000, reminder_status="Upcoming")
    db.add(manual); db.commit()
    pid, _ = program(ctx)
    assign(ctx, pid)
    previous = active(ctx).id
    payload = AddService(license_plate=vehicle.license_plate, service_type="Oil Change", service_date=date.today().strftime("%d-%m-%Y"), odometer_km=21000)
    result = add_service(payload, db, user)
    row = active(ctx)
    assert row.id != previous
    assert row.basis_service_id == result["id"]
    assert row.due_odometer_km == 31000
    assert row.due_date == add_months(date.today(), 12)
    assert db.get(ServiceProgramReminder, previous).resolution == "Resolved"
    db.refresh(manual)
    assert manual.next_service_odometer_km == 30000 and manual.reminder_status == "Upcoming" and not manual.archived
    synchronize_all(db); db.commit()
    assert db.query(ServiceProgramReminder).count() == 2
    update_service(result["id"], payload.model_copy(update={"odometer_km":22000}), db, user)
    assert active(ctx).id == row.id and active(ctx).due_odometer_km == 32000
    archive_service(result["id"], db, user)
    assert active(ctx).basis_service_id == manual.id
    restore_service(result["id"], db, user)
    assert active(ctx).basis_service_id == result["id"]


def test_auto_work_order_creation_completion_and_notifications(ctx):
    db, user, vehicle, *_ = ctx
    pid, _ = program(ctx, auto_create_work_order=True)
    assign(ctx, pid)
    row = active(ctx)
    order_id, reminder_id = row.work_order_id, row.id
    synchronize_all(db); db.commit()
    assert db.query(WorkOrder).count() == 1
    vehicle.odometer_km = 29900; db.commit()
    alerts = db.query(Notification).filter_by(entity_type="ServiceProgramReminder").all()
    assert len(alerts) == 1 and alerts[0].status == "Unread"
    synchronize_all(db); db.commit()
    assert db.query(Notification).filter_by(entity_type="ServiceProgramReminder").count() == 1
    result = complete_work_order(order_id, WorkOrderCompletionRequest(actual_completion_date=date.today().strftime("%d-%m-%Y"),
        completed_odometer_km=30000, service_type="Oil Change"), db, user)
    assert result.reminder_resolved and result.next_reminder_created
    assert active(ctx).work_order_id != order_id
    assert active(ctx).due_odometer_km == 40000
    assert db.query(WorkOrder).count() == 2
    assert db.get(WorkOrder, order_id).status == "Completed"
    assert db.get(ServiceProgramReminder, reminder_id).resolution == "Resolved"
    db.refresh(alerts[0]); assert alerts[0].status == "Resolved"


def test_auto_order_completion_rejects_wrong_service(ctx):
    db, user, *_ = ctx
    pid, _ = program(ctx, auto_create_work_order=True); assign(ctx, pid)
    with pytest.raises(HTTPException):
        complete_work_order(active(ctx).work_order_id, WorkOrderCompletionRequest(actual_completion_date=date.today().strftime("%d-%m-%Y"), completed_odometer_km=20000, service_type="General Service"), db, user)
    assert active(ctx).work_order.status == "Open"


def test_program_without_auto_does_not_create_work_orders(ctx):
    db, *_ = ctx
    pid, _ = program(ctx); assign(ctx, pid)
    assert active(ctx).work_order_id is None
    assert db.query(WorkOrder).count() == 0


def test_tenant_isolation_for_reads_writes_rules_and_history(ctx):
    db, user, vehicle, *_ = ctx
    pid, _ = program(ctx); assign(ctx, pid)
    set_tenant_context(db, 2)
    other = ServiceProgram(name="Secret")
    db.add(other); db.commit(); other_id = other.id
    assert api.list_programs(False, db)[0]["name"] == "Secret"
    assert api.compliance(None, db, user)["items"] == []
    with pytest.raises(HTTPException): api.get_program(pid, db)
    set_tenant_context(db, 1)
    with pytest.raises(HTTPException): api.get_program(other_id, db)
    with pytest.raises(HTTPException): assign(ctx, other_id)
    assert active(ctx).vehicle_id == vehicle.id


def test_api_permissions_validation_and_localization(ctx):
    db, user, *_ = ctx
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        response = client.post("/api/v1/maintenance/programs", json={"name":"API Program"})
        assert response.status_code == 200
        pid = response.json()["id"]
        response = client.post(f"/api/v1/maintenance/programs/{pid}/tasks", json={"title":"Oil", "service_type":"Oil"}, headers={"Accept-Language":"sq"})
        assert response.status_code == 422
        assert response.json()["field_errors"][0]["code"] == "program_interval_required"
        for role in ["viewer", "driver", "finance"]:
            user.role = role; db.commit()
            assert client.get("/api/v1/maintenance/programs").status_code == 200
            assert client.post("/api/v1/maintenance/programs", json={"name":"Forbidden"}).status_code == 403
            assert client.delete(f"/api/v1/maintenance/programs/{pid}").status_code == 403
            assert client.post("/api/v1/maintenance/programs/rules", json={"program_id":pid,"target_type":"Vehicle","target_value":"1"}).status_code == 403
        response = client.get("/api/v1/maintenance/programs/999", headers={"Accept-Language":"sq"})
        assert response.status_code == 404
        assert "kompani" in response.json()["message"]


def test_scoped_permissions_do_not_leak_vehicle_compliance(ctx):
    db, user, vehicle, location, *_ = ctx
    pid, _ = program(ctx); assign(ctx, pid)
    seed_authorization_defaults(db)
    role = db.query(Role).filter_by(code="fleet_manager").one()
    for grant in db.query(UserRole).filter_by(user_id=user.id).all(): db.delete(grant)
    db.add(UserRole(user_id=user.id, role_id=role.id, location_id=999)); db.commit()
    assert api.compliance(None, db, user)["vehicles"] == []
    with pytest.raises(HTTPException): assign(ctx, pid)
    with pytest.raises(HTTPException): api.create_program(ProgramIn(name="Blocked"), db, user)


def test_i18n_keys_for_programs_audits_and_notifications(ctx):
    db, *_ = ctx
    pid, _ = program(ctx); assign(ctx, pid)
    for lang in ["en", "sq"]:
        modules = json.loads((Path(__file__).resolve().parents[2] / "frontend/src/i18n/locales" / lang / "modules.json").read_text())
        for log in db.query(AuditLog).filter(AuditLog.action_code.like("program_%")).all():
            value = modules
            for key in log.description_key.removeprefix("modules:").split("."): value = value[key]
            assert value and "{{id}}" in value
        assert modules["programs"]["notification"]["message"]


def test_reassign_previous_program_and_restore_does_not_drift_km(ctx):
    db, user, vehicle, *_ = ctx
    first, _ = program(ctx, name="First")
    second, _ = program(ctx, name="Second")
    assign(ctx, first); assign(ctx, second)
    vehicle.odometer_km = 25000; db.commit()
    assign(ctx, first)
    assert winning_rule(db, vehicle).program_id == first
    assert active(ctx).due_odometer_km == 30000
    api.archive_program(first, db, user)
    assert winning_rule(db, vehicle).program_id == second
    api.restore_program(first, db, user)
    assert active(ctx).due_odometer_km == 30000


def test_missing_km_with_date_warning_still_needs_baseline(ctx):
    db, _, vehicle, *_ = ctx
    vehicle.odometer_km = None; db.commit()
    pid, _ = program(ctx); assign(ctx, pid)
    row = active(ctx)
    row.due_date = date.today() + timedelta(days=10)
    assert reminder_status(row) == "Needs Baseline"


def test_rule_updates_task_identity_and_assignment_history(ctx):
    db, user, vehicle, *_ = ctx
    pid, tid = program(ctx)
    rule = assign(ctx, pid, "FuelType", "Diesel")
    api.update_rule(rule["id"], ProgramRuleIn(program_id=pid, target_type="FuelType", target_value="Petrol"), db, user)
    assert not api.list_assignments(False, db, user)
    assert len(api.list_assignments(True, db, user)) == 1
    with pytest.raises(HTTPException) as error:
        api.update_task(pid, tid, ProgramTaskIn(service_type="Technical Inspection", title="Inspection", month_interval=12), db, user)
    assert error.value.detail["code"] == "program_task_history"
    vehicle.fuel_type = "Petrol"; db.commit()
    assert len(api.list_assignments(False, db, user)) == 1


def test_program_bulk_ids_are_real_and_retry_is_idempotent(ctx):
    from app.api.v1.endpoints.bulk_actions import apply_bulk_action
    from app.schemas import BulkActionRequest
    db, user, vehicle, *_ = ctx
    pid, _ = program(ctx)
    payload = BulkActionRequest(entity_type="Vehicles", action="assign_service_program", ids=[vehicle.id], options={"program_id":pid})
    first = apply_bulk_action(payload, db, user)
    second = apply_bulk_action(payload, db, user)
    assert first.created_ids == second.created_ids
    assert db.query(VehicleServiceProgram).count() == 1
    assert db.query(ServiceProgramReminder).count() == 1
    assert db.query(VehicleService).count() == 0


def test_started_program_work_can_finish_after_program_archived(ctx):
    db, user, *_ = ctx
    pid, _ = program(ctx, auto_create_work_order=True)
    assign(ctx, pid)
    order = active(ctx).work_order
    order.status = "In Progress"; db.commit()
    api.archive_program(pid, db, user)
    assert order.status == "In Progress"
    result = complete_work_order(order.id, WorkOrderCompletionRequest(actual_completion_date=date.today().strftime("%d-%m-%Y"),
        completed_odometer_km=20000, service_type="Oil Change"), db, user)
    assert result.service and not result.next_reminder_created
    assert db.query(ServiceProgramReminder).filter_by(is_active=True).count() == 0
