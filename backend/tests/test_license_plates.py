import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.vehicles import create_vehicle, list_vehicles, update_vehicle
from app.db.session import Base
from app.models import AuditLog, User, VehicleBrand, VehicleModel
from app.schemas import UserRole, VehicleCreate, VehicleUpdate
from app.services.license_plates import (
    PlateValidationError,
    RegistrationCountry,
    detect_registration_country,
    format_license_plate,
    normalize_license_plate,
    validate_license_plate,
)


@pytest.mark.parametrize(
    ("value", "formatted"),
    [
        ("AA 123 AA", "AA 123 AA"),
        ("AA123AA", "AA 123 AA"),
        ("aa123aa", "AA 123 AA"),
        ("AA-123-AA", "AA 123 AA"),
    ],
)
def test_albania_valid_inputs(value: str, formatted: str):
    assert validate_license_plate(RegistrationCountry.ALBANIA, value) == formatted
    assert normalize_license_plate(RegistrationCountry.ALBANIA, value) == "AA123AA"


@pytest.mark.parametrize(
    "value",
    ["A 123 AA", "AAA 123 AA", "AA 12 AA", "AA 123 A", "01-123-AB"],
)
def test_albania_invalid_shapes(value: str):
    with pytest.raises(PlateValidationError, match="Albania licence plates"):
        validate_license_plate(RegistrationCountry.ALBANIA, value)


@pytest.mark.parametrize(
    ("value", "formatted"),
    [
        ("01-123-AB", "01-123-AB"),
        ("01123AB", "01-123-AB"),
        ("01 123 ab", "01-123-AB"),
        ("01 123-AB", "01-123-AB"),
        ("01-101-AA", "01-101-AA"),
        ("07-999-ZA", "07-999-ZA"),
    ],
)
def test_kosovo_valid_inputs(value: str, formatted: str):
    assert validate_license_plate(RegistrationCountry.KOSOVO, value) == formatted


@pytest.mark.parametrize("value", ["00-123-AB", "08-123-AB"])
def test_kosovo_region_restrictions(value: str):
    with pytest.raises(PlateValidationError, match="region code"):
        validate_license_plate(RegistrationCountry.KOSOVO, value)


def test_kosovo_number_restriction():
    with pytest.raises(PlateValidationError, match="between 101 and 999"):
        validate_license_plate(RegistrationCountry.KOSOVO, "01-100-AB")


@pytest.mark.parametrize("letter", list("TRVWXY"))
def test_kosovo_disallowed_suffix_letters(letter: str):
    with pytest.raises(PlateValidationError, match="not allowed"):
        validate_license_plate(RegistrationCountry.KOSOVO, f"01-123-A{letter}")
    with pytest.raises(PlateValidationError, match="not allowed"):
        validate_license_plate(RegistrationCountry.KOSOVO, f"01-123-{letter}A")


def test_cross_country_formats_and_unsupported_characters_are_rejected():
    with pytest.raises(PlateValidationError):
        validate_license_plate(RegistrationCountry.ALBANIA, "01-123-AB")
    with pytest.raises(PlateValidationError):
        validate_license_plate(RegistrationCountry.KOSOVO, "AA 123 AA")
    with pytest.raises(PlateValidationError, match="only letters"):
        validate_license_plate(RegistrationCountry.ALBANIA, "AA/123/AA")


def test_format_and_detection():
    assert format_license_plate("AL", "AB456CD") == "AB 456 CD"
    assert format_license_plate("XK", "04567SU") == "04-567-SU"
    assert detect_registration_country("AA-123-AA") is RegistrationCountry.ALBANIA
    assert detect_registration_country("01 123 AB") is RegistrationCountry.KOSOVO
    assert detect_registration_country("unknown") is None


@pytest.fixture()
def vehicle_context():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    admin = User(
        email="admin@example.com",
        full_name="Admin",
        hashed_password="unused",
        role=UserRole.admin.value,
        is_active=True,
    )
    brand = VehicleBrand(name="Toyota", normalized_name="toyota", is_active=True)
    db.add_all([admin, brand])
    db.flush()
    model = VehicleModel(
        brand_id=brand.id,
        name="Corolla",
        normalized_name="corolla",
        is_active=True,
    )
    db.add(model)
    db.commit()
    yield db, admin, brand, model
    db.close()
    engine.dispose()


def payload(brand_id: int, model_id: int, country: str, plate: str):
    return VehicleCreate(
        brand_id=brand_id,
        model_id=model_id,
        registration_country=country,
        license_plate=plate,
        fuel_type="Hybrid",
        vehicle_location="Prishtina",
        status=0,
    )


def test_create_normalizes_and_duplicate_checks_by_country(vehicle_context):
    db, admin, brand, model = vehicle_context
    created = create_vehicle(payload(brand.id, model.id, "AL", "aa-123-aa"), db, admin)
    assert created.registration_country == RegistrationCountry.ALBANIA
    assert created.registration_country_name == "Albania"
    assert created.license_plate == "AA 123 AA"
    with pytest.raises(HTTPException) as duplicate:
        create_vehicle(payload(brand.id, model.id, "AL", "AA123AA"), db, admin)
    assert duplicate.value.status_code == 409
    assert "Albania" in duplicate.value.detail


def test_update_revalidates_country_and_records_registration_audit(vehicle_context):
    db, admin, brand, model = vehicle_context
    created = create_vehicle(payload(brand.id, model.id, "XK", "01 123 AB"), db, admin)
    changed = VehicleUpdate(
        **payload(brand.id, model.id, "AL", "AB456CD").model_dump()
    )
    updated = update_vehicle(created.id, changed, db, admin)
    assert updated.license_plate == "AB 456 CD"
    registration_audit = (
        db.query(AuditLog)
        .filter(AuditLog.action == "Vehicle registration changed")
        .one()
    )
    assert registration_audit.old_values == {
        "registration_country": "XK",
        "license_plate": "01-123-AB",
    }
    assert registration_audit.new_values == {
        "registration_country": "AL",
        "license_plate": "AB 456 CD",
    }


def test_separator_insensitive_search_and_country_filter(vehicle_context):
    db, admin, brand, model = vehicle_context
    create_vehicle(payload(brand.id, model.id, "XK", "04-567-SU"), db, admin)
    create_vehicle(payload(brand.id, model.id, "AL", "AC 001 ZZ"), db, admin)
    by_plate = list_vehicles(None, "04 567 su", None, None, None, False, db, admin)
    assert [row.license_plate for row in by_plate] == ["04-567-SU"]
    albania = list_vehicles(
        None,
        None,
        None,
        None,
        RegistrationCountry.ALBANIA,
        False,
        db,
        admin,
    )
    assert [row.license_plate for row in albania] == ["AC 001 ZZ"]
