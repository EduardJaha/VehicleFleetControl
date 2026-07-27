import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.inspections import create_inspection
from app.db.session import Base
from app.models import User, Vehicle
from app.schemas import InspectionCreate, InspectionItemCreate, InspectionItemStatus, InspectionType


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def admin_and_vehicle(db: Session) -> tuple[User, Vehicle]:
    admin = User(
        email="admin@example.com",
        full_name="Fleet Administrator",
        hashed_password="unused",
        role="admin",
        is_active=True,
    )
    vehicle = Vehicle(
        brand="Volkswagen",
        model="Golf",
        fuel_type="Diesel",
        vehicle_location="Pristina",
        license_plate="01-123-AA",
        registration_country="XK",
        license_plate_normalized="01123AA",
        status=0,
    )
    db.add_all([admin, vehicle])
    db.commit()
    return admin, vehicle


@pytest.mark.parametrize(
    "inspection_type",
    [InspectionType.general, InspectionType.monthly, InspectionType.random],
)
def test_new_inspection_types_can_be_saved_with_vehicle_id(
    db: Session,
    admin_and_vehicle: tuple[User, Vehicle],
    inspection_type: InspectionType,
):
    admin, vehicle = admin_and_vehicle

    result = create_inspection(
        InspectionCreate(
            vehicle_id=vehicle.id,
            inspection_type=inspection_type,
            inspection_date="27-07-2026",
            items=[
                InspectionItemCreate(
                    item_name="Brakes",
                    status=InspectionItemStatus.pass_,
                )
            ],
        ),
        db,
        admin,
    )

    assert result.vehicle_id == vehicle.id
    assert result.license_plate == vehicle.license_plate
    assert result.inspection_type == inspection_type
