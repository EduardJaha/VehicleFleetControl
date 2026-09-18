from datetime import datetime, timedelta
import json
import socket
from uuid import uuid4
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import Base, TenantSession, get_db, set_tenant_context
from app.main import app
from app.models import APIKey, AuditLog, Company, CompanyUser, User, Vehicle, VehiclePaper, WebhookEndpoint, WebhookDelivery
from app.services.api_keys import hash_key
from app.services import webhooks
from app.integration_schemas import EVENTS

BASE = "/api/v1/admin/integrations"

@pytest.fixture
def context(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=TenantSession, expire_on_commit=False)
    with factory() as db:
        for cid in (1, 2):
            db.add(Company(id=cid, name=f"Company {cid}", slug=f"company-{cid}"))
            db.add(User(id=cid, company_id=cid, email=f"admin{cid}@test.local", full_name="Admin", hashed_password="unused", role="admin", is_active=True))
            db.add(CompanyUser(company_id=cid, user_id=cid, role="admin", is_active=True))
        db.add(User(id=3, company_id=1, email="viewer@test.local", full_name="Viewer", hashed_password="unused", role="viewer"))
        db.add(CompanyUser(company_id=1, user_id=3, role="viewer", is_active=True))
        db.commit()
    def override():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(get_settings(), "integrations_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    try:
        with TestClient(app) as client: yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

def auth(user=1):
    return {"Authorization": "Bearer " + create_access_token(user, company_id=2 if user == 2 else 1)}

def key(client, scopes=None):
    response = client.post(BASE + "/api-keys", headers=auth(), json={"name": "ERP", "scopes": scopes or ["vehicles.read"]})
    assert response.status_code == 201, response.text
    return response.json()

def hook(client, events=None, user=1):
    response = client.post(BASE + "/webhooks", headers=auth(user), json={"name": "ERP", "url": "https://hooks.example.test/events", "events": events or list(EVENTS)})
    assert response.status_code == 201, response.text
    return response.json()

def vehicle(cid=1, plate="AA111AA"):
    return Vehicle(company_id=cid, brand="Test", model="Car", license_plate=plate, registration_country="AL", license_plate_normalized=plate, fuel_type="Diesel", year=2024, status=0, vehicle_location="HQ", vehicle_category="Car")

def bearer(raw): return {"Authorization": "Bearer " + raw}

def test_hash_once_scope_and_tenant_http(context):
    client, factory = context
    issued = key(client); raw = issued["raw_key"]
    assert len(raw) == 47 and raw.startswith("vfc_") and "key_hash" not in issued
    with factory() as db:
        assert db.get(APIKey, issued["id"]).key_hash == hash_key(raw)
        db.add_all([vehicle(), vehicle(2, "AA222AA")]); db.commit()
        assert raw not in str([row.new_values for row in db.query(AuditLog).all()])
    response = client.get("/api/v1/vehicles", headers=bearer(raw))
    assert response.status_code == 200, response.text
    assert "AA222AA" not in response.text
    for path in ("/drivers", "/auth/me", "/admin/integrations/api-keys", "/reports/tco"):
        assert client.get("/api/v1" + path, headers=bearer(raw)).status_code == 403
    assert client.post("/api/v1/vehicles", headers=bearer(raw), json={}).status_code == 403
    assert client.get("/api/v1/vehicles/2", headers=bearer(raw)).status_code == 404
    with factory() as db: assert db.get(APIKey, issued["id"]).last_used_at is not None
    listing = client.get(BASE + "/api-keys", headers=auth())
    assert raw not in listing.text and "key_hash" not in listing.text and "raw_key" not in listing.text
    assert client.get(BASE + "/api-keys", headers=auth(2)).json() == []
    assert client.post(BASE + f"/api-keys/{issued['id']}/revoke", headers=auth(2)).status_code == 404

def test_expiration_revocation_rotation_membership_and_live_permissions(context):
    client, factory = context
    old = key(client)
    rotated = client.post(BASE + f"/api-keys/{old['id']}/rotate", headers=auth())
    assert rotated.status_code == 200
    def use(raw): return client.get("/api/v1/vehicles", headers=bearer(raw)).status_code
    assert use(old["raw_key"]) == 401
    issued = rotated.json(); assert use(issued["raw_key"]) == 200
    with factory() as db:
        db.get(APIKey, issued["id"]).expires_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
    assert use(issued["raw_key"]) == 401
    issued = key(client)
    assert client.post(BASE + f"/api-keys/{issued['id']}/revoke", headers=auth()).status_code == 200
    assert use(issued["raw_key"]) == 401
    issued = key(client)
    with factory() as db:
        db.query(CompanyUser).filter_by(user_id=1).one().is_active = False; db.commit()
    assert use(issued["raw_key"]) == 401
    with factory() as db:
        member = db.query(CompanyUser).filter_by(user_id=1).one(); member.is_active = True; member.role = "no_access"; db.commit()
    assert use(issued["raw_key"]) == 403

def test_admin_permissions_and_input_and_write_scope_prerequisites(context):
    client, _ = context
    assert client.get(BASE + "/options", headers=auth(3)).status_code == 403
    assert client.post(BASE + "/api-keys", headers=auth(), json={"name":"test", "scopes":["admin"]}).status_code == 422
    assert client.post(BASE + "/api-keys", headers=auth(), json={"name":"test", "scopes":["vehicles.read"], "expires_at":"2000-01-01T00:00:00Z"}).status_code == 422
    assert client.get("/api/v1/vehicles", headers=bearer("vfc_fake")).status_code == 401
    headers = bearer(key(client, ["fuel.write", "maintenance.write"])["raw_key"])
    assert client.post("/api/v1/fuel", headers=headers, data={}).status_code == 422
    assert client.post("/api/v1/work-orders", headers=headers, json={}).status_code == 422
    assert client.get("/api/v1/work-orders", headers=headers).status_code == 403

@pytest.mark.parametrize("url", ["http://example.test", "https://user:password@example.test", "https://example.test:8443", "https://example.test/#fragment", "https://example.test/\n", "https://example.test\\@other.test", "https://[fe80::1%25en0]/"])
def test_unsafe_url_syntax(context, url):
    with pytest.raises(HTTPException): webhooks.validate_url(url)

@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fc00::1", "::ffff:8.8.8.8", "2002:0808:0808::1"])
def test_private_mixed_dns_and_rebinding(context, monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", (ip, 443))])
    with pytest.raises(HTTPException): webhooks.validate_url("https://hooks.example.test")
    with pytest.raises(HTTPException): webhooks.send_https("https://hooks.example.test", b"{}", {})

def test_transport_pins_dns_tls_no_redirect_or_body(context, monkeypatch):
    captured = {}
    class Response:
        status = 302
        def close(self): captured["closed"] = True
    class Pool:
        def __init__(self, address, **kwargs): captured.update(address=address, **kwargs)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def urlopen(self, method, path, **kwargs): captured.update(method=method, path=path, **kwargs); return Response()
    monkeypatch.setattr(webhooks.urllib3, "HTTPSConnectionPool", Pool)
    assert webhooks.send_https("https://hooks.example.test/events?a=b", b"{}", {}) == 302
    assert captured["address"] == "93.184.216.34"
    assert captured["server_hostname"] == captured["assert_hostname"] == "hooks.example.test"
    assert captured["cert_reqs"] == "CERT_REQUIRED"
    assert captured["redirect"] is False and captured["retries"] is False and captured["preload_content"] is False
    assert captured["closed"]

def test_hmac_tampering_timestamp_and_delivery_replay():
    body, secret, did, now = b'{"event_id":"one"}', "secret", str(uuid4()), 1900000000
    header = webhooks.signature(secret, now, did, body)
    assert webhooks.verify_signature(secret, header, did, body, now=now)
    for candidate_secret, candidate_did, candidate_body, time in [(secret,did,body+b" ",now),(secret,str(uuid4()),body,now),(secret,did,body,now+301),(secret,did,body,now-301),("rotated",did,body,now)]:
        assert not webhooks.verify_signature(candidate_secret, header, candidate_did, candidate_body, now=time)
    assert not webhooks.verify_signature(secret, "invalid", did, body, now=now)

def test_atomic_events_rollback_subscription_and_cross_tenant(context):
    client, factory = context
    endpoint = hook(client, ["vehicle.created", "vehicle.updated"]); hook(client, user=2)
    with factory() as db:
        set_tenant_context(db, 1)
        db.add(vehicle()); db.flush(); db.flush()
        assert db.query(WebhookDelivery).count() == 1
        db.rollback(); assert db.query(WebhookDelivery).count() == 0
        db.add(vehicle()); db.commit()
        delivery = db.query(WebhookDelivery).one()
        assert delivery.endpoint_id == endpoint["id"] and delivery.company_id == 1
        assert set(json.loads(delivery.payload)) == {"event_id", "event_type", "company_id", "occurred_at", "entity_id", "data"}
        db.query(Vehicle).one().status = 1; db.commit()
        assert {row.event_type for row in db.query(WebhookDelivery)} == {"vehicle.created", "vehicle.updated"}
    assert client.get(BASE + f"/webhooks/{endpoint['id']}/deliveries", headers=auth(2)).status_code == 404

def test_retry_limits_history_rotation_resend(context):
    client, factory = context
    endpoint = hook(client); other = hook(client, user=2)
    with factory() as db:
        set_tenant_context(db, 1)
        webhooks.enqueue_event(db, "fuel.created", 1, 10, {"vehicle_id": 1}); db.commit()
        row = db.query(WebhookDelivery).one(); pk = row.id
        calls = []
        def failed(url, body, headers): calls.append(headers); return 503
        for attempt in range(1, 7):
            now = datetime.utcnow() + timedelta(seconds=1) if attempt == 1 else row.next_attempt_at
            webhooks.deliver_pending(db, now=now, transport=failed); db.refresh(row)
            assert row.attempt_count == attempt and len(row.attempts) == attempt
            assert row.status == ("Dead" if attempt == 6 else "Failed")
            if attempt < 6:
                assert row.next_attempt_at == now + timedelta(seconds=30 * 2 ** (attempt - 1))
                webhooks.deliver_pending(db, now=now + timedelta(seconds=1), transport=failed)
                assert len(calls) == attempt
    assert endpoint["secret"] not in client.get(BASE + "/webhooks", headers=auth()).text
    rotated = client.post(BASE + f"/webhooks/{endpoint['id']}/rotate", headers=auth()).json()
    assert rotated["secret_version"] == 2 and rotated["secret"] != endpoint["secret"]
    retry = client.post(BASE + f"/deliveries/{pk}/retry", headers=auth())
    assert retry.status_code == 201, retry.text
    new = retry.json(); assert new["resend_of"] == pk and new["status"] == "Pending" and new["attempts"] == []
    assert client.post(BASE + f"/deliveries/{pk}/retry", headers=auth(2)).status_code == 404
    with factory() as db:
        set_tenant_context(db, 1)
        def success(url, body, headers):
            timestamp = int(headers["X-VFC-Signature"].split(",")[0][2:])
            assert webhooks.verify_signature(rotated["secret"], headers["X-VFC-Signature"], headers["X-VFC-Delivery"], body, now=timestamp)
            return 204
        webhooks.deliver_pending(db, now=datetime.utcnow() + timedelta(seconds=1), transport=success)
        row = db.get(WebhookDelivery, new["id"]); old = db.get(WebhookDelivery, pk)
        assert row.status == "Delivered" and row.delivered_at
        assert row.event_id == old.event_id and row.delivery_id != old.delivery_id and row.payload == old.payload
        assert len(old.attempts) == 6
        assert db.get(WebhookEndpoint, endpoint["id"]).secret_ciphertext != rotated["secret"]
    assert client.get(BASE + f"/webhooks/{other['id']}/deliveries", headers=auth(2)).json() == []

def test_endpoint_failure_isolation_leases_and_revocation(context):
    client, factory = context
    first = hook(client); hook(client)
    with factory() as db:
        set_tenant_context(db, 1)
        webhooks.enqueue_event(db, "service.created", 1, 1, {}); db.commit()
        calls = []
        def transport(url, body, headers):
            calls.append(headers["X-VFC-Delivery"])
            if len(calls) == 1: raise OSError("private details must not persist")
            return 200
        webhooks.deliver_pending(db, now=datetime.utcnow() + timedelta(seconds=1), transport=transport)
        assert len(calls) == 2
        rows = db.query(WebhookDelivery).order_by(WebhookDelivery.id).all()
        assert [row.status for row in rows] == ["Failed", "Delivered"]
        assert "private details" not in str(rows[0].attempts)
        rows[0].lease_token = str(uuid4()); rows[0].lease_until = datetime.utcnow() + timedelta(hours=1)
        rows[0].next_attempt_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
        webhooks.deliver_pending(db, transport=transport); assert len(calls) == 2
    client.post(BASE + f"/webhooks/{first['id']}/revoke", headers=auth())
    assert client.post(BASE + f"/webhooks/{first['id']}/rotate", headers=auth()).status_code == 409

def test_document_expiry_deduplicates_and_renewal_emits_again(context):
    client, factory = context
    hook(client, ["document.expiring"])
    with factory() as db:
        set_tenant_context(db, 1)
        v = vehicle(); db.add(v); db.flush(); now = datetime.utcnow()
        paper = VehiclePaper(vehicle_id=v.id, document_type="Insurance", file_path="private.pdf", issue_date=now - timedelta(days=300), expiry_date=now + timedelta(days=10))
        db.add(paper); db.commit()
        for _ in range(2): webhooks.scan_expiring_documents(db, now); db.commit()
        assert db.query(WebhookDelivery).count() == 1
        paper.expiry_date += timedelta(days=1); db.commit()
        webhooks.scan_expiring_documents(db, now); db.commit()
        assert db.query(WebhookDelivery).count() == 2

def test_all_domain_event_transitions_are_wired(context):
    from app.models import Driver, VehicleAssignment, Inspection, WorkOrder, VehicleService, VehicleFuel, VehicleReservation, VehicleAccident, AccidentClaim
    client, factory = context
    hook(client)
    now = datetime.utcnow()
    with factory() as db:
        set_tenant_context(db, 1)
        v = vehicle(); db.add(v); db.flush()
        driver = Driver(full_name="Driver", employee_number="E1", license_number="L1", license_category="B", license_expiry_date=now + timedelta(days=100))
        db.add(driver); db.flush()
        assignment = VehicleAssignment(vehicle_id=v.id, driver_id=driver.id, start_datetime=now, start_odometer_km=0, status="Scheduled")
        inspection = Inspection(vehicle_id=v.id, inspection_type="Routine", inspection_date=now, overall_status="Passed")
        order = WorkOrder(vehicle_id=v.id, title="Repair")
        reservation = VehicleReservation(vehicle_id=v.id, reserved_by="Driver", reservation_type="Business", start_date=now, end_date=now, status=0)
        accident = VehicleAccident(vehicle_id=v.id, accident_date=now, location="HQ")
        db.add_all([assignment, inspection, order, reservation, accident]); db.flush()
        db.add(AccidentClaim(accident_id=accident.id, insurance_company="Insurer", policy_number="P1", claim_number="C1", claim_opened_date=now))
        db.add(VehicleService(vehicle_id=v.id, service_type="Repair", service_date=now))
        db.add(VehicleFuel(vehicle_id=v.id, refuel_date=now, quantity=1, unit="L", fuel_type="Diesel", location="HQ"))
        assignment.status = "Active"; inspection.overall_status = "Failed"; order.status = "Completed"; reservation.status = 1
        db.flush()
        assignment.status = "Completed"; v.status = 1
        db.commit()
        events = [row.event_type for row in db.query(WebhookDelivery)]
        assert set(events) == set(EVENTS) - {"document.expiring"}
        assert len(events) == len(set(events))
        db.commit()
        assert db.query(WebhookDelivery).count() == len(events)


def test_expired_lease_recovers_and_final_attempt_becomes_dead(context):
    client, factory = context
    hook(client)
    with factory() as db:
        set_tenant_context(db, 1)
        webhooks.enqueue_event(db, "service.created", 1, 1, {}); db.commit()
        row = db.query(WebhookDelivery).one()
        row.status = "Retrying"; row.attempt_count = 1
        row.attempts = [{"number":1, "outcome":"InFlight"}]
        row.lease_token = str(uuid4()); row.lease_until = datetime.utcnow() - timedelta(seconds=1); db.commit()
        webhooks.deliver_pending(db, now=datetime.utcnow() + timedelta(seconds=1), transport=lambda *a: 200)
        db.refresh(row)
        assert row.status == "Delivered" and row.attempts[0]["outcome"] == "Interrupted"
        assert row.attempt_count == 2


def test_delivery_pagination_and_revoked_pending(context):
    client, factory = context
    endpoint = hook(client)
    with factory() as db:
        set_tenant_context(db, 1)
        for i in range(3): webhooks.enqueue_event(db, "service.created", 1, i, {})
        db.commit()
    first = client.get(BASE + f"/webhooks/{endpoint['id']}/deliveries?limit=2", headers=auth()).json()
    second = client.get(BASE + f"/webhooks/{endpoint['id']}/deliveries?before_id={first[-1]['id']}&limit=2", headers=auth()).json()
    assert len(first) == 2 and len(second) == 1
    client.post(BASE + f"/webhooks/{endpoint['id']}/revoke", headers=auth())
    with factory() as db:
        set_tenant_context(db, 1)
        def forbidden(*a): pytest.fail("Revoked endpoint must not send")
        webhooks.deliver_pending(db, now=datetime.utcnow() + timedelta(seconds=1), transport=forbidden)
        assert all(row.status == "Dead" for row in db.query(WebhookDelivery))


def test_encryption_configuration_fails_closed(context, monkeypatch):
    client, _ = context
    monkeypatch.setattr(get_settings(), "integrations_encryption_key", "")
    response = client.post(BASE + "/webhooks", headers=auth(), json={"name":"Test", "url":"https://hooks.example.test", "events":["fuel.created"]})
    assert response.status_code == 503


def test_fresh_and_populated_migration(tmp_path, monkeypatch):
    from alembic import command
    from sqlalchemy import inspect, select
    from sqlalchemy.orm import Session
    from tests.test_fuel_migration import alembic_config
    url = f"sqlite:///{tmp_path / 'integrations.db'}"
    monkeypatch.setenv("DATABASE_URL", url); get_settings.cache_clear()
    engine = create_engine(url)
    try:
        config = alembic_config(url)
        command.upgrade(config, "head")
        assert {"APIKeys", "WebhookEndpoints", "WebhookDeliveries"} <= set(inspect(engine).get_table_names())
        command.downgrade(config, "20260917_0022")
        with Session(engine) as db:
            db.add(User(company_id=1, email="kept@test.local", full_name="Kept", hashed_password="untouched", role="admin", session_version=4)); db.commit()
        with engine.connect() as connection: before = connection.execute(select(User.__table__)).all()
        command.upgrade(config, "head")
        with engine.connect() as connection: assert connection.execute(select(User.__table__)).all() == before
        for name in ("APIKeys", "WebhookEndpoints", "WebhookDeliveries"):
            assert {c["name"] for c in inspect(engine).get_columns(name)} == set(Base.metadata.tables[name].columns.keys())
            assert {i["name"] for i in inspect(engine).get_indexes(name)} == {i.name for i in Base.metadata.tables[name].indexes}
    finally:
        engine.dispose(); get_settings.cache_clear()

def test_concurrent_workers_claim_once_and_stale_completion_is_fenced(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    monkeypatch.setattr(get_settings(), "integrations_encryption_key", Fernet.generate_key().decode())
    engine = create_engine(f"sqlite:///{tmp_path / 'workers.db'}", connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=TenantSession)
    with factory() as db:
        db.add(Company(id=1,name="Worker company",slug="worker"))
        db.add(User(id=1,company_id=1,email="worker@test.local",full_name="Worker",role="admin",hashed_password="unused"))
        _, encrypted = webhooks.new_secret()
        db.add(WebhookEndpoint(company_id=1,created_by=1,name="Test",url="https://example.test/",events=["fuel.created"],secret_ciphertext=encrypted));db.commit()
        set_tenant_context(db,1)
        webhooks.enqueue_event(db,"fuel.created",1,1,{});db.commit()
    entered, release = Event(), Event()
    def slow(*args):
        entered.set(); assert release.wait(5); return 200
    def run(transport):
        with factory() as db:
            set_tenant_context(db,1)
            return webhooks.deliver_pending(db,transport=transport)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run,slow)
            assert entered.wait(5)
            assert pool.submit(run,lambda *a: pytest.fail("Unexpired claim sent twice")).result(timeout=5) == {"sent":0}
            # Simulate lease expiration and a second worker completing before the first returns.
            with factory() as db:
                row = db.query(WebhookDelivery).one()
                row.lease_until = datetime.utcnow() - timedelta(seconds=1);db.commit()
            assert pool.submit(run,lambda *a:204).result(timeout=5) == {"sent":1}
            release.set()
            assert first.result(timeout=5) == {"sent":0}
        with factory() as db:
            row = db.query(WebhookDelivery).one()
            assert row.status == "Delivered" and row.attempt_count == 2
            assert [a["outcome"] for a in row.attempts] == ["Interrupted","Delivered"]
            assert row.attempts[-1]["http_status"] == 204
    finally:
        release.set(); engine.dispose()


def test_disabled_company_user_and_scoped_grants_disable_keys(context):
    from app.core.authorization import seed_authorization_defaults
    from app.models import Role, UserRole, Location
    client, factory = context
    issued = key(client)
    def use(): return client.get("/api/v1/vehicles",headers=bearer(issued["raw_key"])).status_code
    with factory() as db:
        db.get(Company,1).is_active=False;db.commit()
    assert use() == 401
    with factory() as db:
        db.get(Company,1).is_active=True;db.get(User,1).is_active=False;db.commit()
    assert use() == 401
    with factory() as db:
        db.get(User,1).is_active=True;db.get(User,1).password_reset_required=True;db.commit()
    assert use() == 401
    with factory() as db:
        db.get(User,1).password_reset_required=False
        seed_authorization_defaults(db,migrate_users=False,commit=False)
        location=Location(company_id=1,name="HQ",code="HQ");db.add(location);db.flush()
        role=db.query(Role).filter_by(code="admin").one()
        db.add(UserRole(company_id=1,user_id=1,role_id=role.id,location_id=location.id));db.commit()
    assert use() == 403
