"""Tenant-scoped, transactional canonical ingestion and future dashboard queries."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from app import models as m
from app.services.audit import record_audit
from app.telematics_schemas import ConnectionSettings

EVENT_MODELS = {
    "location": m.VehicleLocationEvent, "trip": m.Trip, "odometer": m.OdometerEvent,
    "engine_hours": m.EngineHourEvent, "fuel_level": m.FuelLevelEvent,
    "battery_level": m.BatteryLevelEvent, "diagnostic": m.DiagnosticCodeEvent,
    "behavior": m.DriverBehaviorEvent,
}


def fail(code, status=409):
    raise HTTPException(status, detail={"code": "telematics_" + code})


def owned(db, model, row_id, *, lock=False):
    query = db.query(model).filter(model.id == row_id, model.company_id == db.info["company_id"])
    if lock:
        query = query.populate_existing().with_for_update()
    row = query.first()
    if row is None:
        fail("not_found", 404)
    return row


def vehicle(db, vehicle_id, *, lock=False):
    row = owned(db, m.Vehicle, vehicle_id, lock=lock)
    if row.archived:
        fail("vehicle_archived")
    return row


def create_mapping(db, connection_id, payload, user):
    connection = owned(db, m.IntegrationConnection, connection_id, lock=True)
    car = vehicle(db, payload.vehicle_id, lock=True)
    if payload.vin and car.vin_number and payload.vin != car.vin_number.strip().upper():
        fail("mapping_conflict")
    # Prevent a VIN from silently identifying a different internal vehicle.
    vin = payload.vin or (car.vin_number.strip().upper() if car.vin_number else None)
    if vin and db.query(m.Vehicle.id).filter(m.Vehicle.company_id == car.company_id,
            m.Vehicle.id != car.id, m.Vehicle.vin_number.ilike(vin)).first():
        fail("mapping_conflict")
    query = db.query(m.ExternalVehicleMapping).filter(
        m.ExternalVehicleMapping.company_id == car.company_id,
        m.ExternalVehicleMapping.connection_id == connection.id)
    conflicts = [m.ExternalVehicleMapping.vehicle_id == car.id,
                 m.ExternalVehicleMapping.external_vehicle_id == payload.external_vehicle_id]
    if vin:
        conflicts.append(m.ExternalVehicleMapping.vin == vin)
    if payload.external_device_id:
        conflicts.append(m.ExternalVehicleMapping.external_device_id == payload.external_device_id)
    if query.filter(or_(*conflicts)).first():
        fail("mapping_conflict")
    row = m.ExternalVehicleMapping(company_id=car.company_id, connection_id=connection.id,
                                   **{**payload.model_dump(), "vin": vin})
    try:
        db.add(row)
        db.flush()
    except IntegrityError:
        db.rollback()
        fail("mapping_conflict")
    record_audit(db, user=user, action="Telematics mapping created", entity_type="ExternalVehicleMapping",
                 entity_id=row.id, new_values={"vehicle_id": car.id, "connection_id": connection.id})
    return row


def synchronize_odometer(db, connection, mapping, car, event, now):
    settings = ConnectionSettings.model_validate(connection.settings)
    value = event.odometer_km
    if not mapping.odometer_sync_enabled:
        result = "disabled"
    elif car.odometer_manual_override:
        result = "manual_override"
    elif event.confidence < settings.min_confidence:
        result = "low_confidence"
    elif (now - event.occurred_at).total_seconds() > settings.max_reading_age_seconds:
        result = "stale"
    elif car.telematics_odometer_at and event.occurred_at <= car.telematics_odometer_at:
        result = "out_of_order"
    elif car.odometer_km is not None and value < car.odometer_km:
        result = "decreasing"
    else:
        previous = car.odometer_km
        # Vehicle stores whole km; floor positive fractional readings, never round upward.
        car.odometer_km = int(value)
        car.telematics_odometer_at = event.occurred_at
        result = "applied"
        record_audit(db, action="Telematics odometer synchronized", entity_type="Vehicle", entity_id=car.id,
            old_values={"odometer_km": previous}, new_values={"odometer_km": car.odometer_km,
            "provider": connection.provider, "connection_id": connection.id,
            "external_event_id": event.external_event_id, "occurred_at": event.occurred_at})
        # Flush only this automatic change under the guard; all ordinary ORM mileage writes lock it.
        db.info["telematics_odometer_write"] = car.id
        try:
            db.flush()
        finally:
            db.info.pop("telematics_odometer_write", None)
    event.sync_result = result


def ingest(db, connection_id, batch, *, now=None):
    now = now or datetime.utcnow()
    connection = owned(db, m.IntegrationConnection, connection_id, lock=True)
    if connection.status != "Ready":
        fail("inactive")
    # Start a real write transaction before savepoints (including SQLite), and
    # serialize concurrent ingestion for this connection before loading vehicles.
    db.query(m.IntegrationConnection).filter(m.IntegrationConnection.id == connection.id,
        m.IntegrationConnection.company_id == connection.company_id).update(
            {m.IntegrationConnection.last_sync_at: now}, synchronize_session=False)
    results = []
    # Consistent lock order across concurrent batches/connections.
    mappings = db.query(m.ExternalVehicleMapping).filter(
        m.ExternalVehicleMapping.company_id == connection.company_id,
        m.ExternalVehicleMapping.connection_id == connection.id,
        m.ExternalVehicleMapping.external_vehicle_id.in_({e.external_vehicle_id for e in batch.events})).order_by(
            m.ExternalVehicleMapping.id).with_for_update().all()
    by_external = {row.external_vehicle_id: row for row in mappings}
    cars = {vid: vehicle(db, vid, lock=True) for vid in sorted({row.vehicle_id for row in mappings})}
    for item in sorted(batch.events, key=lambda event: event.occurred_at):
        mapping = by_external.get(item.external_vehicle_id)
        if mapping is None:
            fail("mapping_missing")
        if item.occurred_at > now or (item.kind == "trip" and item.ended_at > now):
            fail("future_event", 422)
        model = EVENT_MODELS[item.kind]
        digest = hashlib.sha256(json.dumps(item.model_dump(mode="json"), sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()
        query = db.query(model).filter(model.company_id == connection.company_id,
            model.connection_id == connection.id, model.external_event_id == item.external_event_id)
        existing = query.first()
        if existing:
            if existing.payload_hash != digest:
                fail("event_conflict")
            results.append({"external_event_id": item.external_event_id, "kind": item.kind, "result": "duplicate"})
            continue
        data = item.model_dump(exclude={"kind", "external_vehicle_id"})
        event = model(company_id=connection.company_id, connection_id=connection.id,
            provider=connection.provider, vehicle_id=mapping.vehicle_id, payload_hash=digest,
            received_at=now, **data)
        try:
            with db.begin_nested():
                db.add(event)
                db.flush()
        except IntegrityError:
            existing = query.first()
            if existing is None or existing.payload_hash != digest:
                fail("event_conflict")
            results.append({"external_event_id": item.external_event_id, "kind": item.kind, "result": "duplicate"})
            continue
        if item.kind == "odometer":
            synchronize_odometer(db, connection, mapping, cars[mapping.vehicle_id], event, now)
        results.append({"external_event_id": item.external_event_id, "kind": item.kind,
                        "result": event.sync_result if item.kind == "odometer" else "stored"})
    connection.last_sync_at = now
    connection.last_error = None
    db.flush()
    return {"results": results}


def event_output(row):
    from sqlalchemy import inspect
    hidden = {"company_id", "payload_hash"}
    # Explicit canonical model columns only; no source payloads or credentials.
    data = {a.key: getattr(row, a.key) for a in inspect(type(row)).column_attrs if a.key not in hidden}
    return {k: v.replace(tzinfo=timezone.utc).isoformat() if isinstance(v, datetime) else v for k, v in data.items()}


def events_query(db, model, vehicle_id):
    return db.query(model).filter(model.company_id == db.info["company_id"], model.vehicle_id == vehicle_id)


def summary(db, vehicle_id, *, now=None):
    vehicle(db, vehicle_id)
    now = now or datetime.utcnow()
    last = {}
    for kind, model in EVENT_MODELS.items():
        last[kind] = events_query(db, model, vehicle_id).filter(model.occurred_at <= now).order_by(
            model.occurred_at.desc(), model.id.desc()).first()
    # Trip receipt/start time does not prove a device is currently connected.
    signals = [row for kind, row in last.items() if kind != "trip" and row]
    latest = max(signals, key=lambda row: (row.occurred_at, row.id)) if signals else None
    state = "unknown"
    if latest:
        conn = owned(db, m.IntegrationConnection, latest.connection_id)
        threshold = ConnectionSettings.model_validate(conn.settings).online_after_seconds
        state = "online" if conn.status == "Ready" and (now - latest.occurred_at).total_seconds() <= threshold else "offline"
    company_settings = db.query(m.CompanySettings).filter(m.CompanySettings.company_id == db.info["company_id"]).first()
    try:
        zone = ZoneInfo(company_settings.timezone if company_settings else "UTC")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    local_midnight = now.replace(tzinfo=timezone.utc).astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    start = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
    end = (local_midnight + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
    # Within-day observed odometer delta; never fabricate a midnight baseline.
    readings = events_query(db, m.OdometerEvent, vehicle_id).filter(
        m.OdometerEvent.occurred_at >= start, m.OdometerEvent.occurred_at < min(end, now + timedelta(microseconds=1)),
        m.OdometerEvent.confidence >= 0.9).order_by(m.OdometerEvent.occurred_at).all()
    mileage = None
    if len(readings) >= 2 and len({r.connection_id for r in readings}) == 1 and all(
            b.odometer_km >= a.odometer_km for a, b in zip(readings, readings[1:])):
        mileage = readings[-1].odometer_km - readings[0].odometer_km
    # Only complete trips entirely inside the day; report missing data as unknown.
    trips = events_query(db, m.Trip, vehicle_id).filter(m.Trip.occurred_at >= start, m.Trip.ended_at <= now).order_by(m.Trip.occurred_at).all()
    idle = None
    if trips and len({t.connection_id for t in trips}) == 1 and all(
            following.occurred_at >= previous.ended_at for previous, following in zip(trips, trips[1:])):
        idle = sum(t.idle_seconds for t in trips)
    diagnostics = events_query(db, m.DiagnosticCodeEvent, vehicle_id).order_by(
        m.DiagnosticCodeEvent.occurred_at.desc(), m.DiagnosticCodeEvent.id.desc()).all()
    latest_codes = {}
    for row in diagnostics:
        latest_codes.setdefault((row.connection_id, row.code), row)
    return {"vehicle_id": vehicle_id, "connectivity": state,
        "last_seen_at": event_output(latest)["occurred_at"] if latest else None,
        "last_location": event_output(last["location"]) if last["location"] else None,
        "mileage_today_km": mileage, "mileage_basis": "observed_odometer_delta", "timezone": str(zone),
        "idling_today_seconds": idle, "idling_basis": "completed_trips_inside_day",
        "diagnostic_alerts": [event_output(row) for row in latest_codes.values() if row.active],
        "latest_readings": {kind: event_output(last[kind]) if last[kind] else None
                            for kind in ("odometer", "engine_hours", "fuel_level", "battery_level")}}
