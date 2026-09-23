from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import get_current_user
from app.db.session import Base, get_db
from app.main import app
from app.models import (
    Attachment, Company, Driver, Permission, Role, RolePermission, User,
    UserRole, Vehicle, VehicleAccident, VehicleAssignment, VehicleConditionRecord,
)


@pytest.fixture()
def context():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine)
    actors = {}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actors["current"]
    try:
        yield db, actors, TestClient(app, headers={"Origin": "http://localhost:3000"})
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def setup_record(db: Session, entity_type: str):
    for company_id, name, slug in ((1, "Alpha", "alpha"), (2, "Beta", "beta")):
        if db.get(Company, company_id) is None:
            db.add(Company(id=company_id, name=name, slug=slug))
    users = {
        name: User(company_id=company_id, email=f"{name}@example.test", full_name=name,
                   hashed_password="unused", role=role, is_active=True)
        for name, role, company_id in (
            ("manager", "fleet_manager", 1), ("scoped", "fleet_manager", 1),
            ("viewer", "viewer", 1), ("outsider", "admin", 2),
        )
    }
    db.add_all(users.values())
    db.flush()
    drivers = [Driver(company_id=1, full_name=name, employee_number=f"EMP-{name}",
                      license_number=f"LIC-{name}", license_category="B",
                      license_expiry_date=datetime.utcnow() + timedelta(days=365),
                      status="Active", user_id=users[name].id)
               for name in ("manager", "scoped")]
    vehicle = Vehicle(company_id=1, brand="Toyota", model="Corolla", fuel_type="Petrol",
                      vehicle_location="Depot", license_plate="01-111-AA",
                      registration_country="XK", license_plate_normalized="01111AA", status=0)
    db.add_all([*drivers, vehicle])
    db.flush()
    if entity_type == "VehicleAccident":
        parent = VehicleAccident(company_id=1, vehicle_id=vehicle.id, driver_id=drivers[0].id,
                                 accident_date=datetime.utcnow(), location="Depot", severity="Minor")
    else:
        assignment = VehicleAssignment(company_id=1, vehicle_id=vehicle.id, driver_id=drivers[0].id,
                                       start_datetime=datetime.utcnow(), start_odometer_km=100,
                                       status="Active")
        db.add(assignment)
        db.flush()
        parent = VehicleConditionRecord(company_id=1, vehicle_assignment_id=assignment.id,
                                        vehicle_id=vehicle.id, driver_id=drivers[0].id,
                                        record_type="Checkout", recorded_at=datetime.utcnow(),
                                        odometer_km=100, vehicle_condition="Good")
    db.add(parent)
    db.flush()
    attachment = Attachment(company_id=1, original_filename="photo.jpg", stored_filename="photo-1.jpg",
                            storage_path="photos/photo-1.jpg", mime_type="image/jpeg", file_size=4,
                            uploaded_by=users["manager"].id, entity_type=entity_type, entity_id=parent.id)
    db.add(attachment)
    permission_code = "accidents.manage" if entity_type == "VehicleAccident" else "assignments.manage"
    view_code = "accidents.view" if entity_type == "VehicleAccident" else "assignments.view"
    role = Role(code=f"scoped_{entity_type}", name="Scoped manager", is_active=True)
    permissions = []
    for code in (permission_code, view_code):
        permission = db.query(Permission).filter_by(code=code).one_or_none()
        if permission is None:
            permission = Permission(code=code, name=code, module="Files", description=code)
            db.add(permission)
        permissions.append(permission)
    db.add(role)
    db.flush()
    db.add_all([RolePermission(role_id=role.id, permission_id=permission.id) for permission in permissions])
    db.add(UserRole(user_id=users["scoped"].id, role_id=role.id, own_records_only=True))
    db.commit()
    return users, parent, attachment


@pytest.mark.parametrize("entity_type", ["VehicleAccident", "VehicleConditionRecord"])
def test_archive_checks_parent_ownership_permission_state_and_tenant(context, entity_type):
    db, actors, client = context
    users, parent, attachment = setup_record(db, entity_type)
    url = f"/api/v1/files/{attachment.id}"

    actors["current"] = users["scoped"]
    assert client.delete(url).status_code == 403
    assert client.get(f"/api/v1/files?entity_type={entity_type}&entity_id={parent.id}").status_code == 403
    assert client.get(f"{url}/download").status_code == 403
    assert client.post("/api/v1/files", data={"entity_type": entity_type, "entity_id": parent.id},
                       files={"file": ("photo.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")}).status_code == 403
    assert not attachment.archived

    actors["current"] = users["viewer"]
    assert client.delete(url).status_code == 403
    assert not attachment.archived

    actors["current"] = users["outsider"]
    assert client.delete(url).status_code == 404
    assert not attachment.archived

    actors["current"] = users["manager"]
    parent.archived = True if entity_type == "VehicleAccident" else False
    if entity_type == "VehicleConditionRecord":
        parent.vehicle_assignment.archived = True
    db.commit()
    assert client.delete(url).status_code == 404
    assert not attachment.archived

    if entity_type == "VehicleConditionRecord":
        parent.vehicle_assignment.archived = False
    else:
        parent.archived = False
    db.commit()
    assert client.delete(url).status_code == 200
    db.refresh(attachment)
    assert attachment.archived and attachment.archived_by == users["manager"].id
