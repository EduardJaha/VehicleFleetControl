"""Transactional webhook outbox and isolated, leased HTTPS delivery."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
from urllib.parse import urlsplit
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import or_
import urllib3

from app.core.config import get_settings
from app.integration_schemas import EVENTS
from app.models import WebhookDelivery, WebhookEndpoint, VehiclePaper

MAX_ATTEMPTS = 6


def cipher():
    try:
        return Fernet(get_settings().integrations_encryption_key.encode("ascii"))
    except (ValueError, UnicodeError):
        raise HTTPException(503, detail={"code": "integration_not_configured", "message": "Webhook encryption is not configured."}) from None


def new_secret():
    secret = "whsec_" + secrets.token_urlsafe(32)
    return secret, cipher().encrypt(secret.encode()).decode()


def validate_url(url: str):
    """Resolve all addresses, fail closed, and return a pinned public destination."""
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or
                parsed.password is not None or parsed.fragment or parsed.port not in (None, 443) or
                any(ord(c) <= 32 or ord(c) >= 127 for c in url) or "\\" in url or "%" in parsed.netloc):
            raise ValueError()
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)}
        if not addresses:
            raise ValueError()
        for address in addresses:
            ip = ipaddress.ip_address(address)
            # Reject mapped IPv6 and transition mechanisms as well as private/reserved ranges.
            if not ip.is_global or ip.is_multicast or (ip.version == 6 and (ip.ipv4_mapped or ip.sixtofour or ip.teredo)):
                raise ValueError()
        return parsed, sorted(addresses)[0]
    except (ValueError, OSError):
        raise HTTPException(422, detail={"code": "integration_url_invalid", "message": "Use a public HTTPS webhook URL on port 443."}) from None


def signature(secret: str, timestamp: int, delivery_id: str, body: bytes) -> str:
    message = str(timestamp).encode() + b"." + delivery_id.encode() + b"." + body
    return f"t={timestamp},v1=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_signature(secret: str, header: str, delivery_id: str, body: bytes, *, now: int, tolerance: int = 300) -> bool:
    """Receiver helper; receivers must ALSO atomically deduplicate event_id."""
    try:
        timestamp = int(header.split(",")[0].removeprefix("t="))
        return abs(now - timestamp) <= tolerance and hmac.compare_digest(header, signature(secret, timestamp, delivery_id, body))
    except (ValueError, TypeError):
        return False


def send_https(url: str, body: bytes, headers: dict) -> int:
    parsed, address = validate_url(url)  # Revalidate DNS for every attempt; never reconnect by hostname.
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    with urllib3.HTTPSConnectionPool(address, port=443, server_hostname=parsed.hostname,
                                    assert_hostname=parsed.hostname, cert_reqs="CERT_REQUIRED",
                                    timeout=urllib3.Timeout(connect=3, read=7, total=10)) as pool:
        response = pool.urlopen("POST", path, body=body, headers={**headers, "Host": parsed.netloc},
                                retries=False, redirect=False, preload_content=False, assert_same_host=False)
        try:
            return response.status  # Do not read or store an untrusted response body.
        finally:
            response.close()


def enqueue_event(db, event_type, company_id, entity_id, data, *, event_id=None, now=None):
    if event_type not in EVENTS:
        raise ValueError("Unsupported event")
    now = now or datetime.utcnow()
    event_id = event_id or str(uuid4())
    payload = json.dumps({"event_id": event_id, "event_type": event_type, "company_id": company_id,
                          "occurred_at": now.isoformat(timespec="microseconds") + "Z",
                          "entity_id": entity_id, "data": data}, sort_keys=True, separators=(",", ":"), default=str)
    endpoints = db.query(WebhookEndpoint).filter(WebhookEndpoint.company_id == company_id,
                                                WebhookEndpoint.revoked_at.is_(None)).all()
    for endpoint in endpoints:
        if event_type in endpoint.events:
            db.add(WebhookDelivery(company_id=company_id, endpoint_id=endpoint.id, event_id=event_id,
                                  delivery_id=str(uuid4()), event_type=event_type, payload=payload))


def scan_expiring_documents(db, now):
    """One notification per document expiry per endpoint, independent of in-app preferences."""
    company_id = db.info["company_id"]
    from uuid import uuid5, NAMESPACE_URL
    for paper in db.query(VehiclePaper).filter(VehiclePaper.archived.is_(False),
            VehiclePaper.expiry_date >= now.replace(hour=0, minute=0, second=0, microsecond=0),
            VehiclePaper.expiry_date <= now + timedelta(days=30)).all():
        event_id = str(uuid5(NAMESPACE_URL, f"vfc:{company_id}:document:{paper.id}:{paper.expiry_date.isoformat()}"))
        # Existing subscriptions receive one event for this expiry; new ones start at the next scan.
        endpoints = db.query(WebhookEndpoint).filter(WebhookEndpoint.company_id == company_id,
                                                    WebhookEndpoint.revoked_at.is_(None)).all()
        for endpoint in endpoints:
            if "document.expiring" not in endpoint.events:
                continue
            if db.query(WebhookDelivery.id).filter(WebhookDelivery.endpoint_id == endpoint.id,
                                                   WebhookDelivery.event_id == event_id).first():
                continue
            payload = json.dumps({"event_id": event_id, "event_type": "document.expiring", "company_id": company_id,
                                  "occurred_at": now.isoformat() + "Z", "entity_id": paper.id,
                                  "data": {"expiry_date": paper.expiry_date.isoformat(), "vehicle_id": paper.vehicle_id,
                                           "driver_id": paper.driver_id}}, sort_keys=True, separators=(",", ":"))
            db.add(WebhookDelivery(company_id=company_id, endpoint_id=endpoint.id, event_id=event_id,
                                  delivery_id=str(uuid4()), event_type="document.expiring", payload=payload))
    db.flush()


def deliver_pending(db, *, now=None, transport=None, limit=25):
    """Commits each claim before IO. A failed endpoint cannot roll back domain transactions."""
    now = now or datetime.utcnow()
    transport = transport or send_https
    company_id = db.info["company_id"]
    due = db.query(WebhookDelivery).filter(WebhookDelivery.company_id == company_id,
        WebhookDelivery.status.in_(["Pending", "Failed", "Retrying"]), WebhookDelivery.next_attempt_at <= now,
        or_(WebhookDelivery.lease_until.is_(None), WebhookDelivery.lease_until <= now))
    ids = [row[0] for row in due.with_entities(WebhookDelivery.id).order_by(WebhookDelivery.next_attempt_at, WebhookDelivery.id).limit(limit).all()]
    sent = 0
    for delivery_pk in ids:
        token = str(uuid4())
        claimed = due.filter(WebhookDelivery.id == delivery_pk).update({
            WebhookDelivery.lease_token: token, WebhookDelivery.lease_until: datetime.utcnow() + timedelta(minutes=2),
            WebhookDelivery.status: "Retrying"}, synchronize_session=False)
        db.commit()
        if not claimed:
            continue
        db.expire_all()
        row = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_pk).one()
        endpoint = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == row.endpoint_id,
                                                    WebhookEndpoint.company_id == company_id).first()
        attempts = list(row.attempts)
        if attempts and attempts[-1]["outcome"] == "InFlight":
            attempts[-1] = {**attempts[-1], "outcome": "Interrupted"}
        if not endpoint or endpoint.revoked_at or row.attempt_count >= MAX_ATTEMPTS:
            row.status = "Dead"
            row.attempts = attempts
            row.lease_token = None
            row.lease_until = None
            db.commit()
            continue
        row.attempt_count += 1
        timestamp = int(datetime.now(timezone.utc).timestamp())
        attempt = {"number": row.attempt_count, "started_at": datetime.utcnow().isoformat() + "Z",
                   "outcome": "InFlight", "secret_version": endpoint.secret_version}
        row.attempts = attempts + [attempt]
        body, url = row.payload.encode(), endpoint.url
        delivery_id, event_type, encrypted_secret = row.delivery_id, row.event_type, endpoint.secret_ciphertext
        db.commit()
        code = None
        try:
            secret = cipher().decrypt(encrypted_secret.encode()).decode()
            code = transport(url, body, {"Content-Type": "application/json", "X-VFC-Event": event_type,
                "X-VFC-Delivery": delivery_id, "X-VFC-Signature": signature(secret, timestamp, delivery_id, body)})
            success = 200 <= code < 300
            outcome = "Delivered" if success else "HTTPError"
        except Exception:
            success, outcome = False, "TransportError"  # No URL, secrets or exception contents in history/logs.
        db.expire_all()
        row = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_pk,
                                               WebhookDelivery.lease_token == token).first()
        if row is None:
            continue
        values = {
            WebhookDelivery.attempts: row.attempts[:-1] + [{**attempt, "outcome": outcome, "http_status": code,
                "finished_at": datetime.utcnow().isoformat() + "Z"}],
            WebhookDelivery.lease_token: None, WebhookDelivery.lease_until: None,
            WebhookDelivery.status: "Delivered" if success else ("Dead" if row.attempt_count >= MAX_ATTEMPTS else "Failed"),
        }
        if success:
            values[WebhookDelivery.delivered_at] = datetime.utcnow()
        else:
            values[WebhookDelivery.next_attempt_at] = now + timedelta(seconds=min(3600, 30 * 2 ** (row.attempt_count - 1)))
        # Fence completion too: an expired worker cannot overwrite a newer owner's result.
        completed = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_pk,
            WebhookDelivery.company_id == company_id, WebhookDelivery.lease_token == token).update(values, synchronize_session=False)
        db.commit()
        db.expire_all()
        if completed and success:
            sent += 1
    return {"sent": sent}
