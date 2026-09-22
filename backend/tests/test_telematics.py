from datetime import datetime, timedelta, timezone
import json
import time
import pytest
from app import models as m
from app.services.webhooks import signature
from app.services import telematics
from app.db.session import set_tenant_context
from tests.test_integrations import context, auth, vehicle

BASE = "/api/v1/telematics"
SECRET = "local-test-signing-secret-32-bytes-minimum"

@pytest.fixture
def setup(context, monkeypatch):
    client, factory = context
    monkeypatch.setenv("TELEMATICS_TEST", SECRET)
    with factory() as db:
        first, second = vehicle(), vehicle(2, "AA222AA")
        first.odometer_km = 100
        first.vin_number = "TESTVIN123"
        db.add_all([first, second]); db.commit()
        vid, other = first.id, second.id
    response = client.post(BASE + "/connections", headers=auth(), json={"provider":"generic", "credentials_reference":"env:TELEMATICS_TEST"})
    assert response.status_code == 201, response.text
    cid = response.json()["id"]
    assert response.json()["status"] == "NotConfigured"
    assert "credentials_reference" not in response.text and SECRET not in response.text
    assert client.put(BASE + f"/connections/{cid}", headers=auth(), json={"enabled":True}).status_code == 200
    response = client.post(BASE + f"/connections/{cid}/mappings", headers=auth(), json={"vehicle_id":vid,"external_vehicle_id":"gps-1","vin":"testvin123","external_device_id":"device-1"})
    assert response.status_code == 201, response.text
    return client, factory, cid, vid, other, response.json()["id"]


def event(kind="odometer", eid="one", ago=5, **kwargs):
    data = {"kind":kind,"external_event_id":eid,"external_vehicle_id":"gps-1",
            "occurred_at":(datetime.now(timezone.utc)-timedelta(seconds=ago)).isoformat()}
    if kind == "odometer": data.update(odometer_km=110,confidence=1)
    if kind == "location": data.update(latitude=41.33,longitude=19.82,speed_kph=10,heading=40,ignition=True,idling=False)
    data.update(kwargs)
    return data


def send(setup, events):
    client, _, cid, *_ = setup
    return client.post(BASE+f"/connections/{cid}/events",headers=auth(),json={"events":events})


def enable(setup):
    client, _, _, _, _, mid = setup
    return client.put(BASE+f"/mappings/{mid}/odometer-policy",headers=auth(),json={"enabled":True})


def test_provider_readiness_and_secrets(setup):
    client, factory, cid, *_ = setup
    options = client.get(BASE+"/providers",headers=auth()).json()
    assert [o["provider"] for o in options if o["adapter_available"]] == ["generic"]
    for provider in ("geotab","samsara","motive","oem"):
        row=client.post(BASE+"/connections",headers=auth(),json={"provider":provider,"credentials_reference":"env:TELEMATICS_TEST"}).json()
        assert client.put(BASE+f"/connections/{row['id']}",headers=auth(),json={"enabled":True}).status_code==503
    for payload in ({"provider":"generic","credentials_reference":SECRET}, {"provider":"generic","settings":{"token":SECRET}}):
        response=client.post(BASE+"/connections",headers=auth(),json=payload)
        assert response.status_code==422 and SECRET not in response.text
    listing=client.get(BASE+"/connections",headers=auth()).text
    assert SECRET not in listing and "env:TELEMATICS_TEST" not in listing
    with factory() as db:
        assert SECRET not in str([r.new_values for r in db.query(m.AuditLog)])
        assert "credentials_reference" not in str([r.new_values for r in db.query(m.AuditLog)])


def test_connection_toggle_preserves_settings_and_partial_updates(setup):
    client, factory, cid, vid, *_ = setup
    endpoint = BASE + f"/connections/{cid}"
    settings = {"min_confidence": 0.99, "max_reading_age_seconds": 120, "online_after_seconds": 300}
    response = client.put(endpoint, headers=auth(), json={"enabled": True, "settings": settings})
    assert response.status_code == 200, response.text
    assert response.json()["settings"] == settings

    for enabled, status in ((False, "Disabled"), (True, "Ready")):
        response = client.put(endpoint, headers=auth(), json={"enabled": enabled})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status
        assert response.json()["settings"] == settings

    response = client.put(endpoint, headers=auth(), json={"enabled": True, "settings": {"online_after_seconds": 600}})
    assert response.status_code == 200, response.text
    assert response.json()["settings"] == {**settings, "online_after_seconds": 600}
    assert client.put(endpoint, headers=auth(), json={"enabled": True, "settings": {"min_confidence": None}}).status_code == 422

    enable(setup)
    response = send(setup, [event(eid="below_configured_confidence", confidence=0.95)])
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["result"] == "low_confidence"
    with factory() as db:
        assert db.get(m.Vehicle, vid).odometer_km == 100


def test_mapping_conflicts_and_tenant_boundaries(setup):
    client, factory, cid, vid, other, mid=setup
    for payload in ({"vehicle_id":vid,"external_vehicle_id":"other"}, {"vehicle_id":vid,"external_vehicle_id":"gps-1"},
                    {"vehicle_id":vid,"external_vehicle_id":"new","vin":"WRONG"}):
        assert client.post(BASE+f"/connections/{cid}/mappings",headers=auth(),json=payload).status_code==409
    assert client.post(BASE+f"/connections/{cid}/mappings",headers=auth(),json={"vehicle_id":other,"external_vehicle_id":"other"}).status_code==404
    assert client.get(BASE+"/connections",headers=auth(2)).json()==[]
    for path in (f"/connections/{cid}/mappings", f"/vehicles/{vid}/summary", f"/vehicles/{vid}/events/location"):
        assert client.get(BASE+path,headers=auth(2)).status_code==404
        assert client.get(BASE+path,headers=auth(3)).status_code==403
    assert client.put(BASE+f"/mappings/{mid}/odometer-policy",headers=auth(2),json={"enabled":True}).status_code==404
    assert send(setup,[event(external_vehicle_id="unmapped")]).status_code==409
    with factory() as db:
        set_tenant_context(db,2)
        assert db.query(m.ExternalVehicleMapping).count()==0
        assert db.query(m.OdometerEvent).count()==0


def test_duplicates_changed_replay_and_atomic_batch(setup):
    client, factory, cid, vid, *_=setup
    enable(setup)
    one=event()
    assert send(setup,[one]).json()["results"][0]["result"]=="applied"
    assert send(setup,[one]).json()["results"][0]["result"]=="duplicate"
    assert send(setup,[{**one,"odometer_km":111}]).status_code==409
    assert send(setup,[event(eid="rollback",odometer_km=120,ago=3), event(eid="missing",external_vehicle_id="missing",ago=2)]).status_code==409
    with factory() as db:
        assert db.get(m.Vehicle,vid).odometer_km==110
        assert db.query(m.OdometerEvent).count()==1
        audits=db.query(m.AuditLog).filter_by(action_code="telematics_odometer_synchronized").all()
        assert len(audits)==1 and audits[0].company_id==1
        assert audits[0].old_values["odometer_km"]==100 and audits[0].new_values["odometer_km"]==110


def test_odometer_guards_and_manual_override(setup):
    client,factory,cid,vid,_,mid=setup
    assert send(setup,[event(eid="disabled")]).json()["results"][0]["result"]=="disabled"
    enable(setup)
    cases=[("low_confidence",dict(confidence=0.5)),("stale",dict(ago=7200)),("decreasing",dict(odometer_km=99)),("applied",dict(odometer_km=110,ago=4)),("out_of_order",dict(odometer_km=120,ago=10))]
    for expected,changes in cases:
        response=send(setup,[event(eid=expected,**changes)])
        assert response.status_code==200,response.text
        assert response.json()["results"][0]["result"]==expected
    with factory() as db:
        row=db.get(m.Vehicle,vid); assert not row.odometer_manual_override
        row.odometer_km=125;db.commit();assert row.odometer_manual_override
    assert send(setup,[event(eid="manual",odometer_km=130,ago=2)]).json()["results"][0]["result"]=="manual_override"
    assert client.put(BASE+f"/mappings/{mid}/odometer-policy",headers=auth(),json={"enabled":True,"release_manual_override":True}).status_code==200
    assert send(setup,[event(eid="released",odometer_km=130,ago=1)]).json()["results"][0]["result"]=="applied"
    with factory() as db: assert db.get(m.Vehicle,vid).odometer_km==130


@pytest.mark.parametrize("changes",[{"latitude":91},{"latitude":-91},{"longitude":181},{"longitude":-181},{"speed_kph":-1},{"heading":360},{"occurred_at":"2026-01-01T00:00:00"}])
def test_invalid_location(setup,changes):
    assert send(setup,[event("location",**changes)]).status_code==422


def test_all_event_types_summary_order_and_unknown(setup):
    client,factory,cid,vid,*_=setup
    assert client.get(BASE+f"/vehicles/{vid}/summary",headers=auth()).json()["connectivity"]=="unknown"
    now=datetime.now(timezone.utc)
    events=[event("location",eid="latest"), event("location",eid="older",ago=120,latitude=40),
            event("engine_hours",engine_hours=200),event("fuel_level",fuel_percent=60),
            event("battery_level",soc_percent=90),event("diagnostic",code="P0300",active=True),
            event("behavior",behavior="harsh_braking",duration_seconds=3),
            event("trip",ago=120,ended_at=(now-timedelta(seconds=10)).isoformat(),distance_km=10,idle_seconds=20)]
    assert send(setup,events).status_code==200
    result=client.get(BASE+f"/vehicles/{vid}/summary",headers=auth()).json()
    assert result["connectivity"]=="online" and float(result["last_location"]["latitude"])==41.33
    assert len(result["diagnostic_alerts"])==1 and result["mileage_today_km"] is None
    assert result["last_location"]["occurred_at"].endswith("+00:00")
    assert client.get(BASE+f"/vehicles/{vid}/events/trip",headers=auth()).json()[0]["idle_seconds"]==20
    assert send(setup,[event("diagnostic",eid="clear",code="P0300",active=False,ago=1)]).status_code==200
    assert client.get(BASE+f"/vehicles/{vid}/summary",headers=auth()).json()["diagnostic_alerts"]==[]
    with factory() as db:
        set_tenant_context(db,1)
        assert telematics.summary(db,vid,now=datetime.utcnow()+timedelta(hours=1))["connectivity"]=="offline"
    page=client.get(BASE+f"/vehicles/{vid}/events/location?limit=1",headers=auth()).json()
    assert page[0]["external_event_id"]=="latest"
    page=client.get(BASE+f"/vehicles/{vid}/events/location?before_id={page[0]['id']}",headers=auth()).json()
    assert page[0]["external_event_id"]=="older"
    assert send(setup,[event(ago=-3600)]).status_code==422


def test_webhook_signatures_replay_and_failure_state(setup):
    client,factory,cid,vid,*_=setup
    body=json.dumps({"events":[event("location")]}).encode()
    def post(body=body,secret=SECRET,age=0,signed_cid=cid):
        header=signature(secret,int(time.time())-age,f"{signed_cid}:delivery-one",body)
        return client.post(BASE+f"/webhooks/{cid}",content=body,headers={"X-VFC-Delivery":"delivery-one","X-VFC-Signature":header,"Content-Type":"application/json"})
    assert post(secret="bad").status_code==401
    assert post(age=301).status_code==401
    assert post(signed_cid=cid+1).status_code==401
    assert post().status_code==200
    assert post().json()["results"][0]["result"]=="duplicate"
    assert post(body=b'{"events":[{"secret":"do-not-echo"}]}').status_code==422
    result=client.get(BASE+"/connections",headers=auth()).json()[0]
    assert result["last_error"]=="telematics_invalid_payload" and result["last_sync_at"]
    assert post().status_code==200
    assert client.get(BASE+"/connections",headers=auth()).json()[0]["last_error"] is None
    with factory() as db: assert db.query(m.VehicleLocationEvent).count()==1
    assert client.put(BASE+f"/connections/{cid}",headers=auth(),json={"enabled":False}).status_code==200
    assert post().status_code==401


def test_delayed_location_and_daily_metrics(setup):
    client, factory, cid, vid, *_ = setup
    # A deterministic local day avoids midnight/DST-dependent assertions.
    now = datetime(2026, 9, 18, 12)
    from app.telematics_schemas import EventBatch
    batch = {"events": [
        event("location", eid="new", occurred_at="2026-09-18T11:59:00Z"),
        event(eid="m1", occurred_at="2026-09-18T08:00:00Z", odometer_km=100),
        event(eid="m2", occurred_at="2026-09-18T11:00:00Z", odometer_km=140),
        event("trip", occurred_at="2026-09-18T10:00:00Z", ended_at="2026-09-18T11:00:00Z", distance_km=40, idle_seconds=600),
    ]}
    with factory() as db:
        set_tenant_context(db, 1)
        db.add(m.CompanySettings(company_id=1, timezone="Europe/Tirane")); db.commit()
        telematics.ingest(db, cid, EventBatch.model_validate(batch), now=now); db.commit()
        telematics.ingest(db, cid, EventBatch.model_validate({"events": [event("location", eid="old", occurred_at="2026-09-18T07:00:00Z", latitude=40)]}), now=now); db.commit()
        result = telematics.summary(db, vid, now=now)
        assert result["last_location"]["external_event_id"] == "new"
        assert result["mileage_today_km"] == 40
        assert result["idling_today_seconds"] == 600
        assert result["timezone"] == "Europe/Tirane"


def test_device_and_vin_conflicts_across_vehicles(setup):
    client, factory, cid, vid, *_ = setup
    with factory() as db:
        second = vehicle(1, "AA333AA"); db.add(second); db.commit(); sid = second.id
    for fields in ({"external_device_id":"device-1"}, {"vin":"TESTVIN123"}, {"external_vehicle_id":"gps-1"}):
        payload = {"vehicle_id":sid,"external_vehicle_id":"gps-2", **fields}
        response = client.post(BASE+f"/connections/{cid}/mappings", headers=auth(), json=payload)
        assert response.status_code == 409, response.text
    response = client.post(BASE+f"/connections/{cid}/mappings", headers=auth(), json={"vehicle_id":sid,"external_vehicle_id":"gps-2"})
    assert response.status_code == 201


def test_fresh_and_populated_migration(tmp_path, monkeypatch):
    from alembic import command
    from sqlalchemy import create_engine, inspect, text
    from app.core.config import get_settings
    from app.db.session import Base
    from tests.test_fuel_migration import alembic_config
    names = ["IntegrationConnections", "ExternalVehicleMappings"] + [model.__tablename__ for model in telematics.EVENT_MODELS.values()]
    url = f"sqlite:///{tmp_path / 'telematics.db'}"
    monkeypatch.setenv("DATABASE_URL", url); get_settings.cache_clear()
    engine = create_engine(url)
    try:
        config = alembic_config(url)
        command.upgrade(config, "head")
        assert set(names) <= set(inspect(engine).get_table_names())
        command.downgrade(config, "20260917_0023")
        assert "OdometerManualOverride" not in {c["name"] for c in inspect(engine).get_columns("Vehicles")}
        with engine.begin() as db:
            db.execute(text('INSERT INTO "Vehicles" ("CompanyId", "Brand", "Model", "FuelType", "VehicleLocation", "LicensePlate", "RegistrationCountry", "LicensePlateNormalized", "Status", "OwnershipType", "DepreciationMethod", "Archived", "OdometerKm") VALUES (1, \'Test\', \'Car\', \'Diesel\', \'HQ\', \'AA111AA\', \'AL\', \'AA111AA\', 0, \'Owned\', \'Straight Line\', 0, 12345)'))
        command.upgrade(config, "head")
        with engine.connect() as db:
            assert db.execute(text('SELECT "OdometerKm", "OdometerManualOverride", "TelematicsOdometerAt" FROM "Vehicles"')).one() == (12345, 0, None)
        for name in names:
            assert {c["name"] for c in inspect(engine).get_columns(name)} == set(Base.metadata.tables[name].columns.keys())
            assert {i["name"] for i in inspect(engine).get_indexes(name)} == {i.name for i in Base.metadata.tables[name].indexes}
    finally:
        engine.dispose(); get_settings.cache_clear()


def test_concurrent_duplicate_and_monotonic_ingestion(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.session import Base, TenantSession
    from app.telematics_schemas import EventBatch
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=TenantSession, expire_on_commit=False)
    with factory() as db:
        db.add(m.Company(id=1, name="Company", slug="company"))
        car = vehicle(); car.odometer_km = 100; db.add(car)
        conn = m.IntegrationConnection(company_id=1, provider="generic", status="Ready", settings={})
        db.add(conn); db.flush()
        cid, vid = conn.id, car.id
        db.add(m.ExternalVehicleMapping(company_id=1, connection_id=cid, vehicle_id=vid, external_vehicle_id="gps-1", odometer_sync_enabled=True)); db.commit()
    batch = EventBatch.model_validate({"events":[event()]})
    def ingest(batch):
        with factory() as db:
            set_tenant_context(db,1)
            result = telematics.ingest(db,cid,batch)
            db.commit()
            return result["results"][0]["result"]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(ingest, [batch,batch]))
        assert sorted(results) == ["applied", "duplicate"]
        newer = EventBatch.model_validate({"events":[event(eid="newer",odometer_km=130,ago=1)]})
        older = EventBatch.model_validate({"events":[event(eid="older",odometer_km=120,ago=3)]})
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(ingest,[newer,older]))
        with factory() as db:
            assert db.get(m.Vehicle,vid).odometer_km == 130
            assert db.query(m.OdometerEvent).count() == 3
    finally:
        engine.dispose()


def test_precision_and_ambiguous_trip_totals(setup):
    client, factory, cid, vid, *_ = setup
    enable(setup)
    assert send(setup,[event(eid="precision",confidence=0.89999999)]).json()["results"][0]["result"] == "low_confidence"
    assert send(setup,[event("location",heading=359.99999999)]).status_code == 200
    with factory() as db:
        assert float(db.query(m.OdometerEvent).one().confidence) < 0.9
        assert float(db.query(m.VehicleLocationEvent).one().heading) < 360
    from app.telematics_schemas import EventBatch
    with factory() as db:
        set_tenant_context(db,1)
        for eid in ("trip1", "trip2"):
            batch=EventBatch.model_validate({"events":[event("trip",eid=eid,occurred_at="2026-09-18T10:00:00Z",ended_at="2026-09-18T11:00:00Z",distance_km=10,idle_seconds=30)]})
            telematics.ingest(db,cid,batch,now=datetime(2026,9,18,12));db.commit()
        assert telematics.summary(db,vid,now=datetime(2026,9,18,12))["idling_today_seconds"] is None
