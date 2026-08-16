from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.v1.endpoints.audit_logs import list_audit_logs
from app.api.v1.endpoints.admin import get_company_logo
from app.api.v1.endpoints.auth import register_company_admin
from app.api.v1.endpoints.dashboard import filtered as filtered_dashboard
from app.api.v1.endpoints.files import download_file
from app.api.v1.endpoints.imports import get_import
from app.api.v1.endpoints.notifications import unread_count
from app.api.v1.endpoints.reports import build_excel, fleet_summary_report
from app.api.v1.endpoints.vehicles import list_vehicles
from app.core.authorization import has_permission
from app.core.security import create_access_token, get_current_user
from app.db.session import Base, TenantMixin, TenantSession, set_tenant_context
from app.models import (
    Attachment, AuditLog, Company, CompanySettings, CompanyUser, ImportJob,
    Notification, User, Vehicle,
)
from app.services.notifications import notify_roles
from app.schemas import FirstAdminCreate


@pytest.fixture()
def tenant_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    seed = Session(engine)
    first = Company(id=1, name="Alpha Fleet", slug="alpha")
    second = Company(id=2, name="Beta Fleet", slug="beta")
    admin = User(
        company_id=1, email="admin@alpha.test", full_name="Alpha Admin",
        hashed_password="unused", role="admin", is_active=True,
    )
    outsider = User(
        company_id=2, email="admin@beta.test", full_name="Beta Admin",
        hashed_password="unused", role="admin", is_active=True,
    )
    seed.add_all([first, second, CompanySettings(company=first), CompanySettings(company=second), admin, outsider])
    seed.flush()
    seed.add_all([
        CompanyUser(company_id=1, user_id=admin.id, role="admin", is_default=True),
        CompanyUser(company_id=2, user_id=admin.id, role="viewer", is_default=False),
        CompanyUser(company_id=2, user_id=outsider.id, role="admin", is_default=True),
    ])
    alpha_vehicle = Vehicle(
        company_id=1, brand="Alpha", model="One", fuel_type="Petrol", vehicle_location="Shared Depot",
        license_plate="01-111-AA", registration_country="XK", license_plate_normalized="01111AA",
    )
    beta_vehicle = Vehicle(
        company_id=2, brand="Beta", model="Two", fuel_type="Diesel", vehicle_location="Shared Depot",
        license_plate="01-111-AA", registration_country="XK", license_plate_normalized="01111AA",
    )
    seed.add_all([alpha_vehicle, beta_vehicle]); seed.flush()
    alpha_audit = AuditLog(company_id=1, user_id=admin.id, username=admin.email, action="Alpha", entity_type="Vehicle", entity_id=alpha_vehicle.id)
    beta_audit = AuditLog(company_id=2, user_id=outsider.id, username=outsider.email, action="Beta", entity_type="Vehicle", entity_id=beta_vehicle.id)
    alpha_notification = Notification(company_id=1, user_id=admin.id, notification_type="Test", title="Alpha", message="Alpha", priority="Medium", status="Unread", deduplication_key="same-key")
    beta_notification = Notification(company_id=2, user_id=outsider.id, notification_type="Test", title="Beta", message="Beta", priority="Medium", status="Unread", deduplication_key="same-key")
    alpha_import = ImportJob(company_id=1, entity_type="Vehicles", filename="alpha.csv", source_path="alpha.csv", uploaded_by=admin.id, status="Uploaded")
    beta_import = ImportJob(company_id=2, entity_type="Vehicles", filename="beta.csv", source_path="beta.csv", uploaded_by=outsider.id, status="Uploaded")
    beta_file = Attachment(company_id=2, original_filename="secret.pdf", stored_filename="secret.pdf", storage_path="uploads/secret.pdf", mime_type="application/pdf", file_size=10, uploaded_by=outsider.id, entity_type="VehicleService", entity_id=999)
    seed.add_all([alpha_audit, beta_audit, alpha_notification, beta_notification, alpha_import, beta_import, beta_file])
    seed.commit()
    ids = {
        "admin": admin.id, "outsider": outsider.id,
        "alpha_vehicle": alpha_vehicle.id, "beta_vehicle": beta_vehicle.id,
        "beta_import": beta_import.id, "beta_file": beta_file.id,
    }
    seed.close()

    db = TenantSession(bind=engine)
    set_tenant_context(db, 1)
    yield db, ids, engine
    db.close()
    engine.dispose()


def test_every_business_model_query_has_a_company_predicate(tenant_db):
    db, _, engine = tenant_db
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        tenant_models = sorted(
            (mapper.class_ for mapper in Base.registry.mappers if issubclass(mapper.class_, TenantMixin)),
            key=lambda model: model.__name__,
        )
        assert tenant_models
        for model in tenant_models:
            statements.clear()
            db.query(model).limit(1).all()
            sql = " ".join(statements)
            assert "CompanyId" in sql, f"{model.__name__} was queried without tenant SQL"
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def test_direct_ids_lists_filters_reports_and_exports_are_tenant_scoped(tenant_db):
    db, ids, _ = tenant_db
    admin = db.get(User, ids["admin"])

    assert db.get(Vehicle, ids["beta_vehicle"]) is None
    listed = list_vehicles(None, None, None, None, None, False, db, admin)
    assert [row.id for row in listed] == [ids["alpha_vehicle"]]
    dashboard = filtered_dashboard(None, "Shared Depot", db)
    assert dashboard["total_vehicles"] == 1
    report = fleet_summary_report(db)
    assert [row["brand"] for row in report["rows"]] == ["Alpha"]
    workbook = build_excel("fleet-summary", report)
    assert b"Beta" not in workbook.getvalue()


def test_files_imports_notifications_and_audit_logs_reject_cross_tenant_access(tenant_db):
    db, ids, _ = tenant_db
    admin = db.get(User, ids["admin"])

    with pytest.raises(HTTPException) as file_error:
        download_file(ids["beta_file"], db, admin)
    assert file_error.value.status_code == 404

    with pytest.raises(HTTPException) as import_error:
        get_import(ids["beta_import"], None, 200, db, admin)
    assert import_error.value.status_code == 404

    assert unread_count(db, admin).unread_count == 1
    logs = list_audit_logs(None, None, None, None, None, None, None, 1, 50, db, admin)
    assert logs.total == 1
    assert logs.items[0].action == "Alpha"


def test_company_logo_lookup_uses_the_active_tenant(tenant_db, monkeypatch):
    db, _, _ = tenant_db
    alpha_settings = db.query(CompanySettings).first()
    alpha_settings.logo_path = "alpha/logo.png"
    db.commit()
    monkeypatch.setattr("app.api.v1.endpoints.admin.attachment_path", lambda path: path)

    response = get_company_logo(db, db.query(User).first())

    assert response.path == "alpha/logo.png"
    assert response.headers["cache-control"] == "private, no-store"


def test_background_notification_generation_only_targets_active_tenant_users(tenant_db):
    db, ids, _ = tenant_db
    created = notify_roles(
        db,
        roles={"admin"},
        notification_type="Tenant background test",
        title="Scoped",
        message="Scoped",
        priority="Medium",
        entity_type="Vehicle",
        entity_id=ids["alpha_vehicle"],
        deduplication_key="background-scope",
    )
    db.commit()
    assert [row.user_id for row in created] == [ids["admin"]]
    assert all(row.company_id == 1 for row in created)


def test_company_aware_uniques_allow_same_business_identifier_in_two_companies(tenant_db):
    db, ids, _ = tenant_db
    # Fixture creation itself proves the same normalized registration can exist
    # in both tenants. Each tenant still sees exactly its own record.
    assert db.query(Vehicle).filter(Vehicle.license_plate_normalized == "01111AA").count() == 1
    assert db.get(Vehicle, ids["alpha_vehicle"]) is not None


def test_bulk_orm_deletes_cannot_cross_the_tenant_boundary(tenant_db):
    db, _, engine = tenant_db
    assert db.query(Vehicle).delete(synchronize_session=False) == 1
    db.commit()
    with engine.connect() as connection:
        remaining = connection.exec_driver_sql('SELECT "CompanyId" FROM "Vehicles"').scalars().all()
    assert remaining == [2]


def test_company_membership_role_is_authoritative_after_switching(tenant_db):
    _db, ids, engine = tenant_db
    switched = TenantSession(bind=engine)
    try:
        user = get_current_user(create_access_token(ids["admin"], company_id=2), switched)
        assert switched.info["company_id"] == 2
        assert switched.info["company_role"] == "viewer"
        assert has_permission(switched, user, "vehicles.view")
        assert not has_permission(switched, user, "users.manage")
    finally:
        switched.close()


def test_public_registration_onboards_multiple_isolated_companies():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        responses = []
        for company_name, email in (("Alpha", "owner@alpha.test"), ("Beta", "owner@beta.test")):
            db = TenantSession(bind=engine)
            try:
                responses.append(register_company_admin(FirstAdminCreate(
                    company_name=company_name,
                    email=email,
                    full_name=f"{company_name} Owner",
                    password="safe-password",
                ), db))
            finally:
                db.close()
        check = Session(engine)
        assert check.query(Company).count() == 2
        assert check.query(User).count() == 2
        assert check.query(CompanyUser).count() == 2
        assert {response.user.company_id for response in responses} == {1, 2}
        check.close()
    finally:
        engine.dispose()
