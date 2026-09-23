from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.reservations import (
    add_reservation, approve, restore_reservation, update_status,
)
from app.db.session import Base, TenantSession, set_tenant_context
from app.models import Company, User, Vehicle, VehicleReservation
from app.schemas import AddReservation, ReservationStatusUpdate


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def manager(db):
    user = User(
        email="reservations@example.com", full_name="Reservation Manager",
        hashed_password="unused", role="fleet_manager", is_active=True,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def vehicle(db):
    row = Vehicle(
        brand="Toyota", model="Corolla", fuel_type="Petrol", vehicle_location="Depot",
        license_plate="01-111-AA", registration_country="XK", license_plate_normalized="01111AA",
    )
    db.add(row)
    db.commit()
    return row


def reservation(db, vehicle, *, status=0, archived=False, start=10, end=12):
    row = VehicleReservation(
        vehicle_id=vehicle.id, reserved_by="Driver", reservation_type="Business",
        start_date=datetime(2030, 1, start), end_date=datetime(2030, 1, end),
        status=status, archived=archived,
    )
    db.add(row)
    db.commit()
    return row


def create(db, manager, vehicle, *, start=10, end=12):
    return add_reservation(AddReservation(
        license_plate=vehicle.license_plate, reserved_by="Driver", reservation_type="Business",
        start_date=f"{start:02d}-01-2030", end_date=f"{end:02d}-01-2030",
    ), db, manager)


def assert_conflict(action):
    with pytest.raises(HTTPException) as error:
        action()
    assert error.value.status_code == 409


@pytest.mark.parametrize("status,blocks", [(0, True), (1, True), (2, False), (3, False), (4, False)])
def test_creation_blocks_only_pending_and_approved(db, manager, vehicle, status, blocks):
    reservation(db, vehicle, status=status)
    if blocks:
        assert_conflict(lambda: create(db, manager, vehicle))
    else:
        assert create(db, manager, vehicle)["id"]


@pytest.mark.parametrize("start,end,blocks", [
    (8, 9, False), (8, 10, True), (12, 14, True), (13, 14, False),
    (10, 10, True), (12, 12, True),
])
def test_inclusive_date_boundaries(db, manager, vehicle, start, end, blocks):
    reservation(db, vehicle)
    if blocks:
        assert_conflict(lambda: create(db, manager, vehicle, start=start, end=end))
    else:
        assert create(db, manager, vehicle, start=start, end=end)["id"]


def test_archived_reservation_does_not_block_creation(db, manager, vehicle):
    reservation(db, vehicle, status=1, archived=True)
    assert create(db, manager, vehicle)["id"]


def test_archived_vehicle_rejects_creation(db, manager, vehicle):
    vehicle.archived = True
    db.commit()
    with pytest.raises(HTTPException) as error:
        create(db, manager, vehicle)
    assert error.value.status_code == 400


def test_approve_rechecks_after_conflicting_reservation_is_created(db, manager, vehicle):
    old = reservation(db, vehicle, status=2)
    create(db, manager, vehicle)
    assert_conflict(lambda: approve(old.id, db, manager))
    db.refresh(old)
    assert old.status == 2


@pytest.mark.parametrize("initial,target", [(2, "Pending"), (3, "Approved")])
def test_status_reactivation_rechecks_conflicts(db, manager, vehicle, initial, target):
    old = reservation(db, vehicle, status=initial)
    create(db, manager, vehicle)
    assert_conflict(lambda: update_status(old.id, ReservationStatusUpdate(status=target), db, manager))
    db.refresh(old)
    assert old.status == initial


@pytest.mark.parametrize("target", ["Rejected", "Cancelled", "Completed"])
def test_status_change_to_nonblocking_releases_dates(db, manager, vehicle, target):
    old = reservation(db, vehicle)
    update_status(old.id, ReservationStatusUpdate(status=target), db, manager)
    assert create(db, manager, vehicle)["id"]


@pytest.mark.parametrize("status,blocks", [(0, True), (1, True), (2, False), (3, False), (4, False)])
def test_restore_rechecks_only_active_statuses(db, manager, vehicle, status, blocks):
    old = reservation(db, vehicle, status=status, archived=True)
    create(db, manager, vehicle)
    if blocks:
        assert_conflict(lambda: restore_reservation(old.id, db, manager))
        db.refresh(old)
        assert old.archived
    else:
        restore_reservation(old.id, db, manager)
        db.refresh(old)
        assert not old.archived


def test_completed_reservation_cannot_reopen(db, manager, vehicle):
    old = reservation(db, vehicle, status=4)
    assert_conflict(lambda: approve(old.id, db, manager))
    assert_conflict(lambda: update_status(old.id, ReservationStatusUpdate(status="Pending"), db, manager))


def test_overlap_is_tenant_scoped():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    seed = Session(engine)
    seed.add_all([Company(id=1, name="Alpha", slug="alpha"), Company(id=2, name="Beta", slug="beta")])
    alpha = Vehicle(
        company_id=1, brand="A", model="A", fuel_type="Petrol", vehicle_location="Depot",
        license_plate="01-112-AA", registration_country="XK", license_plate_normalized="01112AA",
    )
    beta = Vehicle(
        company_id=2, brand="B", model="B", fuel_type="Petrol", vehicle_location="Depot",
        license_plate="01-112-AA", registration_country="XK", license_plate_normalized="01112AA",
    )
    manager = User(
        company_id=1, email="alpha-manager@example.com", full_name="Alpha Manager",
        hashed_password="unused", role="fleet_manager", is_active=True,
    )
    seed.add_all([alpha, beta, manager])
    seed.flush()
    seed.add(VehicleReservation(
        company_id=2, vehicle_id=beta.id, reserved_by="Beta Driver", reservation_type="Business",
        start_date=datetime(2030, 1, 10), end_date=datetime(2030, 1, 12), status=1,
    ))
    seed.commit()
    alpha_id = alpha.id
    manager_id = manager.id
    seed.close()
    tenant_db = TenantSession(bind=engine)
    set_tenant_context(tenant_db, 1)
    try:
        tenant_manager = tenant_db.get(User, manager_id)
        assert create(tenant_db, tenant_manager, tenant_db.get(Vehicle, alpha_id))["id"]
        assert_conflict(lambda: create(tenant_db, tenant_manager, tenant_db.get(Vehicle, alpha_id)))
    finally:
        tenant_db.close()
        engine.dispose()
