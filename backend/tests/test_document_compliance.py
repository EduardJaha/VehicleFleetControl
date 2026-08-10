from datetime import date, datetime, timedelta
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.compliance import (
    _authorize_document,
    archive_document,
    restore_document,
    verify_version,
)
from app.api.v1.endpoints.reports import document_compliance_report
from app.core.security import require_roles
from app.db.session import Base
from app.models import (
    AuditLog,
    DocumentRequirement,
    DocumentVersion,
    Driver,
    Notification,
    User,
    Vehicle,
    VehiclePaper,
)
from app.schemas import DocumentVerificationRequest, UserRole
from app.services.document_compliance import compliance_dashboard, document_status
from app.services.notification_generation import generate_time_based_notifications


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
            email=f"compliance-{role}@example.com",
            full_name=role.replace("_", " ").title(),
            hashed_password="unused",
            role=role,
            is_active=True,
        )
        for role in ("admin", "fleet_manager", "viewer", "driver")
    }
    db.add_all(rows.values())
    db.commit()
    return rows


def add_vehicle(db: Session, *, country: str, sequence: int, category: str | None = None) -> Vehicle:
    vehicle = Vehicle(
        brand="Toyota",
        model="Corolla",
        fuel_type="Hybrid",
        vehicle_location="Pristina" if country == "XK" else "Tirana",
        vehicle_category=category,
        license_plate=f"01-{sequence:03d}-AA" if country == "XK" else f"AB-{sequence:03d}-CD",
        registration_country=country,
        license_plate_normalized=f"01{sequence:03d}AA" if country == "XK" else f"AB{sequence:03d}CD",
        status=0,
    )
    db.add(vehicle)
    db.flush()
    return vehicle


def add_requirement(db: Session, document_type: str, **scope) -> DocumentRequirement:
    row = DocumentRequirement(
        document_type=document_type,
        warning_days=scope.pop("warning_days", 30),
        required=True,
        is_active=True,
        **scope,
    )
    db.add(row)
    db.flush()
    return row


def test_global_country_category_and_driver_requirements_are_applied(db: Session, users):
    kosovo = add_vehicle(db, country="XK", sequence=111, category="Leased")
    albania = add_vehicle(db, country="AL", sequence=222)
    driver = Driver(
        full_name="Ada Driver",
        employee_number="D-1",
        license_number="LIC-1",
        license_category="B",
        license_expiry_date=datetime.utcnow() + timedelta(days=365),
        department="Operations",
        assigned_vehicle_id=kosovo.id,
        user_id=users["driver"].id,
    )
    db.add(driver)
    add_requirement(db, "Registration", applies_to_driver=False)
    add_requirement(db, "Kosovo registration documentation", applies_to_driver=False, applies_to_country="XK")
    add_requirement(db, "Lease Agreement", applies_to_driver=False, applies_to_vehicle_category="Leased")
    add_requirement(db, "Driving Licence", applies_to_driver=True)
    db.commit()

    result = compliance_dashboard(db)
    missing = {(row["owner_name"], row["document_type"]) for row in result["missing_required"]}
    assert (kosovo.license_plate, "Registration") in missing
    assert (albania.license_plate, "Registration") in missing
    assert (kosovo.license_plate, "Kosovo registration documentation") in missing
    assert (albania.license_plate, "Kosovo registration documentation") not in missing
    assert (kosovo.license_plate, "Lease Agreement") in missing
    assert ("Ada Driver", "Driving Licence") in missing


def test_lifecycle_statuses_include_all_compliance_states(db: Session):
    vehicle = add_vehicle(db, country="XK", sequence=333)
    requirement = add_requirement(db, "Insurance", applies_to_driver=False, warning_days=30)
    db.flush()
    now = datetime.utcnow()
    paper = VehiclePaper(
        vehicle_id=vehicle.id,
        requirement_id=requirement.id,
        document_type="Insurance",
        file_path="/secure/1",
        issue_date=now - timedelta(days=30),
        expiry_date=now + timedelta(days=20),
    )
    db.add(paper)
    db.flush()
    version = DocumentVersion(
        document_id=paper.id,
        version_number=1,
        file_path="/secure/1",
        issue_date=paper.issue_date,
        expiry_date=paper.expiry_date,
        renewal_status="Approved",
        is_current=True,
    )
    db.add(version)
    db.commit()

    assert document_status(None, None) == "Missing"
    assert document_status(paper, version, warning_days=30) == "Expiring Soon"
    version.expiry_date = now - timedelta(days=1)
    assert document_status(paper, version) == "Expired"
    version.renewal_status = "In Progress"
    assert document_status(paper, version) == "Renewal In Progress"
    version.renewal_status = "Rejected"
    version.rejection_reason = "Unreadable"
    assert document_status(paper, version) == "Rejected"
    paper.archived = True
    assert document_status(paper, version) == "Archived"


def test_version_history_keeps_previous_file_and_one_current_version(db: Session, users):
    vehicle = add_vehicle(db, country="XK", sequence=444)
    requirement = add_requirement(db, "Registration", applies_to_driver=False)
    paper = VehiclePaper(
        vehicle_id=vehicle.id,
        requirement_id=requirement.id,
        document_type="Registration",
        file_path="/api/v1/files/2/download",
        issue_date=datetime.utcnow(),
        expiry_date=datetime.utcnow() + timedelta(days=365),
    )
    db.add(paper)
    db.flush()
    original = DocumentVersion(
        document_id=paper.id,
        version_number=1,
        file_path="/api/v1/files/1/download",
        issue_date=datetime.utcnow() - timedelta(days=365),
        expiry_date=datetime.utcnow(),
        uploaded_by=users["admin"].id,
        renewal_status="Approved",
        is_current=False,
    )
    renewal = DocumentVersion(
        document_id=paper.id,
        version_number=2,
        file_path="/api/v1/files/2/download",
        issue_date=datetime.utcnow(),
        expiry_date=datetime.utcnow() + timedelta(days=365),
        uploaded_by=users["fleet_manager"].id,
        renewal_status="In Progress",
        is_current=True,
    )
    db.add_all([original, renewal])
    db.commit()

    rows = db.query(DocumentVersion).filter(DocumentVersion.document_id == paper.id).order_by(DocumentVersion.version_number).all()
    assert [row.file_path for row in rows] == ["/api/v1/files/1/download", "/api/v1/files/2/download"]
    assert sum(1 for row in rows if row.is_current) == 1
    assert rows[0].uploaded_by == users["admin"].id


def test_verification_preserves_verifier_timestamp_and_rejection_reason(db: Session, users):
    vehicle = add_vehicle(db, country="XK", sequence=555)
    requirement = add_requirement(db, "Insurance", applies_to_driver=False)
    paper = VehiclePaper(
        vehicle_id=vehicle.id,
        requirement_id=requirement.id,
        document_type="Insurance",
        file_path="/secure",
        issue_date=datetime.utcnow(),
        expiry_date=datetime.utcnow() + timedelta(days=365),
    )
    db.add(paper)
    db.flush()
    version = DocumentVersion(
        document_id=paper.id,
        version_number=1,
        file_path="/secure",
        issue_date=paper.issue_date,
        expiry_date=paper.expiry_date,
        renewal_status="Submitted",
        is_current=True,
    )
    db.add(version)
    db.commit()

    result = verify_version(
        version.id,
        DocumentVerificationRequest(approved=False, rejection_reason="Name does not match"),
        db,
        users["fleet_manager"],
    )
    assert result.renewal_status.value == "Rejected"
    assert result.verified_by == users["fleet_manager"].id
    assert result.verified_at is not None
    assert result.rejection_reason == "Name does not match"
    assert db.query(AuditLog).filter(AuditLog.entity_type == "DocumentVersion").count() == 1


def test_compliance_notifications_are_deduplicated_and_resolve(db: Session, users):
    vehicle = add_vehicle(db, country="XK", sequence=666)
    requirement = add_requirement(db, "Insurance", applies_to_driver=False)
    db.commit()

    first = generate_time_based_notifications(db)
    db.commit()
    second = generate_time_based_notifications(db)
    db.commit()
    alerts = db.query(Notification).filter(Notification.notification_type == "Document compliance missing").all()
    assert first >= 1
    assert second == 0
    assert len(alerts) == 2  # Admin and Fleet Manager, one stable alert each.

    paper = VehiclePaper(
        vehicle_id=vehicle.id,
        requirement_id=requirement.id,
        document_type="Insurance",
        file_path="/secure",
        issue_date=datetime.utcnow(),
        expiry_date=datetime.utcnow() + timedelta(days=365),
        renewal_status="Approved",
    )
    db.add(paper)
    db.commit()
    generate_time_based_notifications(db)
    db.commit()
    assert all(row.status == "Resolved" for row in alerts)


def test_driver_file_access_is_owner_scoped(db: Session, users):
    vehicle = add_vehicle(db, country="XK", sequence=777)
    own_driver = Driver(
        full_name="Own Driver", employee_number="D-OWN", license_number="L-OWN",
        license_category="B", license_expiry_date=datetime.utcnow() + timedelta(days=365),
        user_id=users["driver"].id,
    )
    other_driver = Driver(
        full_name="Other Driver", employee_number="D-OTHER", license_number="L-OTHER",
        license_category="B", license_expiry_date=datetime.utcnow() + timedelta(days=365),
    )
    db.add_all([own_driver, other_driver])
    db.flush()
    own = VehiclePaper(
        driver_id=own_driver.id, document_type="Driving Licence", file_path="/own",
        issue_date=datetime.utcnow(), expiry_date=datetime.utcnow() + timedelta(days=365),
    )
    other = VehiclePaper(
        driver_id=other_driver.id, document_type="Driving Licence", file_path="/other",
        issue_date=datetime.utcnow(), expiry_date=datetime.utcnow() + timedelta(days=365),
    )
    vehicle_document = VehiclePaper(
        vehicle_id=vehicle.id, document_type="Registration", file_path="/vehicle",
        issue_date=datetime.utcnow(), expiry_date=datetime.utcnow() + timedelta(days=365),
    )
    db.add_all([own, other, vehicle_document])
    db.commit()
    db.refresh(users["driver"])

    _authorize_document(db, users["driver"], own)
    with pytest.raises(HTTPException) as denied:
        _authorize_document(db, users["driver"], other)
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException):
        _authorize_document(db, users["driver"], vehicle_document)
    _authorize_document(db, users["viewer"], other)


def test_permissions_archive_restore_audit_report_and_translations(db: Session, users):
    vehicle = add_vehicle(db, country="XK", sequence=888)
    requirement = add_requirement(db, "Registration", applies_to_driver=False)
    paper = VehiclePaper(
        vehicle_id=vehicle.id, requirement_id=requirement.id,
        document_type="Registration", file_path="/secure",
        issue_date=datetime.utcnow(), expiry_date=datetime.utcnow() + timedelta(days=365),
    )
    db.add(paper)
    db.commit()

    with pytest.raises(HTTPException):
        require_roles(UserRole.admin, UserRole.fleet_manager)(users["viewer"])
    archive_document(paper.id, db, users["fleet_manager"])
    assert db.get(VehiclePaper, paper.id).archived is True
    restore_document(paper.id, db, users["admin"])
    assert db.get(VehiclePaper, paper.id).archived is False
    assert db.query(AuditLog).filter(AuditLog.entity_id == paper.id).count() == 2

    report = document_compliance_report(db)
    assert report["kpis"]["requirement_count"] == 1
    assert report["rows"][0]["status"] == "Valid"

    locale_root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n" / "locales"
    english = json.loads((locale_root / "en" / "modules.json").read_text())
    albanian = json.loads((locale_root / "sq" / "modules.json").read_text())
    for key in ("title", "missing", "expired", "renew", "history", "warningDays"):
        assert english["documentCompliance"][key]
        assert albanian["documentCompliance"][key]
        assert english["documentCompliance"][key] != albanian["documentCompliance"][key]
