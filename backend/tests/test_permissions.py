import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.drivers import list_drivers
from app.api.v1.endpoints.vehicles import list_vehicles
from app.core.authorization import (
    ALL_PERMISSIONS,
    DEFAULT_ROLE_PERMISSIONS,
    get_user_permissions,
    has_permission,
    require_permission,
    seed_authorization_defaults,
)
from app.core.security import create_access_token, get_current_user
from app.db.session import Base
from app.models import Department, Driver, Location, Permission, Role, RolePermission, User, UserRole, Vehicle


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


def user(email: str, role: str = "viewer", **values) -> User:
    return User(email=email, full_name=email.split("@")[0], hashed_password="unused", role=role, **values)


def test_default_role_migration_preserves_legacy_roles_and_granular_permissions(db: Session):
    admin = user("admin@example.com", "admin")
    driver = user("driver@example.com", "driver")
    db.add_all([admin, driver]); db.commit()

    seed_authorization_defaults(db)

    assert {assignment.role.code for assignment in admin.role_assignments} == {"admin"}
    assert {assignment.role.code for assignment in driver.role_assignments} == {"driver"}
    assert get_user_permissions(db, admin) == set(ALL_PERMISSIONS)
    assert "reservations.create" in get_user_permissions(db, driver)
    assert "users.manage" not in get_user_permissions(db, driver)
    assert set(DEFAULT_ROLE_PERMISSIONS) == {"admin", "fleet_manager", "mechanic", "driver", "finance", "viewer"}


def test_custom_role_permission_is_authoritative(db: Session):
    seed_authorization_defaults(db)
    viewer = user("custom@example.com")
    permission = db.query(Permission).filter(Permission.code == "vehicles.view").one()
    role = Role(code="vehicle_reader", name="Vehicle Reader")
    role.role_permissions.append(RolePermission(permission_id=permission.id))
    db.add_all([viewer, role]); db.flush()
    db.add(UserRole(user_id=viewer.id, role_id=role.id)); db.commit()

    assert has_permission(db, viewer, "vehicles.view")
    assert not has_permission(db, viewer, "vehicles.edit")
    assert require_permission("vehicles.view")(db, viewer) is viewer
    with pytest.raises(HTTPException) as denied:
        require_permission("vehicles.edit")(db, viewer)
    assert denied.value.status_code == 403


def test_inactive_users_and_revoked_session_versions_are_rejected(db: Session):
    inactive = user("inactive@example.com", is_active=False)
    active = user("active@example.com", session_version=0)
    db.add_all([inactive, active]); db.commit()

    with pytest.raises(HTTPException) as disabled:
        get_current_user(create_access_token(inactive.id), db)
    assert disabled.value.status_code == 403

    token = create_access_token(active.id, session_version=0)
    assert get_current_user(token, db).id == active.id
    active.session_version = 1; db.commit()
    with pytest.raises(HTTPException) as revoked:
        get_current_user(token, db)
    assert revoked.value.status_code == 401


def test_location_department_and_own_record_scopes_filter_backend_queries(db: Session):
    seed_authorization_defaults(db)
    location_a, location_b = Location(code="A", name="A"), Location(code="B", name="B")
    department_a, department_b = Department(code="A", name="A"), Department(code="B", name="B")
    scoped = user("scoped@example.com")
    permission_codes = ["vehicles.view", "drivers.view"]
    permissions = db.query(Permission).filter(Permission.code.in_(permission_codes)).all()
    role = Role(code="scoped_reader", name="Scoped Reader", role_permissions=[RolePermission(permission_id=row.id) for row in permissions])
    db.add_all([location_a, location_b, department_a, department_b, scoped, role]); db.flush()
    assignment = UserRole(user_id=scoped.id, role_id=role.id, location_id=location_a.id, department_id=department_a.id)
    db.add(assignment)
    db.add_all([
        Vehicle(brand="A", model="One", fuel_type="Petrol", vehicle_location="A", location_id=location_a.id, license_plate="01-101-AA", registration_country="XK", license_plate_normalized="01101AA"),
        Vehicle(brand="B", model="Two", fuel_type="Petrol", vehicle_location="B", location_id=location_b.id, license_plate="01-102-AA", registration_country="XK", license_plate_normalized="01102AA"),
        Driver(full_name="Allowed", employee_number="E1", department="A", department_id=department_a.id, license_number="L1", license_category="B", license_expiry_date=datetime(2030, 1, 1), user_id=scoped.id),
        Driver(full_name="Denied", employee_number="E2", department="B", department_id=department_b.id, license_number="L2", license_category="B", license_expiry_date=datetime(2030, 1, 1)),
    ]); db.commit()

    vehicles = list_vehicles(None, None, None, None, None, False, db, scoped)
    assignment.own_records_only = True; db.commit()
    drivers = list_drivers(None, None, None, None, None, False, db, scoped)
    assert [row.license_plate for row in vehicles] == ["01-101-AA"]
    assert [row.full_name for row in drivers] == ["Allowed"]


def test_major_modules_and_audit_logs_have_explicit_permissions(db: Session):
    expected = {
        "vehicles.view", "drivers.manage", "fuel.view_cost", "maintenance.complete_work_order",
        "documents.verify", "reservations.approve", "reports.export", "audit_logs.view",
        "users.manage", "roles.manage", "settings.manage",
    }
    assert expected.issubset(ALL_PERMISSIONS)
    audit_reader = user("audit@example.com", "viewer")
    db.add(audit_reader); db.commit()
    with pytest.raises(HTTPException):
        require_permission("audit_logs.view")(db, audit_reader)


@pytest.mark.parametrize(("role", "allowed", "denied"), [
    ("viewer", "vehicles.view", "vehicles.edit"),
    ("fleet_manager", "assignments.manage", "users.manage"),
    ("mechanic", "maintenance.complete_work_order", "reports.export"),
    ("driver", "reservations.create", "reservations.approve"),
    ("finance", "fuel.view_cost", "drivers.manage"),
    ("admin", "audit_logs.view", "not.a.real.permission"),
])
def test_default_role_permission_matrix_covers_major_modules(db: Session, role: str, allowed: str, denied: str):
    actor = user(f"{role}@example.com", role)
    db.add(actor); db.commit()
    assert has_permission(db, actor, allowed)
    assert not has_permission(db, actor, denied)


def test_admin_translations_and_permission_visibility_contract_exist():
    root = Path(__file__).resolve().parents[2]
    for language in ("en", "sq"):
        modules = json.loads((root / "frontend" / "src" / "i18n" / "locales" / language / "modules.json").read_text())
        navigation = json.loads((root / "frontend" / "src" / "i18n" / "locales" / language / "navigation.json").read_text())
        assert modules["admin"]["usersTitle"]
        assert modules["admin"]["rolesTitle"]
        assert navigation["organizationSettings"]
    auth_source = (root / "frontend" / "src" / "lib" / "auth.tsx").read_text()
    assert "DEFAULT_ROLE_PERMISSIONS[user.role]" in auth_source
    assert "Array.isArray(user.permissions)" in auth_source
