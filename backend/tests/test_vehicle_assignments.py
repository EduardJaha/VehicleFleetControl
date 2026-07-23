from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.vehicle_assignments import (
    archive_vehicle_assignment,
    complete_vehicle_assignment,
    create_vehicle_assignment,
    restore_vehicle_assignment,
    start_vehicle_assignment,
)
from app.core.security import require_roles
from app.db.session import Base
from app.models import AuditLog, Driver, Notification, User, Vehicle, VehicleAssignment
from app.schemas import (
    UserRole,
    VehicleAssignmentComplete,
    VehicleAssignmentCreate,
    VehicleAssignmentStart,
    VehicleAssignmentStatus,
)
from app.services.vehicle_assignments import active_assignment_at


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def users(db: Session) -> dict[str, User]:
    rows = {
        role: User(
            email=f"assignment-{role}@example.com",
            full_name=role.replace("_", " ").title(),
            hashed_password="unused",
            role=role,
            is_active=True,
        )
        for role in ("admin", "fleet_manager", "viewer")
    }
    db.add_all(rows.values())
    db.commit()
    return rows


def make_vehicle(db: Session, sequence: int, odometer: int = 10_000) -> Vehicle:
    vehicle = Vehicle(
        brand="Toyota",
        model="Corolla",
        fuel_type="Hybrid",
        vehicle_location="Prishtina",
        license_plate=f"01-{sequence:03d}-AA",
        registration_country="XK",
        license_plate_normalized=f"01{sequence:03d}AA",
        status=0,
        odometer_km=odometer,
    )
    db.add(vehicle)
    db.commit()
    return vehicle


def make_driver(db: Session, sequence: int) -> Driver:
    driver = Driver(
        full_name=f"Driver {sequence}",
        employee_number=f"EMP-{sequence}",
        license_number=f"LIC-{sequence}",
        license_category="B",
        license_expiry_date=datetime.utcnow() + timedelta(days=365),
        status="Active",
    )
    db.add(driver)
    db.commit()
    return driver


def create_scheduled(
    db: Session,
    user: User,
    vehicle: Vehicle,
    driver: Driver,
    *,
    start_odometer: int | None = None,
):
    return create_vehicle_assignment(
        VehicleAssignmentCreate(
            vehicle_id=vehicle.id,
            driver_id=driver.id,
            start_datetime=(datetime.utcnow() + timedelta(hours=1)).isoformat(),
            start_odometer_km=start_odometer if start_odometer is not None else vehicle.odometer_km or 0,
            start_energy_level=80,
            purpose="Business Trip",
            notes="Scheduled test assignment",
        ),
        db,
        user,
    )


def test_create_scheduled_assignment_records_creator_audit_and_notification(db: Session, users):
    vehicle = make_vehicle(db, 101)
    driver = make_driver(db, 101)

    result = create_scheduled(db, users["fleet_manager"], vehicle, driver)

    assert result.status == VehicleAssignmentStatus.scheduled
    assert result.assigned_by_user_id == users["fleet_manager"].id
    assert db.get(Driver, driver.id).assigned_vehicle_id is None
    assert db.query(AuditLog).filter(
        AuditLog.entity_type == "VehicleAssignment",
        AuditLog.action == "Vehicle Assignment created",
    ).count() == 1
    assert db.query(Notification).filter(
        Notification.entity_type == "VehicleAssignment",
        Notification.entity_id == result.id,
    ).count() >= 1


def test_start_and_complete_assignment_updates_compatibility_relationship_and_odometer(db: Session, users):
    vehicle = make_vehicle(db, 102)
    driver = make_driver(db, 102)
    scheduled = create_scheduled(db, users["fleet_manager"], vehicle, driver)

    started = start_vehicle_assignment(
        scheduled.id,
        VehicleAssignmentStart(
            start_datetime=datetime.utcnow().isoformat(),
            start_odometer_km=10_050,
            start_energy_level=75,
        ),
        db,
        users["fleet_manager"],
    )
    assert started.status == VehicleAssignmentStatus.active
    assert db.get(Driver, driver.id).assigned_vehicle_id == vehicle.id
    assert db.get(Vehicle, vehicle.id).odometer_km == 10_050

    completed = complete_vehicle_assignment(
        scheduled.id,
        VehicleAssignmentComplete(
            end_datetime=(datetime.utcnow() + timedelta(hours=2)).isoformat(),
            end_odometer_km=10_240,
            end_energy_level=40,
            return_notes="Returned clean.",
        ),
        db,
        users["fleet_manager"],
    )
    assert completed.status == VehicleAssignmentStatus.completed
    assert completed.ended_by_user_id == users["fleet_manager"].id
    assert completed.return_notes == "Returned clean."
    assert db.get(Driver, driver.id).assigned_vehicle_id is None
    assert db.get(Vehicle, vehicle.id).odometer_km == 10_240


def test_prevents_two_active_assignments_for_one_vehicle(db: Session, users):
    vehicle = make_vehicle(db, 103)
    first_driver = make_driver(db, 103)
    second_driver = make_driver(db, 104)
    first = create_scheduled(db, users["fleet_manager"], vehicle, first_driver)
    start_vehicle_assignment(first.id, VehicleAssignmentStart(), db, users["fleet_manager"])
    second = create_scheduled(db, users["fleet_manager"], vehicle, second_driver)

    with pytest.raises(HTTPException) as conflict:
        start_vehicle_assignment(second.id, VehicleAssignmentStart(), db, users["fleet_manager"])
    assert conflict.value.status_code == 409
    assert "Vehicle" in conflict.value.detail


def test_prevents_conflicting_driver_assignments(db: Session, users):
    first_vehicle = make_vehicle(db, 104)
    second_vehicle = make_vehicle(db, 105)
    driver = make_driver(db, 105)
    first = create_scheduled(db, users["fleet_manager"], first_vehicle, driver)
    start_vehicle_assignment(first.id, VehicleAssignmentStart(), db, users["fleet_manager"])
    second = create_scheduled(db, users["fleet_manager"], second_vehicle, driver)

    with pytest.raises(HTTPException) as conflict:
        start_vehicle_assignment(second.id, VehicleAssignmentStart(), db, users["fleet_manager"])
    assert conflict.value.status_code == 409
    assert "Driver" in conflict.value.detail


def test_odometer_validation_rejects_lower_start_and_return_values(db: Session, users):
    vehicle = make_vehicle(db, 106, odometer=20_000)
    driver = make_driver(db, 106)
    scheduled = create_scheduled(db, users["fleet_manager"], vehicle, driver, start_odometer=19_999)

    with pytest.raises(HTTPException) as lower_start:
        start_vehicle_assignment(scheduled.id, VehicleAssignmentStart(), db, users["fleet_manager"])
    assert lower_start.value.status_code == 400

    assignment = db.get(VehicleAssignment, scheduled.id)
    assignment.start_odometer_km = 20_000
    db.commit()
    start_vehicle_assignment(scheduled.id, VehicleAssignmentStart(), db, users["fleet_manager"])
    with pytest.raises(HTTPException) as lower_end:
        complete_vehicle_assignment(
            scheduled.id,
            VehicleAssignmentComplete(
                end_datetime=(datetime.utcnow() + timedelta(hours=1)).isoformat(),
                end_odometer_km=19_999,
            ),
            db,
            users["fleet_manager"],
        )
    assert lower_end.value.status_code == 400


def test_archive_and_admin_restore_preserve_assignment_history(db: Session, users):
    vehicle = make_vehicle(db, 107)
    driver = make_driver(db, 107)
    scheduled = create_scheduled(db, users["fleet_manager"], vehicle, driver)

    archive_vehicle_assignment(scheduled.id, db, users["fleet_manager"])
    assert db.get(VehicleAssignment, scheduled.id).archived is True
    restored = restore_vehicle_assignment(scheduled.id, db, users["admin"])
    assert restored.archived is False
    assert db.get(VehicleAssignment, scheduled.id) is not None


def test_assignment_write_permissions_keep_viewers_read_only(users):
    dependency = require_roles(UserRole.admin, UserRole.fleet_manager)
    assert dependency(users["fleet_manager"]).id == users["fleet_manager"].id
    with pytest.raises(HTTPException) as denied:
        dependency(users["viewer"])
    assert denied.value.status_code == 403


def test_date_only_operational_records_resolve_the_assignment_active_that_day(db: Session, users):
    vehicle = make_vehicle(db, 108)
    driver = make_driver(db, 108)
    scheduled = create_scheduled(db, users["fleet_manager"], vehicle, driver)
    started_at = datetime.utcnow().replace(hour=12, minute=0, second=0, microsecond=0)
    start_vehicle_assignment(
        scheduled.id,
        VehicleAssignmentStart(start_datetime=started_at.isoformat()),
        db,
        users["fleet_manager"],
    )

    resolved = active_assignment_at(
        db,
        vehicle_id=vehicle.id,
        occurred_at=started_at.replace(hour=0),
    )
    assert resolved is not None
    assert resolved.id == scheduled.id
