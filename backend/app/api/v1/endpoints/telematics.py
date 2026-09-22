"""Administrative telematics foundation; commercial adapters remain unavailable."""
import time
from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session
from app import models as m
from app.api.v1.endpoints.integrations import administrator
from app.db.session import get_db, set_tenant_context
from app.services import telematics as service
from app.services.audit import record_audit
from app.services.telematics_providers import ADAPTERS, resolve_credentials
from app.services.webhooks import verify_signature
from app.telematics_schemas import (ConnectionCreate, ConnectionUpdate, ConnectionOut,
    MappingCreate, MappingOut, OdometerPolicy, EventBatch)

router = APIRouter()


def audit(db, user, row, action):
    record_audit(db, user=user, action=action, entity_type=type(row).__name__, entity_id=row.id,
                 new_values={"id": row.id})


@router.get("/providers")
def providers(user=Depends(administrator)):
    return [{"provider": provider, "adapter_available": provider in ADAPTERS,
             "operational": False} for provider in ("generic", "geotab", "samsara", "motive", "oem")]


@router.get("/connections", response_model=list[ConnectionOut])
def connections(db: Session = Depends(get_db), user=Depends(administrator)):
    return db.query(m.IntegrationConnection).filter(m.IntegrationConnection.company_id == db.info["company_id"]).all()


@router.post("/connections", response_model=ConnectionOut, status_code=201)
def create_connection(payload: ConnectionCreate, db: Session = Depends(get_db), user=Depends(administrator)):
    row = m.IntegrationConnection(company_id=db.info["company_id"], **payload.model_dump())
    db.add(row)
    db.flush()
    audit(db, user, row, "Telematics connection created")
    db.commit()
    return row


@router.put("/connections/{connection_id}", response_model=ConnectionOut)
def configure_connection(connection_id: int, payload: ConnectionUpdate,
                         db: Session = Depends(get_db), user=Depends(administrator)):
    row = service.owned(db, m.IntegrationConnection, connection_id, lock=True)
    row.credentials_reference = payload.credentials_reference or row.credentials_reference
    row.settings = payload.settings.model_dump()
    if payload.enabled:
        if row.provider not in ADAPTERS or not resolve_credentials(row.credentials_reference):
            service.fail("not_configured", 503)
        row.status = "Ready"
    else:
        row.status = "Disabled"
    audit(db, user, row, "Telematics connection configured")
    db.commit()
    return row


@router.get("/connections/{connection_id}/mappings", response_model=list[MappingOut])
def mappings(connection_id: int, db: Session = Depends(get_db), user=Depends(administrator)):
    service.owned(db, m.IntegrationConnection, connection_id)
    return db.query(m.ExternalVehicleMapping).filter(m.ExternalVehicleMapping.company_id == db.info["company_id"],
                                                    m.ExternalVehicleMapping.connection_id == connection_id).all()


@router.post("/connections/{connection_id}/mappings", response_model=MappingOut, status_code=201)
def map_vehicle(connection_id: int, payload: MappingCreate, db: Session = Depends(get_db), user=Depends(administrator)):
    row = service.create_mapping(db, connection_id, payload, user)
    db.commit()
    return row


@router.put("/mappings/{mapping_id}/odometer-policy", response_model=MappingOut)
def odometer_policy(mapping_id: int, payload: OdometerPolicy, db: Session = Depends(get_db), user=Depends(administrator)):
    mapping = service.owned(db, m.ExternalVehicleMapping, mapping_id, lock=True)
    car = service.vehicle(db, mapping.vehicle_id, lock=True)
    mapping.odometer_sync_enabled = payload.enabled
    if payload.release_manual_override:
        car.odometer_manual_override = False
    record_audit(db, user=user, action="Telematics odometer policy changed", entity_type="Vehicle", entity_id=car.id,
                 new_values={"mapping_id": mapping.id, **payload.model_dump()})
    db.commit()
    return mapping


@router.post("/connections/{connection_id}/events")
def ingest_events(connection_id: int, payload: EventBatch, db: Session = Depends(get_db), user=Depends(administrator)):
    # Canonical testing/import entry point; cannot imply a commercial adapter exists.
    connection = service.owned(db, m.IntegrationConnection, connection_id)
    if connection.provider not in ADAPTERS:
        service.fail("not_configured", 503)
    result = service.ingest(db, connection_id, payload)
    db.commit()
    return result


@router.post("/webhooks/{connection_id}")
async def webhook(connection_id: int, request: Request, db: Session = Depends(get_db)):
    # Inbound HMAC authentication is separate from browser cookies and API keys.
    # The signed connection ID prevents replay across two connections sharing a key.
    row = db.query(m.IntegrationConnection).join(m.Company, m.Company.id == m.IntegrationConnection.company_id).filter(
        m.IntegrationConnection.id == connection_id, m.Company.is_active.is_(True)).first()
    secret = resolve_credentials(row.credentials_reference) if row else None
    delivery = request.headers.get("X-VFC-Delivery", "")
    if not row or row.status != "Ready" or not secret or not 1 <= len(delivery) <= 200:
        service.fail("webhook_auth", 401)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024 * 1024:
            service.fail("payload_size", 413)
    if not verify_signature(secret, request.headers.get("X-VFC-Signature", ""),
                            f"{connection_id}:{delivery}", bytes(body), now=int(time.time())):
        service.fail("webhook_auth", 401)
    set_tenant_context(db, row.company_id)
    adapter = ADAPTERS.get(row.provider)
    if not adapter:
        service.fail("not_configured", 503)
    try:
        batch = adapter.normalize(bytes(body))
    except ValidationError:
        # Never echo provider payloads or raw parser/credential errors.
        row.last_error = "telematics_invalid_payload"
        db.commit()
        service.fail("invalid_payload", 422)
    try:
        result = service.ingest(db, row.id, batch)
        db.commit()
        return result
    except Exception as exc:
        from fastapi import HTTPException
        db.rollback()
        if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
            row = service.owned(db, m.IntegrationConnection, connection_id)
            row.last_error = exc.detail["code"]
            db.commit()
        raise


@router.get("/vehicles/{vehicle_id}/summary")
def vehicle_summary(vehicle_id: int, db: Session = Depends(get_db), user=Depends(administrator)):
    return service.summary(db, vehicle_id)


@router.get("/vehicles/{vehicle_id}/events/{kind}")
def vehicle_events(vehicle_id: int, kind: str, before_id: int | None = None,
                   limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user=Depends(administrator)):
    service.vehicle(db, vehicle_id)
    model = service.EVENT_MODELS.get(kind)
    if model is None:
        service.fail("not_found", 404)
    query = service.events_query(db, model, vehicle_id)
    if before_id is not None:
        # A stable (occurred_at, id) cursor handles delayed events correctly.
        cursor = query.filter(model.id == before_id).first()
        if cursor is None:
            service.fail("not_found", 404)
        from sqlalchemy import or_, and_
        query = query.filter(or_(model.occurred_at < cursor.occurred_at,
                    and_(model.occurred_at == cursor.occurred_at, model.id < cursor.id)))
    return [service.event_output(row) for row in query.order_by(model.occurred_at.desc(), model.id.desc()).limit(limit)]
