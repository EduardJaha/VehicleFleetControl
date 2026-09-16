from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient as BaseTestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.authorization import seed_authorization_defaults
from app.core.config import Settings, get_settings
from app.core.security import create_access_token, hash_password, set_auth_cookie, validate_access_token, verify_password
from app.db.session import Base, TenantSession, get_db
from app.main import app
from app.models import Company, CompanyUser, LoginRateLimit, Role, User, UserRole


PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "new correct horse battery staple"


class TestClient(BaseTestClient):
    __test__ = False

    def __init__(self, application, **kwargs):
        super().__init__(application, headers={"Origin": "http://localhost:3000"}, **kwargs)


@pytest.fixture()
def auth_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=TenantSession, expire_on_commit=False)
    db = factory()
    db.add_all([Company(id=1, name="Alpha", slug="alpha"), Company(id=2, name="Beta", slug="beta")])
    db.commit()
    seed_authorization_defaults(db, migrate_users=False)
    roles = {row.code: row for row in db.query(Role).all()}

    def add_user(email: str, role: str, company_id: int = 1, **values) -> User:
        user = User(
            company_id=company_id,
            email=email,
            full_name=values.pop("full_name", email.split("@", 1)[0].title()),
            hashed_password=hash_password(values.pop("password", PASSWORD)),
            role=role,
            **values,
        )
        db.add(user)
        db.flush()
        db.add(CompanyUser(company_id=company_id, user_id=user.id, role=role, is_default=True))
        db.add(UserRole(company_id=company_id, user_id=user.id, role_id=roles[role].id))
        db.commit()
        return user

    users = {
        "admin": add_user("admin@alpha.test", "admin"),
        "viewer": add_user("viewer@alpha.test", "viewer"),
        "inactive": add_user("inactive@alpha.test", "viewer", is_active=False),
        "temporary": add_user("temporary@alpha.test", "viewer", password_reset_required=True),
        "outsider": add_user("admin@beta.test", "admin", company_id=2),
    }
    db.close()

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    settings = get_settings()
    original_attempts = settings.login_rate_limit_attempts
    original_window = settings.login_rate_limit_window_seconds
    original_secure = settings.cookie_secure
    app.dependency_overrides[get_db] = override_db
    try:
        yield factory, users
    finally:
        settings.login_rate_limit_attempts = original_attempts
        settings.login_rate_limit_window_seconds = original_window
        settings.cookie_secure = original_secure
        app.dependency_overrides.clear()
        engine.dispose()


def login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_login_uses_httponly_cookie_and_never_returns_plaintext_or_token(auth_context):
    factory, users = auth_context
    with TestClient(app) as client:
        response = login(client, users["admin"].email)
        assert response.status_code == 200
        assert set(response.json()) == {"user"}
        assert PASSWORD not in response.text
        assert not {"password", "hashed_password", "access_token"}.intersection(response.json()["user"])
        cookie = response.headers["set-cookie"]
        assert "vehicle_fleet_control_session=" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/" in cookie
        assert "Secure" not in cookie
        assert client.get("/api/v1/auth/me").status_code == 200

    db = factory()
    try:
        stored = db.get(User, users["admin"].id)
        assert stored.last_login_at is not None
        assert stored.hashed_password != PASSWORD
        assert verify_password(PASSWORD, stored.hashed_password)
    finally:
        db.close()


def test_login_errors_do_not_disclose_unknown_wrong_or_inactive_accounts(auth_context):
    _, users = auth_context
    with TestClient(app) as client:
        wrong = login(client, users["viewer"].email, "definitely wrong")
        unknown = login(client, "unknown@alpha.test", "definitely wrong")
        inactive = login(client, users["inactive"].email)
    assert wrong.status_code == unknown.status_code == inactive.status_code == 401
    assert wrong.json() == unknown.json() == inactive.json()
    assert wrong.json()["code"] == "invalid_credentials"


def test_rate_limit_activates_and_success_clears_failure_bucket(auth_context):
    factory, users = auth_context
    settings = get_settings()
    settings.login_rate_limit_attempts = 3
    settings.login_rate_limit_window_seconds = 60
    with TestClient(app) as client:
        for _ in range(3):
            assert login(client, users["viewer"].email, "wrong password").status_code == 401
        limited = login(client, users["viewer"].email, PASSWORD)
        assert limited.status_code == 429
        assert limited.json()["code"] == "login_rate_limited"

    db = factory()
    db.query(LoginRateLimit).delete()
    db.commit()
    db.close()
    with TestClient(app) as client:
        assert login(client, users["viewer"].email, "wrong password").status_code == 401
        assert login(client, users["viewer"].email).status_code == 200
    db = factory()
    try:
        # IP request budget remains; successful authentication clears the pair.
        assert db.query(LoginRateLimit).count() == 1
    finally:
        db.close()


def test_temporary_password_blocks_normal_api_until_changed_and_revokes_old_session(auth_context):
    factory, users = auth_context
    with TestClient(app) as client:
        response = login(client, users["temporary"].email)
        assert response.status_code == 200
        old_token = client.cookies[get_settings().auth_cookie_name]
        denied = client.get("/api/v1/dashboard/overview")
        assert denied.status_code == 403
        assert denied.json()["code"] == "password_change_required"
        assert client.get("/api/v1/auth/me").status_code == 200
        wrong = client.put(
            "/api/v1/auth/me/password",
            json={"current_password": "wrong", "new_password": NEW_PASSWORD},
        )
        assert wrong.status_code == 400
        changed = client.put(
            "/api/v1/auth/me/password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert changed.status_code == 200
        assert changed.json()["user"]["password_reset_required"] is False

    db = factory()
    try:
        with pytest.raises(HTTPException) as revoked:
            validate_access_token(old_token, db)
        assert revoked.value.status_code == 401
        assert verify_password(NEW_PASSWORD, db.get(User, users["temporary"].id).hashed_password)
    finally:
        db.close()


def test_admin_user_lifecycle_authorization_and_company_boundary(auth_context):
    factory, users = auth_context
    db = factory()
    admin_role = db.query(Role).filter(Role.code == "admin").one()
    viewer_role = db.query(Role).filter(Role.code == "viewer").one()
    db.close()

    with TestClient(app) as viewer_client:
        assert login(viewer_client, users["viewer"].email).status_code == 200
        assert viewer_client.get("/api/v1/admin/users").status_code == 403

    with TestClient(app) as admin_client:
        assert login(admin_client, users["admin"].email).status_code == 200
        listed = admin_client.get("/api/v1/admin/users")
        assert listed.status_code == 200
        assert {row["email"] for row in listed.json()} == {
            users["admin"].email,
            users["viewer"].email,
            users["inactive"].email,
            users["temporary"].email,
        }
        created = admin_client.post(
            "/api/v1/admin/users",
            json={
                "email": "created@alpha.test",
                "company_id": 2,  # Untrusted input cannot select the new user's tenant.
                "full_name": "Created User",
                "password": PASSWORD,
                "is_active": True,
                "preferred_language": "sq",
                "driver_id": None,
                "role_assignments": [{"role_id": viewer_role.id, "own_records_only": False}],
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["company_id"] == 1
        assert body["password_reset_required"] is True
        assert "password" not in body
        user_id = body["id"]

        changed_role = admin_client.put(
            f"/api/v1/admin/users/{user_id}",
            json={
                "email": body["email"],
                "full_name": body["full_name"],
                "is_active": True,
                "preferred_language": "sq",
                "driver_id": None,
                "role_assignments": [{"role_id": admin_role.id, "own_records_only": False}],
            },
        )
        assert changed_role.status_code == 200
        assert changed_role.json()["role"] == "admin"

        reset = admin_client.post(
            f"/api/v1/admin/users/{user_id}/reset-password",
            json={"temporary_password": NEW_PASSWORD, "require_change": True},
        )
        assert reset.status_code == 204

        outsider_update = admin_client.put(
            f"/api/v1/admin/users/{users['outsider'].id}",
            json={
                "email": users["outsider"].email,
                "full_name": users["outsider"].full_name,
                "is_active": True,
                "preferred_language": "en",
                "driver_id": None,
                "role_assignments": [{"role_id": admin_role.id, "own_records_only": False}],
            },
        )
        assert outsider_update.status_code == 404


def test_deactivation_reactivation_and_admin_session_revocation_take_effect_immediately(auth_context):
    factory, users = auth_context
    db = factory()
    viewer_role = db.query(Role).filter(Role.code == "viewer").one()
    db.close()
    update = {
        "email": users["viewer"].email,
        "full_name": users["viewer"].full_name,
        "preferred_language": "en",
        "driver_id": None,
        "role_assignments": [{"role_id": viewer_role.id, "own_records_only": False}],
    }
    with TestClient(app) as viewer_client, TestClient(app) as admin_client:
        assert login(viewer_client, users["viewer"].email).status_code == 200
        assert login(admin_client, users["admin"].email).status_code == 200
        assert admin_client.put(f"/api/v1/admin/users/{users['viewer'].id}", json={**update, "is_active": False}).status_code == 200
        assert viewer_client.get("/api/v1/auth/me").status_code in {401, 403}
        assert admin_client.put(f"/api/v1/admin/users/{users['viewer'].id}", json={**update, "is_active": True}).status_code == 200
        assert login(viewer_client, users["viewer"].email).status_code == 200
        assert admin_client.post(f"/api/v1/admin/users/{users['viewer'].id}/revoke-sessions", json={}).status_code == 204
        assert viewer_client.get("/api/v1/auth/me").status_code == 401


def test_expiry_logout_csrf_and_security_headers(auth_context):
    factory, users = auth_context
    db = factory()
    try:
        expired = create_access_token(users["viewer"].id, expires_delta=timedelta(seconds=-1), company_id=1)
        with pytest.raises(HTTPException):
            validate_access_token(expired, db)
    finally:
        db.close()

    with TestClient(app) as client:
        assert login(client, users["viewer"].email).status_code == 200
        rejected = client.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"})
        assert rejected.status_code == 403
        assert rejected.json()["code"] == "csrf_failed"
        logged_out = client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:3000"})
        assert logged_out.status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401
        health = client.get("/health")
        assert health.headers["x-content-type-options"] == "nosniff"
        assert health.headers["x-frame-options"] == "DENY"
        assert health.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert health.headers["permissions-policy"]


def test_production_settings_and_secure_cookie_contract():
    with pytest.raises(ValidationError):
        Settings(environment="production", JWT_SECRET_KEY="short", CORS_ORIGINS="https://fleet.example", COOKIE_SECURE=True)
    with pytest.raises(ValidationError):
        Settings(environment="production", JWT_SECRET_KEY="x" * 32, CORS_ORIGINS="*", COOKIE_SECURE=True)
    with pytest.raises(ValidationError):
        Settings(environment="production", JWT_SECRET_KEY="x" * 32, CORS_ORIGINS="http://fleet.example", COOKIE_SECURE=True)
    with pytest.raises(ValidationError):
        Settings(environment="production", JWT_SECRET_KEY="x" * 32, CORS_ORIGINS="https://fleet.example", COOKIE_SECURE=False)

    settings = get_settings()
    original = settings.cookie_secure
    settings.cookie_secure = True
    try:
        response = Response()
        set_auth_cookie(response, "signed-token")
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=lax" in cookie
    finally:
        settings.cookie_secure = original
