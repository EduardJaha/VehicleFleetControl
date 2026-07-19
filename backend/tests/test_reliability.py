import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile

from app.api.v1.endpoints.audit_logs import list_audit_logs
from app.api.v1.endpoints.files import download_file
from app.api.v1.endpoints.notifications import dismiss, mark_read, unread_count
from app.api.v1.endpoints.reports import vehicle_costs_report
from app.api.v1.endpoints.vehicles import delete_vehicle, list_vehicles, restore_vehicle
from app.api.v1.endpoints.work_orders import complete_work_order, update_work_order_status
from app.core.security import require_roles
from app.db.session import Base
from app.main import app
from app.models import Attachment, AuditLog, Notification, User, Vehicle, VehicleService, WorkOrder
from app.schemas import (
    UserRole,
    WorkOrderCompletionRequest,
    WorkOrderStatus,
    WorkOrderStatusUpdate,
)
from app.services.audit import record_audit
from app.services.notifications import notify_user
from app.utils import files as file_utils


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
            email=f"{role}@example.com",
            full_name=role.replace("_", " ").title(),
            hashed_password="unused",
            role=role,
            is_active=True,
        )
        for role in ("admin", "fleet_manager", "mechanic", "finance", "viewer")
    }
    db.add_all(rows.values())
    db.commit()
    return rows


def vehicle_and_order(db: Session, *, odometer: int = 100_000) -> tuple[Vehicle, WorkOrder]:
    sequence = 555 + db.query(Vehicle).count()
    vehicle = Vehicle(
        brand="Toyota", model="Corolla", fuel_type="Hybrid",
        vehicle_location="Belgrade", license_plate=f"01-{sequence:03d}-AA",
        registration_country="XK", license_plate_normalized=f"01{sequence:03d}AA",
        status=0, odometer_km=odometer,
    )
    db.add(vehicle)
    db.flush()
    order = WorkOrder(
        vehicle_id=vehicle.id, source="Manual", title="Scheduled maintenance",
        priority="High", status="In Progress", created_at=datetime.utcnow() - timedelta(days=2),
    )
    db.add(order)
    db.commit()
    return vehicle, order


def completion_payload(**overrides) -> WorkOrderCompletionRequest:
    data = {
        "actual_completion_date": datetime.utcnow().strftime("%d-%m-%Y"),
        "completed_odometer_km": 100_250,
        "workshop": "Fleet Workshop",
        "labor_cost": Decimal("12.34"),
        "parts_cost": Decimal("87.66"),
        "completion_notes": "Completed and checked.",
        "create_service_record": True,
        "service_type": "General Service",
        "service_description": "Scheduled maintenance",
        "next_service_km_interval": 10_000,
        "resolve_source_reminder": True,
    }
    data.update(overrides)
    return WorkOrderCompletionRequest(**data)


def test_complete_work_order_with_service_is_atomic_and_decimal_safe(db: Session, users):
    vehicle, order = vehicle_and_order(db)
    result = complete_work_order(order.id, completion_payload(), db, users["mechanic"])

    assert result.work_order.status == WorkOrderStatus.completed
    assert result.work_order.total_cost == Decimal("100.00")
    assert result.service is not None
    assert result.next_reminder_created is True
    service = db.query(VehicleService).filter(VehicleService.work_order_id == order.id).one()
    assert service.cost == Decimal("100.00")
    assert service.next_service_odometer_km == 110_250
    assert db.get(Vehicle, vehicle.id).odometer_km == 100_250
    assert db.query(AuditLog).filter(AuditLog.action == "Work Order completed").count() == 1
    assert db.query(Notification).filter(Notification.notification_type == "Work Order completed").count() >= 1


def test_complete_without_service_creates_no_service_or_reminder(db: Session, users):
    _, order = vehicle_and_order(db)
    result = complete_work_order(
        order.id,
        completion_payload(create_service_record=False, service_type=None, next_service_km_interval=None),
        db,
        users["mechanic"],
    )
    assert result.service is None
    assert result.next_reminder_created is False
    assert db.query(VehicleService).filter(VehicleService.work_order_id == order.id).count() == 0


def test_duplicate_completion_and_generic_completion_are_blocked(db: Session, users):
    _, order = vehicle_and_order(db)
    complete_work_order(order.id, completion_payload(), db, users["mechanic"])
    with pytest.raises(HTTPException) as duplicate:
        complete_work_order(order.id, completion_payload(), db, users["mechanic"])
    assert duplicate.value.status_code == 409

    _, second = vehicle_and_order(db, odometer=200_000)
    with pytest.raises(HTTPException) as generic:
        update_work_order_status(
            second.id,
            WorkOrderStatusUpdate(status=WorkOrderStatus.completed),
            db,
            users["mechanic"],
        )
    assert generic.value.status_code == 409


def test_lower_odometer_and_negative_cost_are_rejected(db: Session, users):
    _, order = vehicle_and_order(db)
    with pytest.raises(HTTPException) as lower:
        complete_work_order(order.id, completion_payload(completed_odometer_km=99_999), db, users["mechanic"])
    assert lower.value.status_code == 400
    with pytest.raises(ValueError):
        completion_payload(labor_cost=Decimal("-0.01"))


def test_source_reminder_is_resolved(db: Session, users):
    vehicle, order = vehicle_and_order(db)
    reminder = VehicleService(
        vehicle_id=vehicle.id, service_type="General Service", service_date=datetime.utcnow() - timedelta(days=300),
        odometer_km=90_000, next_service_km_interval=10_000, next_service_odometer_km=100_000,
        source="Manual", status="Completed", reminder_status="Overdue",
    )
    db.add(reminder)
    db.flush()
    order.reminder_service_id = reminder.id
    order.source = "Service Reminder"
    db.commit()

    result = complete_work_order(order.id, completion_payload(), db, users["mechanic"])
    assert result.reminder_resolved is True
    assert db.get(VehicleService, reminder.id).reminder_status == "Resolved"


def test_completion_rolls_back_when_required_step_fails(db: Session, users, monkeypatch):
    _, order = vehicle_and_order(db)

    def fail_notifications(*args, **kwargs):
        raise RuntimeError("notification storage failed")

    monkeypatch.setattr("app.services.work_order_completion.notify_roles", fail_notifications)
    with pytest.raises(RuntimeError):
        complete_work_order(order.id, completion_payload(), db, users["mechanic"])
    db.expire_all()
    unchanged = db.get(WorkOrder, order.id)
    assert unchanged.status == "In Progress"
    assert db.query(VehicleService).filter(VehicleService.work_order_id == order.id).count() == 0


def test_role_permissions_enforce_viewer_read_only(users):
    dependency = require_roles(UserRole.admin, UserRole.fleet_manager, UserRole.mechanic)
    assert dependency(users["admin"]).id == users["admin"].id
    assert dependency(users["mechanic"]).id == users["mechanic"].id
    with pytest.raises(HTTPException) as denied:
        dependency(users["viewer"])
    assert denied.value.status_code == 403


def test_vehicle_delete_archives_and_admin_can_restore(db: Session, users):
    vehicle, order = vehicle_and_order(db)
    delete_vehicle(vehicle.id, db, users["fleet_manager"])
    assert db.get(Vehicle, vehicle.id) is not None
    assert db.get(Vehicle, vehicle.id).archived is True
    assert db.get(WorkOrder, order.id) is not None
    assert list_vehicles(None, None, None, None, None, False, db, users["viewer"]) == []
    archived = list_vehicles(None, None, None, None, None, True, db, users["admin"])
    assert [row.id for row in archived] == [vehicle.id]
    restored = restore_vehicle(vehicle.id, db, users["admin"])
    assert restored.archived is False


def test_audit_redacts_sensitive_values_and_filters(db: Session, users):
    record_audit(
        db, action="User updated", entity_type="User", entity_id=users["viewer"].id,
        user=users["admin"],
        old_values={"role": "viewer", "hashed_password": "never-log-this"},
        new_values={"role": "finance", "access_token": "never-log-this"},
        description="Role changed.",
    )
    db.commit()
    row = db.query(AuditLog).one()
    assert "hashed_password" not in (row.old_values or {})
    assert "access_token" not in (row.new_values or {})
    page = list_audit_logs(
        None, "User updated", "User", users["viewer"].id,
        None, None, "Role changed", 1, 50, db, users["admin"],
    )
    assert page.total == 1
    assert page.items[0].created_at.endswith("+00:00")
    with pytest.raises(HTTPException):
        require_roles(UserRole.admin, UserRole.fleet_manager)(users["viewer"])


def test_notifications_deduplicate_and_transitions_are_user_scoped(db: Session, users):
    kwargs = dict(
        user_id=users["admin"].id, notification_type="Work Order overdue",
        title="Overdue", message="WO #1", priority="High",
        entity_type="WorkOrder", entity_id=1, deduplication_key="work-order:1:overdue:user:1",
    )
    first = notify_user(db, **kwargs)
    second = notify_user(db, **kwargs)
    db.commit()
    assert first is second
    assert db.query(Notification).count() == 1
    assert unread_count(db, users["admin"]).unread_count == 1
    assert unread_count(db, users["viewer"]).unread_count == 0
    assert mark_read(first.id, db, users["admin"]).status.value == "Read"
    assert dismiss(first.id, db, users["admin"]).status.value == "Dismissed"
    with pytest.raises(HTTPException):
        mark_read(first.id, db, users["viewer"])


def test_numeric_sorting_and_aggregation_use_database_numeric_types(db: Session):
    vehicle = Vehicle(
        brand="A", model="B", fuel_type="Diesel", vehicle_location="Belgrade",
        registration_country="XK", license_plate="01-777-AA",
        license_plate_normalized="01777AA", status=0,
    )
    db.add(vehicle)
    db.flush()
    db.add_all([
        VehicleService(vehicle_id=vehicle.id, service_type="Other", service_date=datetime.utcnow(), cost=Decimal("9.99")),
        VehicleService(vehicle_id=vehicle.id, service_type="Other", service_date=datetime.utcnow(), cost=Decimal("100.01")),
    ])
    db.commit()
    values = [row.cost for row in db.query(VehicleService).order_by(VehicleService.cost).all()]
    assert values == [Decimal("9.99"), Decimal("100.01")]
    assert db.query(func.sum(VehicleService.cost)).scalar() == Decimal("110.00")


def test_linked_service_and_work_order_cost_are_not_double_counted(db: Session):
    vehicle, order = vehicle_and_order(db)
    order.status = "Completed"
    order.actual_completion_date = datetime.utcnow()
    order.total_cost = Decimal("100.00")
    service = VehicleService(
        vehicle_id=vehicle.id, work_order_id=order.id, service_type="General Service",
        service_date=datetime.utcnow(), cost=Decimal("100.00"), source="Work Order", status="Completed",
    )
    db.add(service)
    db.commit()
    report = vehicle_costs_report(db)
    row = report["rows"][0]
    assert row["service_cost"] == 100.0
    assert row["work_order_cost"] == 0.0
    assert row["total_cost"] == 100.0


def upload(filename: str, mime: str, content: bytes) -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=filename, headers=Headers({"content-type": mime}))


def test_secure_upload_accepts_pdf_and_image_and_uses_uuid_names(tmp_path, monkeypatch):
    monkeypatch.setattr(file_utils.settings, "upload_directory", str(tmp_path))
    pdf = asyncio.run(file_utils.store_upload(upload("../../invoice.pdf", "application/pdf", b"%PDF-1.7\nbody"), "documents", "document"))
    image = asyncio.run(file_utils.store_upload(upload("photo.png", "image/png", b"\x89PNG\r\n\x1a\ncontent"), "images", "image"))
    assert pdf.original_filename == "invoice.pdf"
    assert ".." not in pdf.storage_path
    assert pdf.stored_filename != pdf.original_filename
    assert image.mime_type == "image/png"


def test_secure_upload_rejects_bad_extension_mime_content_and_size(tmp_path, monkeypatch):
    monkeypatch.setattr(file_utils.settings, "upload_directory", str(tmp_path))
    with pytest.raises(HTTPException) as extension:
        asyncio.run(file_utils.store_upload(upload("script.exe", "application/pdf", b"%PDF-1.7"), category="document"))
    assert extension.value.status_code == 415
    with pytest.raises(HTTPException) as mime:
        asyncio.run(file_utils.store_upload(upload("file.pdf", "text/plain", b"%PDF-1.7"), category="document"))
    assert mime.value.status_code == 415
    with pytest.raises(HTTPException) as content:
        asyncio.run(file_utils.store_upload(upload("file.pdf", "application/pdf", b"not-a-pdf"), category="document"))
    assert content.value.status_code == 415
    monkeypatch.setattr(file_utils.settings, "max_document_size", 4)
    with pytest.raises(HTTPException) as oversized:
        asyncio.run(file_utils.store_upload(upload("file.pdf", "application/pdf", b"%PDF-123456"), category="document"))
    assert oversized.value.status_code == 413


def test_private_download_requires_authentication_and_serves_authorized_file(db: Session, users, tmp_path, monkeypatch):
    monkeypatch.setattr(file_utils.settings, "upload_directory", str(tmp_path))
    vehicle, order = vehicle_and_order(db)
    stored = asyncio.run(file_utils.store_upload(
        upload("invoice.pdf", "application/pdf", b"%PDF-1.7\nbody"),
        "workorder", "document",
    ))
    attachment = Attachment(
        original_filename=stored.original_filename, stored_filename=stored.stored_filename,
        storage_path=stored.storage_path, mime_type=stored.mime_type, file_size=stored.file_size,
        uploaded_by=users["admin"].id, entity_type="WorkOrder", entity_id=order.id,
    )
    db.add(attachment)
    db.commit()
    response = download_file(attachment.id, db, users["admin"])
    assert response.media_type == "application/pdf"
    assert str(response.path).endswith(stored.stored_filename)

    client = TestClient(app)
    assert client.get(f"/api/v1/files/{attachment.id}/download").status_code == 401
