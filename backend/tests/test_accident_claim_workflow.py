from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.v1.endpoints.accidents import (
    accident_detail,
    archive_accident,
    close_accident,
    close_claim,
    create_accident,
    create_accident_work_order,
    mark_vehicle_unavailable,
    open_claim,
    resolve_accident,
    restore_accident,
    update_claim,
)
from app.api.v1.endpoints.files import authorize_entity_access
from app.api.v1.endpoints.reports import accidents_report
from app.core.security import require_roles
from app.db.session import Base
from app.models import (
    AccidentFile,
    Attachment,
    AuditLog,
    Driver,
    Notification,
    User,
    Vehicle,
    VehicleAccident,
    VehicleAssignment,
    VehicleService,
    WorkOrder,
)
from app.schemas import (
    AccidentClaimPayload,
    AccidentCreate,
    AccidentWorkOrderPayload,
    UserRole,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def records(db: Session):
    users = {
        role: User(
            email=f"accident-{role}@example.com",
            full_name=role.replace("_", " ").title(),
            hashed_password="unused",
            role=role,
            is_active=True,
        )
        for role in ("admin", "fleet_manager", "mechanic", "finance", "viewer", "driver")
    }
    db.add_all(users.values())
    db.flush()
    vehicle = Vehicle(
        brand="Volvo", model="XC60", fuel_type="Hybrid", vehicle_location="Prishtina",
        license_plate="01-880-AA", registration_country="XK",
        license_plate_normalized="01880AA", status=0, odometer_km=50_000,
    )
    driver = Driver(
        full_name="Fleet Driver", employee_number="ACC-DRIVER-1", license_number="ACC-LIC-1",
        license_category="B", license_expiry_date=datetime.utcnow() + timedelta(days=365),
        status="Active", user_id=users["driver"].id,
    )
    db.add_all([vehicle, driver])
    db.flush()
    assignment = VehicleAssignment(
        vehicle_id=vehicle.id, driver_id=driver.id,
        start_datetime=datetime.utcnow() - timedelta(days=2),
        end_datetime=datetime.utcnow() + timedelta(days=1),
        start_odometer_km=49_000, end_odometer_km=50_000,
        status="Active",
    )
    db.add(assignment)
    db.commit()
    return users, vehicle, driver, assignment


def request() -> Request:
    return Request({
        "type": "http", "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": "/", "raw_path": b"/", "query_string": b"",
        "headers": [], "client": ("test", 123), "server": ("testserver", 80),
    })


def test_complete_accident_claim_repair_and_archive_workflow(db: Session, records):
    users, vehicle, driver, assignment = records
    created = create_accident(
        AccidentCreate(
            vehicle_id=vehicle.id,
            driver_id=driver.id,
            assignment_id=assignment.id,
            accident_datetime=datetime.utcnow().isoformat(),
            location="A2 motorway",
            severity="Severe",
            police_involved=True,
            police_report_number="POL-2026-88",
            description="Front-end collision",
            vehicle_available_after_accident=False,
            estimated_damage_cost=Decimal("5000.00"),
            fault_determination="Third Party",
        ),
        request(), db, users["fleet_manager"],
    )
    accident = db.get(VehicleAccident, created.id)
    assert accident.driver_id == driver.id
    assert accident.vehicle_assignment_id == assignment.id
    assert accident.status == "Reported"
    assert vehicle.status == 1
    assert not accident.vehicle_available_after_accident
    assert db.query(AuditLog).filter(AuditLog.action == "Accident reported").count() == 1
    assert db.query(Notification).filter(Notification.entity_id == accident.id).count() >= 1

    attachment = Attachment(
        original_filename="scene.jpg", stored_filename="accident-scene.jpg",
        storage_path="accidents/accident-scene.jpg", mime_type="image/jpeg", file_size=1234,
        uploaded_by=users["fleet_manager"].id, entity_type="VehicleAccident", entity_id=accident.id,
    )
    db.add(attachment)
    db.flush()
    legacy = AccidentFile(vehicle_accident_id=accident.id, file_path=f"/api/v1/files/{attachment.id}/download")
    db.add(legacy)
    db.commit()

    claim_payload = AccidentClaimPayload(
        insurance_company="Fleet Mutual",
        policy_number="POLICY-77",
        claim_number="CLAIM-2026-99",
        claim_status="Open",
        claim_opened_date=datetime.utcnow().isoformat(),
        deductible=Decimal("500.00"),
        adjuster_name="Alex Adjuster",
    )
    open_claim(accident.id, claim_payload, db, users["finance"])
    db.refresh(accident)
    assert accident.status == "Claim Opened"
    assert accident.claim.deductible == Decimal("500.00")

    work_order_result = create_accident_work_order(
        accident.id,
        AccidentWorkOrderPayload(title="Repair collision damage", priority="Critical"),
        db,
        users["mechanic"],
    )
    order = db.get(WorkOrder, work_order_result["id"])
    assert order.accident_id == accident.id
    assert order.source == "Accident"
    assert accident.status == "Repair In Progress"

    order.status = "Completed"
    order.total_cost = Decimal("4500.00")
    service = VehicleService(
        vehicle_id=vehicle.id, work_order_id=order.id, service_type="Accident Repair",
        service_date=datetime.utcnow(), cost=Decimal("4500.00"), source="Work Order", status="Completed",
    )
    db.add(service)
    db.commit()

    settled = claim_payload.model_copy(update={
        "claim_status": "Settled",
        "settlement_amount": Decimal("3500.00"),
    })
    update_claim(accident.id, settled, db, users["finance"])
    close_claim(accident.id, db, users["finance"])
    resolve_accident(accident.id, db, users["fleet_manager"])
    db.refresh(accident)
    assert accident.status == "Resolved"
    assert accident.actual_damage_cost == Decimal("4500.00")
    assert accident.resolved_at is not None
    close_accident(accident.id, db, users["fleet_manager"])
    assert accident.status == "Closed"

    detail = accident_detail(accident.id, request(), db, users["fleet_manager"])
    assert detail["claim"]["settlement_amount"] == "3500.00"
    assert detail["work_orders"][0]["service"]["id"] == service.id
    assert detail["attachments"][0]["original_filename"] == "scene.jpg"
    assert detail["files"] == [f"/api/v1/files/{attachment.id}/download"]
    assert any(item["action"] == "Accident resolved" for item in detail["timeline"])

    report = accidents_report(db)
    assert report["kpis"]["total_accidents"] == 1
    assert report["kpis"]["claim_cost"] == 3500.0
    assert report["kpis"]["unrecovered_cost"] == 1000.0
    assert report["kpis"]["accident_rate_per_100000_km"] == 100.0
    assert report["by_driver"] == [{"driver": driver.full_name, "accidents": 1}]
    assert report["by_vehicle"] == [{"license_plate": vehicle.license_plate, "accidents": 1}]
    assert report["fault_distribution"] == [{"fault": "Third Party", "accidents": 1}]

    archive_accident(accident.id, db, users["fleet_manager"])
    assert accident.archived
    restore_accident(accident.id, db, users["admin"])
    assert not accident.archived
    assert db.get(Attachment, attachment.id) is not None
    assert db.get(AccidentFile, legacy.id) is not None


def test_workflow_guards_permissions_and_driver_attachment_scope(db: Session, records):
    users, vehicle, driver, assignment = records
    created = create_accident(
        AccidentCreate(
            vehicle_id=vehicle.id, driver_id=driver.id, assignment_id=assignment.id,
            accident_datetime=datetime.utcnow().isoformat(), location="Depot",
            severity="Minor", vehicle_available_after_accident=True,
        ),
        request(), db, users["admin"],
    )
    accident = db.get(VehicleAccident, created.id)

    with pytest.raises(HTTPException) as permission:
        require_roles(UserRole.admin, UserRole.fleet_manager)(users["viewer"])
    assert permission.value.status_code == 403
    with pytest.raises(HTTPException) as transition:
        resolve_accident(accident.id, db, users["fleet_manager"])
    assert transition.value.status_code == 409

    authorize_entity_access(db, users["driver"], "VehicleAccident", accident)
    other_driver = Driver(
        full_name="Other Driver", employee_number="ACC-DRIVER-2", license_number="ACC-LIC-2",
        license_category="B", license_expiry_date=datetime.utcnow() + timedelta(days=365), status="Active",
    )
    db.add(other_driver)
    db.flush()
    accident.driver_id = other_driver.id
    db.commit()
    with pytest.raises(HTTPException) as denied:
        authorize_entity_access(db, users["driver"], "VehicleAccident", accident)
    assert denied.value.status_code == 403

    mark_vehicle_unavailable(accident.id, db, users["fleet_manager"])
    assert vehicle.status == 1
    assert accident.status == "Under Review"


def test_accident_workflow_translations_are_bilingual():
    locale_root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n" / "locales"
    english = json.loads((locale_root / "en" / "modules.json").read_text())
    albanian = json.loads((locale_root / "sq" / "modules.json").read_text())
    for key in ("summary", "people", "claim", "repair", "attachments", "timeline"):
        assert english["accidents"]["tabs"][key]
        assert albanian["accidents"]["tabs"][key]
        assert english["accidents"]["tabs"][key] != albanian["accidents"]["tabs"][key]
    for key in (
        "accident_reported", "vehicle_unavailable_after_accident",
        "insurance_claim_opened", "insurance_claim_closed", "accident_resolved",
    ):
        assert english["notificationContent"][key]["title"]
        assert albanian["notificationContent"][key]["title"]
