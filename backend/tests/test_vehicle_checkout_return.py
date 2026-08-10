from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.files import ENTITY_MODELS, authorize_entity_access
from app.api.v1.endpoints.vehicle_assignments import checkout_vehicle, return_vehicle
from app.core.security import require_roles
from app.db.session import Base
from app.models import (
    AuditLog,
    Driver,
    Inspection,
    Notification,
    User,
    Vehicle,
    VehicleAccident,
    VehicleAssignment,
    VehicleConditionRecord,
    VehicleReservation,
    WorkOrder,
)
from app.schemas import UserRole, VehicleCheckoutCreate, VehicleReturnCreate


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def fleet_manager(db: Session) -> User:
    user = User(
        email="checkout-manager@example.com",
        full_name="Checkout Manager",
        hashed_password="unused",
        role="fleet_manager",
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def make_vehicle(db: Session, sequence: int, *, status: int = 0, odometer: int = 10_000) -> Vehicle:
    vehicle = Vehicle(
        brand="Toyota",
        model="Corolla",
        fuel_type="Hybrid",
        vehicle_location="Prishtina",
        license_plate=f"01-{sequence:03d}-AA",
        registration_country="XK",
        license_plate_normalized=f"01{sequence:03d}AA",
        status=status,
        odometer_km=odometer,
    )
    db.add(vehicle)
    db.commit()
    return vehicle


def make_driver(db: Session, sequence: int) -> Driver:
    driver = Driver(
        full_name=f"Driver {sequence}",
        employee_number=f"EMP-CHECKOUT-{sequence}",
        license_number=f"LIC-CHECKOUT-{sequence}",
        license_category="B",
        license_expiry_date=datetime.utcnow() + timedelta(days=365),
        status="Active",
    )
    db.add(driver)
    db.commit()
    return driver


def checkout_payload(vehicle: Vehicle, driver: Driver, **changes) -> VehicleCheckoutCreate:
    values = {
        "vehicle_id": vehicle.id,
        "driver_id": driver.id,
        "checkout_datetime": datetime.utcnow().isoformat(),
        "starting_odometer_km": vehicle.odometer_km or 0,
        "energy_level": 80,
        "vehicle_condition": "Good",
        "existing_damage": "Small scratch on rear bumper",
        "documents_handed_over": ["Registration", "Insurance"],
        "purpose": "Customer visit",
        "destination": "Peja",
        "notes": "Call fleet desk if plans change.",
    }
    values.update(changes)
    return VehicleCheckoutCreate(**values)


def return_payload(assignment: VehicleAssignment, **changes) -> VehicleReturnCreate:
    values = {
        "return_datetime": (assignment.start_datetime + timedelta(hours=4)).isoformat(),
        "ending_odometer_km": assignment.start_odometer_km + 120,
        "energy_level": 40,
        "vehicle_condition": "Good",
        "driver_comments": "Returned normally.",
    }
    values.update(changes)
    return VehicleReturnCreate(**values)


def test_valid_checkout_marks_vehicle_assigned_and_records_audit_notification(db: Session, fleet_manager: User):
    vehicle = make_vehicle(db, 201)
    driver = make_driver(db, 201)

    result = checkout_vehicle(checkout_payload(vehicle, driver), db, fleet_manager)

    assert result.assignment.status.value == "Active"
    assert result.condition_record.record_type.value == "Checkout"
    assert result.assignment.destination == "Peja"
    assert result.assignment.documents_handed_over == ["Registration", "Insurance"]
    assert db.get(Vehicle, vehicle.id).status == 4
    assert db.get(Driver, driver.id).assigned_vehicle_id == vehicle.id
    assert db.query(AuditLog).filter(AuditLog.action == "Vehicle checked out").count() == 1
    assert db.query(Notification).filter(
        Notification.notification_type == "Check-out completed",
        Notification.deduplication_key.like("vehicle-usage:%:checkout-completed:%"),
    ).count() == 1


def test_checkout_and_return_continue_the_same_scheduled_assignment(db: Session, fleet_manager: User):
    vehicle = make_vehicle(db, 214)
    driver = make_driver(db, 214)
    scheduled = VehicleAssignment(
        vehicle_id=vehicle.id,
        driver_id=driver.id,
        assigned_by_user_id=fleet_manager.id,
        start_datetime=datetime.utcnow() + timedelta(hours=1),
        start_odometer_km=vehicle.odometer_km,
        purpose="Customer visit",
        status="Scheduled",
    )
    db.add(scheduled)
    db.commit()

    checked_out = checkout_vehicle(
        checkout_payload(vehicle, driver, assignment_id=scheduled.id),
        db,
        fleet_manager,
    )

    assert checked_out.assignment.id == scheduled.id
    assert checked_out.assignment.status.value == "Active"
    assert db.query(VehicleAssignment).count() == 1
    assert db.query(VehicleAssignment).filter(VehicleAssignment.status == "Scheduled").count() == 0

    assignment = db.get(VehicleAssignment, scheduled.id)
    returned = return_vehicle(assignment.id, return_payload(assignment), db, fleet_manager)
    assert returned.assignment.id == scheduled.id
    assert returned.assignment.status.value == "Completed"
    assert db.query(VehicleAssignment).count() == 1


def test_unavailable_vehicle_and_driver_conflict_are_rejected(db: Session, fleet_manager: User):
    unavailable = make_vehicle(db, 202, status=1)
    driver = make_driver(db, 202)
    with pytest.raises(HTTPException) as unavailable_error:
        checkout_vehicle(checkout_payload(unavailable, driver), db, fleet_manager)
    assert unavailable_error.value.status_code == 409

    first_vehicle = make_vehicle(db, 203)
    second_vehicle = make_vehicle(db, 204)
    checkout_vehicle(checkout_payload(first_vehicle, driver), db, fleet_manager)
    with pytest.raises(HTTPException) as driver_error:
        checkout_vehicle(checkout_payload(second_vehicle, driver), db, fleet_manager)
    assert driver_error.value.status_code == 409
    assert "Driver" in driver_error.value.detail


def test_reservation_must_be_approved_and_match_vehicle(db: Session, fleet_manager: User):
    vehicle = make_vehicle(db, 205)
    other_vehicle = make_vehicle(db, 206)
    driver = make_driver(db, 205)
    reservation = VehicleReservation(
        vehicle_id=vehicle.id,
        reserved_by="Driver 205",
        reservation_type="Business Trip",
        start_date=datetime.utcnow() - timedelta(hours=1),
        end_date=datetime.utcnow() + timedelta(hours=6),
        status=0,
    )
    db.add(reservation)
    db.commit()

    with pytest.raises(HTTPException) as pending_error:
        checkout_vehicle(checkout_payload(vehicle, driver, reservation_id=reservation.id), db, fleet_manager)
    assert pending_error.value.status_code == 409

    reservation.status = 1
    db.commit()
    with pytest.raises(HTTPException) as vehicle_error:
        checkout_vehicle(checkout_payload(other_vehicle, driver, reservation_id=reservation.id), db, fleet_manager)
    assert vehicle_error.value.status_code in {400, 409}


def test_valid_return_restores_vehicle_and_completes_reservation(db: Session, fleet_manager: User):
    vehicle = make_vehicle(db, 207)
    driver = make_driver(db, 207)
    reservation = VehicleReservation(
        vehicle_id=vehicle.id,
        reserved_by=driver.full_name,
        reservation_type="Business Trip",
        start_date=datetime.utcnow() - timedelta(hours=1),
        end_date=datetime.utcnow() + timedelta(hours=6),
        status=1,
    )
    db.add(reservation)
    db.commit()
    checked_out = checkout_vehicle(
        checkout_payload(vehicle, driver, reservation_id=reservation.id),
        db,
        fleet_manager,
    )
    assignment = db.get(VehicleAssignment, checked_out.assignment.id)

    result = return_vehicle(assignment.id, return_payload(assignment), db, fleet_manager)

    assert result.assignment.status.value == "Completed"
    assert result.condition_record.record_type.value == "Return"
    assert db.get(Vehicle, vehicle.id).odometer_km == assignment.start_odometer_km + 120
    assert db.get(Vehicle, vehicle.id).status == 0
    assert db.get(Driver, driver.id).assigned_vehicle_id is None
    assert db.get(VehicleReservation, reservation.id).status == 4


def test_lower_return_odometer_is_rejected_without_partial_changes(db: Session, fleet_manager: User):
    vehicle = make_vehicle(db, 208)
    driver = make_driver(db, 208)
    checked_out = checkout_vehicle(checkout_payload(vehicle, driver), db, fleet_manager)
    assignment = db.get(VehicleAssignment, checked_out.assignment.id)

    with pytest.raises(HTTPException) as error:
        return_vehicle(
            assignment.id,
            return_payload(assignment, ending_odometer_km=assignment.start_odometer_km - 1),
            db,
            fleet_manager,
        )
    assert error.value.status_code == 400
    assert db.get(VehicleAssignment, assignment.id).status == "Active"
    assert db.query(VehicleConditionRecord).filter(
        VehicleConditionRecord.vehicle_assignment_id == assignment.id,
        VehicleConditionRecord.record_type == "Return",
    ).count() == 0


def test_damage_return_can_create_inspection_accident_and_work_order(db: Session, fleet_manager: User):
    vehicle = make_vehicle(db, 209)
    driver = make_driver(db, 209)
    checked_out = checkout_vehicle(checkout_payload(vehicle, driver), db, fleet_manager)
    assignment = db.get(VehicleAssignment, checked_out.assignment.id)

    result = return_vehicle(
        assignment.id,
        return_payload(
            assignment,
            vehicle_condition="Damaged",
            new_damage="Dent on passenger door",
            return_inspection_required=True,
            create_accident=True,
            create_work_order=True,
        ),
        db,
        fleet_manager,
    )

    assert db.get(Inspection, result.inspection_id).vehicle_assignment_id == assignment.id
    assert db.get(VehicleAccident, result.accident_id).vehicle_assignment_id == assignment.id
    assert db.get(WorkOrder, result.work_order_id).reported_issue == "Dent on passenger door"
    assert db.query(Notification).filter(
        Notification.notification_type == "Vehicle returned with new damage"
    ).count() == 1


def test_checkout_rolls_back_all_records_when_commit_fails(db: Session, fleet_manager: User, monkeypatch):
    vehicle = make_vehicle(db, 210)
    driver = make_driver(db, 210)

    def fail_commit():
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError):
        checkout_vehicle(checkout_payload(vehicle, driver), db, fleet_manager)

    assert db.query(VehicleAssignment).count() == 0
    assert db.query(VehicleConditionRecord).count() == 0
    assert db.query(AuditLog).count() == 0
    assert db.query(Notification).count() == 0
    assert db.get(Vehicle, vehicle.id).status == 0


def test_return_rolls_back_completion_and_follow_up_records_when_commit_fails(
    db: Session,
    fleet_manager: User,
    monkeypatch,
):
    vehicle = make_vehicle(db, 213)
    driver = make_driver(db, 213)
    checked_out = checkout_vehicle(checkout_payload(vehicle, driver), db, fleet_manager)
    assignment = db.get(VehicleAssignment, checked_out.assignment.id)

    def fail_commit():
        raise RuntimeError("simulated return commit failure")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError):
        return_vehicle(
            assignment.id,
            return_payload(
                assignment,
                new_damage="Cracked mirror",
                return_inspection_required=True,
                create_accident=True,
                create_work_order=True,
            ),
            db,
            fleet_manager,
        )

    assert db.get(VehicleAssignment, assignment.id).status == "Active"
    assert db.get(Vehicle, vehicle.id).status == 4
    assert db.query(Inspection).count() == 0
    assert db.query(VehicleAccident).count() == 0
    assert db.query(WorkOrder).count() == 0
    assert db.query(VehicleConditionRecord).filter(
        VehicleConditionRecord.record_type == "Return"
    ).count() == 0


def test_checkout_permissions_and_secure_condition_attachments(fleet_manager: User):
    dependency = require_roles(UserRole.admin, UserRole.fleet_manager)
    assert dependency(fleet_manager).id == fleet_manager.id
    assert ENTITY_MODELS["VehicleConditionRecord"] is VehicleConditionRecord


def test_driver_cannot_access_another_drivers_condition_attachments(db: Session, fleet_manager: User):
    vehicle = make_vehicle(db, 211)
    assigned_driver = make_driver(db, 211)
    other_driver = make_driver(db, 212)
    other_user = User(
        email="other-driver@example.com",
        full_name=other_driver.full_name,
        hashed_password="unused",
        role="driver",
        is_active=True,
    )
    db.add(other_user)
    db.flush()
    other_driver.user_id = other_user.id
    db.commit()
    result = checkout_vehicle(checkout_payload(vehicle, assigned_driver), db, fleet_manager)
    condition = db.get(VehicleConditionRecord, result.condition_record.id)

    with pytest.raises(HTTPException) as denied:
        authorize_entity_access(db, other_user, "VehicleConditionRecord", condition)
    assert denied.value.status_code == 403
