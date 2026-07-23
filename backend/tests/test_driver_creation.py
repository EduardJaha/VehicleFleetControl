from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.auth import list_users
from app.api.v1.endpoints.drivers import create_driver
from app.db.session import Base
from app.models import User
from app.schemas import DriverCreate


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
        email="fleet-manager@example.com",
        full_name="Fleet Manager",
        hashed_password="unused",
        role="fleet_manager",
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def driver_payload(**overrides) -> DriverCreate:
    values = {
        "full_name": "New Driver",
        "employee_number": "EMP-NEW",
        "license_number": "LIC-NEW",
        "license_category": "B",
        "license_expiry_date": (datetime.utcnow() + timedelta(days=365)).strftime("%d-%m-%Y"),
        "status": "Active",
    }
    values.update(overrides)
    return DriverCreate(**values)


def test_invalid_linked_account_returns_specific_error_code(db: Session, fleet_manager: User):
    with pytest.raises(HTTPException) as error:
        create_driver(
            driver_payload(user_id=1_284_439_524),
            db,
            fleet_manager,
        )

    assert error.value.status_code == 404
    assert error.value.detail["code"] == "linked_user_not_found"


def test_invalid_assigned_vehicle_returns_specific_error_code(db: Session, fleet_manager: User):
    with pytest.raises(HTTPException) as error:
        create_driver(
            driver_payload(assigned_license_plate="01-417-EH"),
            db,
            fleet_manager,
        )

    assert error.value.status_code == 404
    assert error.value.detail["code"] == "assigned_vehicle_not_found"


def test_user_options_endpoint_returns_existing_login_accounts(db: Session, fleet_manager: User):
    rows = list_users(db, fleet_manager)
    assert [(row.id, row.email) for row in rows] == [
        (fleet_manager.id, fleet_manager.email)
    ]
