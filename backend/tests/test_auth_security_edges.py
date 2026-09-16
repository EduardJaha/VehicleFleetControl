from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from alembic import command
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwt
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import hash_password, pwd_context, verify_password, validate_access_token
from app.db.session import Base
from app.main import app
from app.models import AuditLog, CompanyUser, LoginRateLimit, User
from app.schemas import AdminUserCreate, FirstAdminCreate, PasswordChangeRequest, PasswordResetRequest, UserCreate
from app.services.login_security import reserve_login_attempt
from tests.test_auth_security import auth_context, login, PASSWORD, NEW_PASSWORD
from tests.test_fuel_migration import alembic_config


ORIGIN = {"Origin": "http://localhost:3000"}
STRONG_SECRET = "B7g9N2q4R6t8V0x3Z5c1D7f9H2j4K6m8"


@pytest.mark.parametrize("headers", [{}, {"Origin": "null"}, {"Referer": "not-a-url"}, {"Origin": "https://evil.example"}])
def test_cookie_and_login_csrf_fail_closed(auth_context, headers):
    with TestClient(app) as client:
        rejected = client.post("/api/v1/auth/login", headers=headers, json={"email": "unknown@test.test", "password": PASSWORD})
        assert rejected.status_code == 403
        client.cookies.set(get_settings().auth_cookie_name, "invalid")
        rejected = client.post("/api/v1/auth/logout", headers=headers)
        assert rejected.status_code == 403
        assert rejected.headers["x-frame-options"] == "DENY"
        assert rejected.headers["cache-control"] == "private, no-store"


def test_referer_fallback_and_albanian_errors(auth_context):
    _, users = auth_context
    with TestClient(app, headers={"Referer": "http://localhost:3000/login", "Accept-Language": "sq"}) as client:
        bad = login(client, "missing@test.test", "wrong")
        assert bad.status_code == 401
        assert bad.json()["message"] == "Email-i ose fjalëkalimi është i pasaktë."
        for _ in range(get_settings().login_rate_limit_attempts - 1):
            login(client, "missing@test.test", "wrong")
        limited = login(client, "missing@test.test", "wrong")
        assert limited.status_code == 429
        assert limited.headers["retry-after"].isdigit()
        assert limited.json()["message"] == "Shumë tentativa për hyrje. Ju lutemi provoni përsëri më vonë."
        assert login(client, users["admin"].email).status_code == 200


def test_production_cookie_cors_hsts_and_invalid_settings(auth_context, monkeypatch):
    settings = get_settings()
    for key, value in {"environment": "production", "cookie_secure": True}.items():
        monkeypatch.setattr(settings, key, value)
    with TestClient(app, base_url="https://testserver", headers=ORIGIN) as client:
        response = login(client, "admin@alpha.test")
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]
        assert response.headers["strict-transport-security"].startswith("max-age=")
        assert response.headers["access-control-allow-origin"] == ORIGIN["Origin"]
        assert response.headers["access-control-allow-credentials"] == "true"
        assert client.get("/api/v1/auth/me").status_code == 200
        bad = client.options("/api/v1/auth/login", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
        assert bad.status_code == 400
        assert "access-control-allow-origin" not in bad.headers
    with TestClient(app) as client:
        assert "strict-transport-security" not in client.get("/health", headers={"X-Forwarded-Proto": "https"}).headers
    settings_args = dict(_env_file=None, environment="production", JWT_SECRET_KEY=STRONG_SECRET, CORS_ORIGINS="https://fleet.example", cookie_secure=True)
    assert Settings(**settings_args).cookie_secure
    for secret in ("", " " * 40, "x" * 40, "change-this-local-development-secret", "replace-with-a-random-secret-at-least-32-characters"):
        with pytest.raises(ValidationError):
            Settings(**{**settings_args, "JWT_SECRET_KEY": secret})
    for origin in ("", "*", "https://fleet.example/path", "https://*.example", "https://user:pass@fleet.example", "http://fleet.example"):
        with pytest.raises(ValidationError):
            Settings(**{**settings_args, "CORS_ORIGINS": origin})
    with pytest.raises(ValidationError):
        Settings(**{**settings_args, "cookie_secure": False})


def test_long_unicode_passwords_are_not_truncated_and_legacy_hashes_work():
    password = "ë" * 60 + "suffix-one"
    encoded = hash_password(password)
    assert verify_password(password, encoded)
    assert not verify_password("ë" * 60 + "suffix-two", encoded)
    legacy = pwd_context.hash(PASSWORD, scheme="bcrypt")
    assert verify_password(PASSWORD, legacy)


@pytest.mark.parametrize("schema,field,extra", [
    (UserCreate, "password", {"email": "test@example.com", "full_name": "Test"}),
    (FirstAdminCreate, "password", {"email": "test@example.com", "full_name": "Test"}),
    (AdminUserCreate, "password", {"email": "test@example.com", "full_name": "Test", "role_assignments": []}),
    (PasswordResetRequest, "temporary_password", {}),
    (PasswordChangeRequest, "new_password", {"current_password": PASSWORD}),
])
def test_shared_password_minimum(schema, field, extra):
    with pytest.raises(ValidationError):
        schema(**{**extra, field: "short-pass"})
    assert schema(**{**extra, field: "valid pass phrase"})


def test_company_actions_and_scopes_cannot_escape_tenant(auth_context):
    factory, users = auth_context
    with TestClient(app, headers=ORIGIN) as client:
        assert login(client, users["admin"].email).status_code == 200
        for suffix, payload in (("reset-password", {"temporary_password": NEW_PASSWORD}), ("revoke-sessions", {})):
            assert client.post(f"/api/v1/admin/users/{users['outsider'].id}/{suffix}", json=payload).status_code == 404
        listed = client.get("/api/v1/admin/users").json()
        assert next(row for row in listed if row["id"] == users["viewer"].id)["role"] == "viewer"
        assert client.post("/api/v1/auth/switch-company", json={"company_id": 2}).status_code == 404
    with TestClient(app, headers=ORIGIN) as client:
        assert login(client, users["viewer"].email).status_code == 200
        for suffix, payload in (("reset-password", {"temporary_password": NEW_PASSWORD}), ("revoke-sessions", {})):
            assert client.post(f"/api/v1/admin/users/{users['admin'].id}/{suffix}", json=payload).status_code == 403
        assert client.post("/api/v1/admin/users", json={"email": "hacker@test.test", "full_name": "Hacker", "password": PASSWORD, "role_assignments": [{"role_id": 1}]}).status_code == 403
        assert client.put(f"/api/v1/admin/users/{users['admin'].id}", json={"email": "hacker@test.test", "full_name": "Hacker", "role_assignments": [{"role_id": 1}]}).status_code == 403
    with factory() as db:
        outsider = db.get(User, users["outsider"].id)
        assert outsider.session_version == 0
        assert verify_password(PASSWORD, outsider.hashed_password)


def test_inactive_membership_expired_missing_exp_and_audit_redaction(auth_context):
    factory, users = auth_context
    with TestClient(app, headers=ORIGIN) as client:
        assert login(client, users["viewer"].email).status_code == 200
        with factory() as db:
            row = db.query(CompanyUser).filter_by(user_id=users["viewer"].id).one()
            row.is_active = False
            db.commit()
        assert client.get("/api/v1/auth/me").status_code == 401
        assert login(client, users["viewer"].email).status_code == 401
    settings = get_settings()
    with factory() as db:
        token = jwt.encode({"sub": str(users["admin"].id), "sv": 0, "cid": 1}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        with pytest.raises(HTTPException):
            validate_access_token(token, db)
        audits = str([(row.old_values, row.new_values, row.description_params, row.description) for row in db.query(AuditLog)])
        assert PASSWORD not in audits and token not in audits


def test_rate_limit_one_attempt_cooldown_and_concurrent_workers(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "login_rate_limit_attempts", 1)
    monkeypatch.setattr(settings, "login_rate_limit_window_seconds", 60)
    engine = create_engine(f"sqlite:///{tmp_path / 'throttle.db'}", connect_args={"timeout": 30})
    LoginRateLimit.__table__.create(engine)
    now = datetime.utcnow()
    def attempt(_):
        with Session(engine) as db:
            try:
                reserve_login_attempt(db, "192.0.2.1", "normalized@EXAMPLE.com", now=now)
                return 200
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, range(12)))
    assert results.count(200) == 1
    assert results.count(429) == 11
    with Session(engine) as db:
        assert reserve_login_attempt(db, "192.0.2.1", "normalized@example.com", now=now + timedelta(seconds=61))
    engine.dispose()


def test_fresh_and_populated_migration_preserves_users(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    engine = create_engine(url)
    try:
        config = alembic_config(url)
        command.upgrade(config, "head")
        assert "LoginRateLimits" in inspect(engine).get_table_names()
        command.downgrade(config, "20260915_0020")
        with Session(engine) as db:
            db.add(User(email="kept@test.test", full_name="Kept", hashed_password=hash_password(PASSWORD), role="admin", is_active=True, session_version=7))
            db.commit()
        with engine.connect() as conn:
            original = conn.execute(select(User.__table__)).all()
        command.upgrade(config, "head")
        with engine.connect() as conn:
            assert conn.execute(select(User.__table__)).all() == original
        assert {i["name"] for i in inspect(engine).get_indexes("LoginRateLimits")} == {i.name for i in Base.metadata.tables["LoginRateLimits"].indexes}
    finally:
        engine.dispose()
        get_settings.cache_clear()
