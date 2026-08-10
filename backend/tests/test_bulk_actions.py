from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.bulk_actions import apply_bulk_action, export_selected
from app.db.session import Base
from app.models import AuditLog, Driver, User, Vehicle, VehicleAssignment, VehicleService, WorkOrder
from app.schemas import BulkActionRequest


@pytest.fixture()
def context():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    admin = User(email="admin@example.com", full_name="Admin", hashed_password="unused", role="admin", is_active=True)
    manager = User(email="manager@example.com", full_name="Manager", hashed_password="unused", role="fleet_manager", is_active=True)
    vehicles = [
        Vehicle(brand="Toyota", model="Corolla", fuel_type="Petrol", vehicle_location="A", registration_country="XK", license_plate=f"0{i}-111-AA", license_plate_normalized=f"0{i}111AA", odometer_km=1000, status=0)
        for i in (1, 2)
    ]
    driver = Driver(full_name="Driver", employee_number="EMP-1", license_number="LIC-1", license_category="B", license_expiry_date=datetime(2028, 1, 1), status="Active")
    db.add_all([admin, manager, *vehicles, driver])
    db.commit()
    yield db, admin, manager, vehicles, driver
    db.close()
    engine.dispose()


def test_bulk_vehicle_updates_programs_work_orders_and_export(context):
    db, admin, _, vehicles, _ = context
    ids = [vehicle.id for vehicle in vehicles]
    result = apply_bulk_action(BulkActionRequest(entity_type="Vehicles", action="change_location", ids=ids, value="Depot B"), db, admin)
    assert result.affected == 2
    assert {vehicle.vehicle_location for vehicle in db.query(Vehicle).all()} == {"Depot B"}

    work_orders = apply_bulk_action(BulkActionRequest(entity_type="Vehicles", action="create_work_orders", ids=ids, value="Tyre inspection"), db, admin)
    assert len(work_orders.created_ids) == 2
    assert db.query(WorkOrder).count() == 2

    programs = apply_bulk_action(BulkActionRequest(entity_type="Vehicles", action="assign_service_program", ids=ids, value="Six-month service"), db, admin)
    assert len(programs.created_ids) == 2
    assert db.query(VehicleService).filter(VehicleService.status == "Reminder").count() == 2

    response = export_selected("Vehicles", ",".join(map(str, ids)), db, admin)
    assert b"Licence Plate" in response.body
    assert b"01-111-AA" in response.body
    assert db.query(AuditLog).filter(AuditLog.action == "Bulk export selected").count() == 1


def test_bulk_archive_preflight_is_atomic_and_restore_uses_archive_permission(context):
    db, admin, manager, vehicles, driver = context
    db.add(VehicleAssignment(
        vehicle_id=vehicles[0].id, driver_id=driver.id, assigned_by_user_id=admin.id,
        start_datetime=datetime.utcnow(), start_odometer_km=1000, status="Active",
    ))
    db.commit()
    with pytest.raises(HTTPException) as conflict:
        apply_bulk_action(BulkActionRequest(entity_type="Vehicles", action="archive", ids=[vehicle.id for vehicle in vehicles]), db, manager)
    assert conflict.value.status_code == 409
    assert not any(vehicle.archived for vehicle in vehicles)

    vehicles[1].archived = True
    db.commit()
    apply_bulk_action(BulkActionRequest(entity_type="Vehicles", action="restore", ids=[vehicles[1].id]), db, manager)
    assert not vehicles[1].archived


def test_bulk_driver_status_and_department_are_audited(context):
    db, admin, _, _, driver = context
    apply_bulk_action(BulkActionRequest(entity_type="Drivers", action="change_status", ids=[driver.id], value="Suspended"), db, admin)
    apply_bulk_action(BulkActionRequest(entity_type="Drivers", action="change_department", ids=[driver.id], value="Safety"), db, admin)
    db.refresh(driver)
    assert (driver.status, driver.department) == ("Suspended", "Safety")
    assert db.query(AuditLog).filter(AuditLog.entity_type == "Drivers").count() == 2
