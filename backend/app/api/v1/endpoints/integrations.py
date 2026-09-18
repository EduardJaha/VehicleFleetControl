from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.authorization import authorization_scope, get_user_permissions, require_permission
from app.db.session import get_db
from app.integration_schemas import (APIKeyCreate, APIKeyIssued, APIKeyOut, DeliveryOut, EVENTS, SCOPES,
                                     WebhookCreate, WebhookIssued, WebhookOut)
from app.models import APIKey, User, WebhookEndpoint, WebhookDelivery
from app.services.api_keys import issue_key
from app.services.audit import record_audit
from app.services.webhooks import new_secret, validate_url

router = APIRouter()


def administrator(db: Session = Depends(get_db), user: User = Depends(require_permission("integrations.manage"))):
    if db.info.get("api_key_id") or not authorization_scope(db, user, "integrations.manage").unrestricted:
        raise HTTPException(403, detail="Insufficient permissions.")
    return user


def owned(db, model, row_id):
    row = db.query(model).filter(model.id == row_id, model.company_id == db.info["company_id"]).with_for_update().first()
    if row is None:
        raise HTTPException(404, detail={"code": "integration_not_found", "message": "Integration record not found."})
    return row


def audit(db, user, row, action):
    record_audit(db, user=user, action=action, entity_type=type(row).__name__, entity_id=row.id,
                 new_values={"id": row.id})


def check_scopes(db, user, scopes):
    permissions = set().union(*(SCOPES[scope] for scope in scopes))
    if not permissions <= get_user_permissions(db, user) or any(
            not authorization_scope(db, user, p).unrestricted for p in permissions):
        raise HTTPException(403, detail="API keys require unrestricted domain grants.")


@router.get("/options")
def options(user: User = Depends(administrator)):
    return {"scopes": sorted(SCOPES), "events": list(EVENTS)}


@router.get("/api-keys", response_model=list[APIKeyOut])
def list_keys(db: Session = Depends(get_db), user: User = Depends(administrator)):
    return db.query(APIKey).filter(APIKey.company_id == db.info["company_id"]).order_by(APIKey.id.desc()).all()


@router.post("/api-keys", response_model=APIKeyIssued, status_code=201)
def create_key(payload: APIKeyCreate, db: Session = Depends(get_db), user: User = Depends(administrator)):
    check_scopes(db, user, payload.scopes)
    row, raw = issue_key(db, company_id=db.info["company_id"], user_id=user.id, **payload.model_dump())
    audit(db, user, row, "Create API key")
    db.commit()
    return {**APIKeyOut.model_validate(row).model_dump(), "raw_key": raw}


@router.post("/api-keys/{key_id}/revoke", response_model=APIKeyOut)
def revoke_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(administrator)):
    row = owned(db, APIKey, key_id)
    row.revoked_at = row.revoked_at or datetime.utcnow()
    audit(db, user, row, "Revoke API key")
    db.commit()
    return row


@router.post("/api-keys/{key_id}/rotate", response_model=APIKeyIssued)
def rotate_key(key_id: int, db: Session = Depends(get_db), user: User = Depends(administrator)):
    old = owned(db, APIKey, key_id)
    if old.revoked_at or (old.expires_at and old.expires_at <= datetime.utcnow()):
        raise HTTPException(409, detail={"code": "integration_inactive", "message": "Integration is revoked or expired."})
    check_scopes(db, user, old.scopes)
    updated = db.query(APIKey).filter(APIKey.id == old.id, APIKey.company_id == db.info["company_id"],
                                      APIKey.revoked_at.is_(None)).update({APIKey.revoked_at: datetime.utcnow()})
    if not updated:
        raise HTTPException(409, detail="Integration is revoked or expired.")
    row, raw = issue_key(db, company_id=old.company_id, user_id=user.id, name=old.name,
                         scopes=old.scopes, expires_at=old.expires_at)
    audit(db, user, old, "Rotate API key")
    db.commit()
    return {**APIKeyOut.model_validate(row).model_dump(), "raw_key": raw}


@router.get("/webhooks", response_model=list[WebhookOut])
def list_webhooks(db: Session = Depends(get_db), user: User = Depends(administrator)):
    return db.query(WebhookEndpoint).filter(WebhookEndpoint.company_id == db.info["company_id"]).order_by(WebhookEndpoint.id.desc()).all()


@router.post("/webhooks", response_model=WebhookIssued, status_code=201)
def create_webhook(payload: WebhookCreate, db: Session = Depends(get_db), user: User = Depends(administrator)):
    validate_url(payload.url)
    secret, encrypted = new_secret()
    row = WebhookEndpoint(company_id=db.info["company_id"], created_by=user.id,
                          secret_ciphertext=encrypted, **payload.model_dump())
    db.add(row)
    db.flush()
    audit(db, user, row, "Create webhook")
    db.commit()
    return {**WebhookOut.model_validate(row).model_dump(), "secret": secret}


@router.post("/webhooks/{endpoint_id}/rotate", response_model=WebhookIssued)
def rotate_webhook(endpoint_id: int, db: Session = Depends(get_db), user: User = Depends(administrator)):
    row = owned(db, WebhookEndpoint, endpoint_id)
    if row.revoked_at:
        raise HTTPException(409, detail={"code": "integration_inactive", "message": "Integration is revoked or expired."})
    secret, encrypted = new_secret()
    row.secret_ciphertext = encrypted
    row.secret_version += 1
    audit(db, user, row, "Rotate webhook secret")
    db.commit()
    return {**WebhookOut.model_validate(row).model_dump(), "secret": secret}


@router.post("/webhooks/{endpoint_id}/revoke", response_model=WebhookOut)
def revoke_webhook(endpoint_id: int, db: Session = Depends(get_db), user: User = Depends(administrator)):
    row = owned(db, WebhookEndpoint, endpoint_id)
    row.revoked_at = row.revoked_at or datetime.utcnow()
    audit(db, user, row, "Revoke webhook")
    db.commit()
    return row


@router.get("/webhooks/{endpoint_id}/deliveries", response_model=list[DeliveryOut])
def deliveries(endpoint_id: int, before_id: int | None = None, limit: int = Query(50, ge=1, le=100),
               db: Session = Depends(get_db), user: User = Depends(administrator)):
    owned(db, WebhookEndpoint, endpoint_id)
    query = db.query(WebhookDelivery).filter(WebhookDelivery.endpoint_id == endpoint_id,
                                           WebhookDelivery.company_id == db.info["company_id"])
    if before_id is not None:
        query = query.filter(WebhookDelivery.id < before_id)
    return query.order_by(WebhookDelivery.id.desc()).limit(limit).all()


@router.post("/deliveries/{delivery_id}/retry", response_model=DeliveryOut, status_code=201)
def retry_delivery(delivery_id: int, db: Session = Depends(get_db), user: User = Depends(administrator)):
    old = owned(db, WebhookDelivery, delivery_id)
    endpoint = owned(db, WebhookEndpoint, old.endpoint_id)
    if endpoint.revoked_at or old.status not in {"Delivered", "Dead", "Failed"} or old.lease_token:
        raise HTTPException(409, detail={"code": "integration_retry_unavailable", "message": "This delivery cannot be resent now."})
    # Stop automatic retries for the old series; its attempts and payload remain available.
    if old.status == "Failed":
        old.status = "Dead"
    row = WebhookDelivery(company_id=old.company_id, endpoint_id=old.endpoint_id, event_id=old.event_id,
                          delivery_id=str(uuid4()), event_type=old.event_type, payload=old.payload, resend_of=old.id)
    db.add(row)
    db.flush()
    audit(db, user, row, "Resend webhook")
    db.commit()
    return row
