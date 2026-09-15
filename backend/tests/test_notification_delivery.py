from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints.notifications import get_preferences, unread_count, update_preferences
from app.core.config import Settings
from app.db.session import Base, TenantSession, set_tenant_context
from app.models import (
    AccidentClaim, Company, CompanySettings, CompanyUser, Inspection, Notification, NotificationDelivery,
    NotificationPreference, User, Vehicle, VehicleAccident, WorkOrder,
)
from app.schemas import NotificationPreferenceItem, NotificationPreferencesUpdate
from app.services.email import render_notification_email
from app.services.notification_delivery import deliver_pending_emails
from app.services.notification_generation import scan_claims, scan_work_and_reservations
from app.services.notifications import notify_user
from app.services.scheduled_jobs import run_scheduled_job


def make_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(class_=TenantSession, bind=engine)
    seed = factory()
    seed.add_all([Company(id=1, name="Alpha", slug="alpha"), Company(id=2, name="Beta", slug="beta")])
    seed.flush()
    users = [
        User(id=1, company_id=1, email="admin@alpha.test", full_name="Alpha", hashed_password="x", role="admin", preferred_language="en"),
        User(id=2, company_id=2, email="admin@beta.test", full_name="Beta", hashed_password="x", role="admin", preferred_language="sq"),
    ]
    seed.add_all(users)
    seed.flush()
    seed.add_all([
        CompanySettings(company_id=1), CompanySettings(company_id=2),
        CompanyUser(company_id=1, user_id=1, role="admin", is_active=True),
        CompanyUser(company_id=2, user_id=2, role="admin", is_active=True),
    ])
    seed.commit()
    db = factory()
    set_tenant_context(db, 1)
    return db, factory, engine


def notification_kwargs(user_id=1):
    return dict(
        user_id=user_id, notification_type="Work Order overdue", title="Work order overdue",
        message="Repair brakes", priority="High", entity_type="WorkOrder", entity_id=7,
        deduplication_key=f"work-order:7:overdue:user:{user_id}",
        message_params={"plate": "01-123-AB", "date": "2026-09-14"},
    )


class CapturingEmail:
    def __init__(self, failures=0):
        self.failures = failures
        self.messages = []

    def send(self, **message):
        self.messages.append(message)
        if len(self.messages) <= self.failures:
            raise OSError("SMTP unavailable")


def test_email_preference_deduplication_and_albanian_template():
    db, _, engine = make_db()
    try:
        db.add(NotificationPreference(user_id=1, notification_type="Work Order overdue", email_enabled=True))
        db.flush()
        first = notify_user(db, **notification_kwargs())
        second = notify_user(db, **notification_kwargs())
        db.commit()
        assert first is second
        assert db.query(Notification).count() == 1
        assert db.query(NotificationDelivery).filter_by(channel="Email").count() == 1

        first.user.preferred_language = "sq"
        subject, text, _ = render_notification_email(first, "sq", "https://fleet.example")
        assert "Urdhrit të Punës" in subject
        assert "Përmbledhje" in text
        assert "https://fleet.example/work-orders/7" in text
    finally:
        db.close()
        engine.dispose()


def test_disabled_email_and_in_app_preferences_are_enforced():
    db, _, engine = make_db()
    try:
        payload = NotificationPreferencesUpdate(items=[NotificationPreferenceItem(
            notification_type="Work Order overdue", in_app_enabled=False, email_enabled=False,
        )])
        update_preferences(payload, db, db.get(User, 1))
        notify_user(db, **notification_kwargs())
        db.commit()
        assert db.query(NotificationDelivery).count() == 0
        assert unread_count(db, db.get(User, 1)).unread_count == 0
        saved = {row.notification_type: row for row in get_preferences(db, db.get(User, 1)).items}
        assert not saved["Work Order overdue"].email_enabled
        assert not saved["Work Order overdue"].in_app_enabled
    finally:
        db.close()
        engine.dispose()


def test_direct_notification_rejects_cross_tenant_recipient():
    db, _, engine = make_db()
    try:
        with pytest.raises(ValueError, match="active member"):
            notify_user(db, **notification_kwargs(user_id=2))
        assert db.query(Notification).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_retry_then_send_and_terminal_smtp_failure():
    db, _, engine = make_db()
    settings = Settings(email_backend="mock", email_max_attempts=2, email_retry_base_minutes=1)
    try:
        db.add(NotificationPreference(user_id=1, notification_type="Work Order overdue", email_enabled=True))
        db.flush()
        notify_user(db, **notification_kwargs())
        db.commit()
        now = datetime(2026, 9, 15, 10, 0)
        transport = CapturingEmail(failures=1)
        metrics = deliver_pending_emails(db, now=now, email_service=transport, settings=settings)
        delivery = db.query(NotificationDelivery).filter_by(channel="Email").one()
        assert metrics["retrying"] == 1
        assert delivery.status == "Retrying"
        assert delivery.next_attempt_at == now + timedelta(minutes=1)
        metrics = deliver_pending_emails(db, now=now + timedelta(minutes=1), email_service=transport, settings=settings)
        assert metrics["sent"] == 1
        assert delivery.status == "Sent"
        assert delivery.attempt_count == 2

        delivery.status = "Pending"
        delivery.attempt_count = 0
        delivery.sent_at = None
        db.flush()
        always_fails = CapturingEmail(failures=10)
        deliver_pending_emails(db, now=now, email_service=always_fails, settings=settings)
        deliver_pending_emails(db, now=now + timedelta(minutes=1), email_service=always_fails, settings=settings)
        assert delivery.status == "Failed"
        assert delivery.attempt_count == 2
        assert "SMTP unavailable" in delivery.failure_reason
    finally:
        db.close()
        engine.dispose()


def test_resolved_notification_is_not_emailed():
    db, _, engine = make_db()
    try:
        db.add(NotificationPreference(user_id=1, notification_type="Work Order overdue", email_enabled=True))
        db.flush()
        notification = notify_user(db, **notification_kwargs())
        notification.status = "Resolved"
        db.commit()
        transport = CapturingEmail()
        metrics = deliver_pending_emails(db, email_service=transport, settings=Settings(email_backend="mock"))
        delivery = db.query(NotificationDelivery).filter_by(channel="Email").one()
        assert metrics["cancelled"] == 1
        assert delivery.status == "Failed"
        assert not transport.messages
    finally:
        db.close()
        engine.dispose()


def test_scheduler_is_tenant_scoped_and_idempotent(monkeypatch):
    db, factory, engine = make_db()
    db.close()
    from app.services import scheduled_jobs

    def scan(session, _now):
        notify_user(session, **notification_kwargs(user_id=session.info["company_id"]))

    monkeypatch.setattr(scheduled_jobs, "SessionLocal", factory)
    monkeypatch.setitem(scheduled_jobs.SCAN_FUNCTIONS, "notification_scan", scan)
    try:
        first = run_scheduled_job("notification_scan", datetime(2026, 9, 15, 10, 0))
        second = run_scheduled_job("notification_scan", datetime(2026, 9, 15, 10, 15))
        check = factory()
        assert first["created"] == 2
        assert second["created"] == 0
        rows = check.query(Notification).execution_options(skip_tenant_scope=True).order_by(Notification.company_id).all()
        assert [(row.company_id, row.user_id) for row in rows] == [(1, 1), (2, 2)]
        check.close()
    finally:
        engine.dispose()


def test_archived_failed_inspection_and_critical_order_are_ignored(monkeypatch):
    db, _, engine = make_db()
    try:
        vehicle = Vehicle(
            brand="A", model="B", fuel_type="Diesel", vehicle_location="Depot",
            registration_country="XK", license_plate="01-123-AB", license_plate_normalized="01123AB",
        )
        db.add(vehicle)
        db.flush()
        db.add_all([
            Inspection(vehicle_id=vehicle.id, inspection_type="Safety", inspection_date=datetime.utcnow(), overall_status="Failed", archived=True),
            WorkOrder(vehicle_id=vehicle.id, title="Brakes", priority="Critical", status="Open", archived=True),
        ])
        db.commit()
        monkeypatch.setattr("app.services.inspection_templates.generate_scheduled", lambda *_args, **_kwargs: [])
        scan_work_and_reservations(db, datetime.utcnow())
        assert db.query(Notification).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_open_insurance_claim_is_reminded_and_then_resolved():
    db, _, engine = make_db()
    now = datetime(2026, 9, 15, 10, 0)
    try:
        vehicle = Vehicle(
            brand="A", model="B", fuel_type="Diesel", vehicle_location="Depot",
            registration_country="XK", license_plate="01-123-AB", license_plate_normalized="01123AB",
        )
        db.add(vehicle)
        db.flush()
        accident = VehicleAccident(
            vehicle_id=vehicle.id, accident_date=now - timedelta(days=20), location="Depot",
            severity="Minor", status="Reported", vehicle_available_after_accident=True,
        )
        db.add(accident)
        db.flush()
        claim = AccidentClaim(
            accident_id=accident.id, insurance_company="Insurer", policy_number="P-1",
            claim_number="C-1", claim_status="Open", claim_opened_date=now - timedelta(days=10),
        )
        db.add(claim)
        db.commit()
        scan_claims(db, now)
        db.commit()
        notice = db.query(Notification).filter_by(notification_type="Insurance claim reminder").one()
        assert notice.status == "Unread"
        claim.claim_status = "Closed"
        db.commit()
        scan_claims(db, now + timedelta(days=1))
        db.commit()
        assert notice.status == "Resolved"
    finally:
        db.close()
        engine.dispose()
