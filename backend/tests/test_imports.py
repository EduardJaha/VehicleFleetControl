import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.imports import authorize_job
from app.core.config import get_settings
from app.db.session import Base
from app.models import AuditLog, Driver, ImportJob, ImportRowResult, User, Vehicle, VehicleBrand, VehicleModel
from app.schemas import ImportTransactionMode, ImportUpdateMode
from app.services import imports as import_service
from app.services.imports import confirm_job, error_report, parse_import_bytes, store_import, template_bytes, validate_job


@pytest.fixture()
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIRECTORY", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    admin = User(email="admin@example.com", full_name="Admin", hashed_password="unused", role="admin", is_active=True)
    manager = User(email="manager@example.com", full_name="Manager", hashed_password="unused", role="fleet_manager", is_active=True)
    other = User(email="other@example.com", full_name="Other", hashed_password="unused", role="fleet_manager", is_active=True)
    brand = VehicleBrand(name="Toyota", normalized_name="toyota", is_active=True)
    db.add_all([admin, manager, other, brand])
    db.flush()
    model = VehicleModel(brand_id=brand.id, name="Corolla", normalized_name="corolla", is_active=True)
    db.add(model)
    db.commit()
    yield db, admin, manager, other
    db.close()
    engine.dispose()
    get_settings.cache_clear()


def upload_job(db: Session, user: User, entity_type: str, text: str, filename: str = "import.csv") -> ImportJob:
    upload = UploadFile(filename=filename, file=BytesIO(text.encode("utf-8")))
    return asyncio.run(store_import(upload, entity_type, user, db))


VEHICLE_HEADER = "Country,Plate,Brand,Model,Fuel,Location,VIN,Odometer,Status\n"
VEHICLE_MAPPING = {
    "registration_country": "Country",
    "license_plate": "Plate",
    "brand": "Brand",
    "model": "Model",
    "fuel_type": "Fuel",
    "vehicle_location": "Location",
    "vin_number": "VIN",
    "odometer_km": "Odometer",
    "status": "Status",
}


def test_csv_validation_rejects_unsafe_shapes_and_large_files():
    with pytest.raises(HTTPException, match="Only .csv"):
        parse_import_bytes(b"a,b\n1,2", ".xls")
    with pytest.raises(HTTPException, match="unique"):
        parse_import_bytes(b"Plate, plate \nA,B", ".csv")
    too_many = b"Name\n" + (b"row\n" * 20_001)
    with pytest.raises(HTTPException, match="more than 20000"):
        parse_import_bytes(too_many, ".csv")


def test_localized_csv_and_excel_templates_are_parseable():
    sq_csv, csv_name, _ = template_bytes("Drivers", "sq", "csv")
    headers, rows = parse_import_bytes(sq_csv, ".csv")
    assert csv_name.endswith("-sq.csv")
    assert "Emri i Plotë" in headers
    assert rows[0]["Data e Skadimit të Patentës"] == "31-12-2027"
    xlsx, xlsx_name, _ = template_bytes("Vehicles", "en", "xlsx")
    xlsx_headers, xlsx_rows = parse_import_bytes(xlsx, ".xlsx")
    assert xlsx_name.endswith(".xlsx")
    assert xlsx_headers[0] == "Registration Country"
    assert xlsx_rows[0]["Year"] == 2025


def test_vehicle_dry_run_detects_file_and_database_duplicates(context):
    db, admin, _, _ = context
    existing = Vehicle(
        brand="Toyota", model="Corolla", brand_id=1, model_id=1, fuel_type="Petrol",
        vehicle_location="Prishtina", registration_country="XK", license_plate="01-123-AB",
        license_plate_normalized="01123AB", vin_number="EXISTINGVIN", status=0,
    )
    db.add(existing)
    db.commit()
    job = upload_job(
        db, admin, "Vehicles",
        VEHICLE_HEADER
        + "XK,01-123-AB,Toyota,Corolla,Petrol,Prishtina,NEWVIN,1000,Active\n"
        + "XK,02-222-AA,Toyota,Corolla,Petrol,Prishtina,SAMEVIN,1000,Active\n"
        + "XK,03-333-AA,Toyota,Corolla,Petrol,Prishtina,SAMEVIN,1000,Active\n",
    )
    result = validate_job(db, job, VEHICLE_MAPPING, ImportUpdateMode.create_only)
    assert result.status == "Ready"
    assert result.valid_rows == 0
    assert result.invalid_rows == 3
    rows = db.query(ImportRowResult).filter_by(import_job_id=job.id).order_by(ImportRowResult.row_number).all()
    assert any(error["code"] == "duplicate_existing" for error in rows[0].errors)
    assert all(any(error["code"] == "duplicate_in_file" for error in row.errors) for row in rows[1:])
    albanian_report = error_report(result, rows, "sq").decode("utf-8-sig")
    assert "Kodet e Gabimeve" in albanian_report
    assert "më shumë se një herë" in albanian_report
    assert db.query(Vehicle).count() == 1  # dry run performs no target writes


def test_explicit_update_mode_updates_without_silent_overwrite(context):
    db, admin, _, _ = context
    existing = Vehicle(
        brand="Toyota", model="Corolla", brand_id=1, model_id=1, fuel_type="Petrol",
        vehicle_location="Old", registration_country="XK", license_plate="01-123-AB",
        license_plate_normalized="01123AB", vin_number="VIN1", odometer_km=10, status=0,
    )
    db.add(existing)
    db.commit()
    job = upload_job(db, admin, "Vehicles", VEHICLE_HEADER + "XK,01-123-AB,Toyota,Corolla,Hybrid,New,VIN1,2500,In Service\n")
    validate_job(db, job, VEHICLE_MAPPING, ImportUpdateMode.update_existing)
    result = confirm_job(db, job, admin, ImportUpdateMode.update_existing, ImportTransactionMode.file)
    db.refresh(existing)
    assert result.status == "Completed"
    assert result.updated_rows == 1
    assert existing.vehicle_location == "New"
    assert existing.odometer_km == 2500
    assert db.query(AuditLog).filter(AuditLog.action == "Import confirmed").count() == 1
    assert db.query(AuditLog).filter(AuditLog.action == "Vehicle imported (updated)").count() == 1


def test_driver_date_email_and_employee_duplicates(context):
    db, admin, _, _ = context
    db.add(Driver(
        full_name="Existing", employee_number="EMP-1", email="driver@example.com",
        license_number="LIC-1", license_category="B", license_expiry_date=import_service.datetime(2028, 1, 1), status="Active",
    ))
    db.commit()
    text = (
        "Name,Employee,Email,Licence,Category,Expiry,Status\n"
        "Updated,EMP-1,DRIVER@example.com,LIC-1,B,2028-12-31,Suspended\n"
    )
    mapping = {
        "full_name": "Name", "employee_number": "Employee", "email": "Email",
        "license_number": "Licence", "license_category": "Category",
        "license_expiry_date": "Expiry", "status": "Status",
    }
    job = upload_job(db, admin, "Drivers", text)
    validate_job(db, job, mapping, ImportUpdateMode.update_existing)
    result = confirm_job(db, job, admin, ImportUpdateMode.update_existing, ImportTransactionMode.row)
    driver = db.query(Driver).one()
    assert result.updated_rows == 1
    assert driver.email == "driver@example.com"
    assert driver.status == "Suspended"
    assert driver.license_expiry_date.strftime("%d-%m-%Y") == "31-12-2028"


def test_row_transactions_keep_successes_and_file_transactions_roll_back(context, monkeypatch):
    db, admin, _, _ = context
    text = (
        VEHICLE_HEADER
        + "XK,01-111-AA,Toyota,Corolla,Petrol,A,VIN-A,100,Active\n"
        + "XK,02-222-AA,Toyota,Corolla,Petrol,B,VIN-B,200,Active\n"
    )
    original = import_service._apply_row
    calls = {"count": 0}

    def fail_second(db_arg, job_arg, row_arg, user_arg):
        calls["count"] += 1
        if calls["count"] == 2:
            raise IntegrityError("forced", {}, Exception("changed data"))
        return original(db_arg, job_arg, row_arg, user_arg)

    job = upload_job(db, admin, "Vehicles", text)
    validate_job(db, job, VEHICLE_MAPPING, ImportUpdateMode.create_only)
    monkeypatch.setattr(import_service, "_apply_row", fail_second)
    partial = confirm_job(db, job, admin, ImportUpdateMode.create_only, ImportTransactionMode.row)
    assert partial.status == "Completed With Errors"
    assert partial.created_rows == 1
    assert partial.skipped_rows == 1
    assert db.query(Vehicle).count() == 1

    calls["count"] = 0
    text2 = text.replace("VIN-A", "VIN-C").replace("VIN-B", "VIN-D").replace("01-111-AA", "03-333-AA").replace("02-222-AA", "04-444-AA")
    atomic_job = upload_job(db, admin, "Vehicles", text2)
    validate_job(db, atomic_job, VEHICLE_MAPPING, ImportUpdateMode.create_only)
    atomic = confirm_job(db, atomic_job, admin, ImportUpdateMode.create_only, ImportTransactionMode.file)
    assert atomic.status == "Failed"
    assert atomic.created_rows == 0
    assert db.query(Vehicle).count() == 1


def test_job_owner_boundary_and_admin_access(context):
    db, admin, manager, other = context
    job = upload_job(db, manager, "Vehicles", VEHICLE_HEADER + "XK,01-111-AA,Toyota,Corolla,Petrol,A,VIN-A,100,Active\n")
    assert authorize_job(job, manager) is job
    assert authorize_job(job, admin) is job
    with pytest.raises(HTTPException) as denied:
        authorize_job(job, other)
    assert denied.value.status_code == 403
