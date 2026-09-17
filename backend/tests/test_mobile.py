"""Offline HTTP boundary, transactional receipts, ownership and migration coverage."""
import asyncio
import io
from datetime import datetime
import subprocess
import os
import sys

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile, Headers
from starlette.requests import Request

from tests.test_service_programs import ctx
from tests.test_inspection_templates import template
from tests.test_vehicle_checkout_return import make_driver
from app.api.v1.endpoints import mobile, inspections
from app.core.security import get_current_user
from app.db.session import get_db, set_tenant_context
from app.main import app
from app.models import Inspection, MobileOperation, User, Vehicle, VehicleAccident, CompanyUser, Attachment

REQUEST = Request({"type": "http", "scheme": "http", "server": ("testserver", 80), "path": "/api/v1/mobile/sync", "headers": []})

def operation(ctx, kind="prepare", **changes):
    db, user, vehicle, *_ = ctx
    return mobile.Operation(key="operation-12345", company_id=1, user_id=user.id, kind=kind,
        payload={"vehicle_id": vehicle.id, "inspection_type": "Daily", "inspection_date": "17-09-2026"}, **changes)

def prepare(ctx):
    return mobile.synchronize(operation(ctx), REQUEST, ctx[0], ctx[1])

def completion(ctx, record):
    return mobile.Operation(key="complete-12345", company_id=1, user_id=ctx[1].id, kind="inspection",
        inspection_id=record['id'], expected_updated_at=record['updated_at'],
        payload={"vehicle_id":record['vehicle_id'],"driver_id":record['driver_id'],"inspection_type":record['inspection_type'],
            "inspection_date":record['inspection_date'],"complete":True,
            "items":[dict(i, status="Pass") for i in record['items']]})

def test_prepare_and_completion_are_idempotent_and_atomic(ctx):
    template(ctx)
    first=prepare(ctx); again=prepare(ctx)
    assert first==again
    db,user,*_=ctx
    assert db.query(Inspection).count()==1
    op=completion(ctx,first)
    done=mobile.synchronize(op,REQUEST,db,user)
    assert done['completed_at']
    assert mobile.synchronize(op,REQUEST,db,user)==done
    assert db.query(MobileOperation).count()==2
    op.payload['notes']='different retry data'
    with pytest.raises(HTTPException) as exc: mobile.synchronize(op,REQUEST,db,user)
    assert exc.value.status_code==409

def test_conflict_never_overwrites_server_and_rolls_back_receipt(ctx):
    template(ctx); first=prepare(ctx); db,user,*_=ctx
    row=db.get(Inspection,first['id']); row.notes='Concurrent server edit'; row.updated_at=datetime.utcnow(); db.commit()
    with pytest.raises(HTTPException) as exc: mobile.synchronize(completion(ctx,first),REQUEST,db,user)
    assert exc.value.status_code==409
    assert db.get(Inspection,first['id']).notes=='Concurrent server edit'
    assert db.query(MobileOperation).count()==1

def test_validation_failure_can_be_corrected_without_consuming_key(ctx):
    template(ctx,comment_required_on_failure=True); first=prepare(ctx); op=completion(ctx,first)
    op.payload['items'][0]['status']='Fail'
    with pytest.raises(HTTPException): mobile.synchronize(op,REQUEST,ctx[0],ctx[1])
    assert ctx[0].query(MobileOperation).count()==1
    op.payload['items'][0]['comment']='Damaged brake'
    assert mobile.synchronize(op,REQUEST,ctx[0],ctx[1])['completed_at']

def test_default_checklist_is_frozen_for_offline(ctx):
    first=prepare(ctx)
    assert first['template_snapshot']['offline_default']
    done=mobile.synchronize(completion(ctx,first),REQUEST,ctx[0],ctx[1])
    assert done['completed_at'] and done['overall_status']=='Passed'

def test_http_auth_and_account_boundaries(ctx):
    db,user,*_=ctx
    app.dependency_overrides[get_db]=lambda: db
    client=TestClient(app)
    assert client.get('/api/v1/mobile/home').status_code==401
    app.dependency_overrides[get_current_user]=lambda: user
    op=operation(ctx).model_dump(mode='json');op['company_id']=2
    assert client.post('/api/v1/mobile/sync',json=op).status_code==409
    op['company_id']=1;op['user_id']+=1
    assert client.post('/api/v1/mobile/sync',json=op).status_code==409
    op=operation(ctx).model_dump(mode='json');op['payload']['inspection_type']='invalid'
    assert client.post('/api/v1/mobile/sync',json=op).status_code==422
    assert db.query(Inspection).count()==0

def test_driver_ownership_and_permission_revocation(ctx):
    db,admin,vehicle,*_=ctx
    user=User(email='driver@alpha.test',full_name='Driver',role='driver',hashed_password='unused')
    db.add(user);db.flush();db.add(CompanyUser(company_id=1,user_id=user.id,role='driver'))
    driver=make_driver(db,1);driver.user_id=user.id;driver.assigned_vehicle_id=vehicle.id;db.commit()
    op=mobile.Operation(key='driver-operation',company_id=1,user_id=user.id,kind='prepare',payload={
        'vehicle_id':vehicle.id,'driver_id':driver.id,'inspection_type':'Daily','inspection_date':'17-09-2026'})
    first=mobile.synchronize(op,REQUEST,db,user)
    assert first['driver_id']==driver.id
    op.payload['driver_id']=999
    with pytest.raises(HTTPException) as exc: mobile.synchronize(op,REQUEST,db,user)
    assert exc.value.status_code==403
    op.payload['driver_id']=driver.id
    membership=db.query(CompanyUser).filter_by(user_id=user.id).one();membership.role='viewer';user.role='viewer';db.commit()
    with pytest.raises(HTTPException) as exc: mobile.synchronize(op,REQUEST,db,user)
    assert exc.value.status_code==403

def test_accident_retries_do_not_duplicate_and_cannot_set_management_fields(ctx):
    db,user,vehicle,*_=ctx;driver=make_driver(db,1)
    op=mobile.Operation(key='accident-operation',company_id=1,user_id=user.id,kind='accident',payload={
        'vehicle_id':vehicle.id,'driver_id':driver.id,'accident_datetime':'2026-09-17T08:30:00Z',
        'location':'Depot','description':'Body damage','severity':'Minor','vehicle_available_after_accident':False,
        'status':'Closed','actual_damage_cost':999})
    first=mobile.synchronize(op,REQUEST,db,user)
    assert mobile.synchronize(op,REQUEST,db,user)==first
    assert db.query(VehicleAccident).count()==1
    row=db.query(VehicleAccident).one();assert row.status=='Reported' and row.actual_damage_cost is None

def test_photo_retry_is_single_attachment(ctx, monkeypatch):
    from types import SimpleNamespace
    import app.api.v1.endpoints.files as files
    db,user,*_=ctx;first=prepare(ctx);calls=[]
    async def fake_store(*args):
        calls.append(1)
        return SimpleNamespace(original_filename='photo.png',stored_filename='unique.png',storage_path='inspection/unique.png',mime_type='image/png',file_size=4)
    monkeypatch.setattr(files,'store_upload',fake_store)
    def photo(): return UploadFile(file=io.BytesIO(b'photo'),filename='photo.png',headers=Headers({'content-type':'image/png'}))
    first_photo=asyncio.run(mobile.photo('photo-operation',1,user.id,'Inspection',first['id'],photo(),db,user))
    replay=asyncio.run(mobile.photo('photo-operation',1,user.id,'Inspection',first['id'],photo(),db,user))
    assert first_photo==replay and len(calls)==1 and db.query(Attachment).count()==1

def test_mobile_migration_fresh_and_populated(tmp_path):
    from sqlalchemy import create_engine,inspect,text
    # Subprocess settings are isolated from other test fixtures and operational databases.
    for populated in [False,True]:
        dbpath=tmp_path/f'migration-{populated}.db'
        env={**os.environ,'DATABASE_URL':f'sqlite:///{dbpath}'}
        if populated:
            subprocess.run([sys.executable,'-m','alembic','upgrade','20260915_0021'],env=env,check=True,capture_output=True)
        subprocess.run([sys.executable,'-m','alembic','upgrade','head'],env=env,check=True,capture_output=True)
        engine=create_engine(f'sqlite:///{dbpath}')
        assert 'MobileOperations' in inspect(engine).get_table_names()
        with engine.connect() as conn:
            assert conn.execute(text('SELECT COUNT(*) FROM "Permissions" WHERE "Code" = :code'),{'code':'accidents.report'}).scalar()==1
        engine.dispose()


def test_other_company_resources_are_not_accessible(ctx):
    db,user,vehicle,*_=ctx
    original=prepare(ctx)
    uid=user.id; payload=completion(ctx,original).payload
    db.expunge_all();set_tenant_context(db,2)
    user=db.query(User).execution_options(skip_tenant_scope=True).filter(User.id==uid).one()
    op=mobile.Operation(key='cross-company-123',company_id=2,user_id=user.id,kind='inspection',inspection_id=original['id'],
        expected_updated_at=original['updated_at'],payload=payload)
    with pytest.raises(HTTPException) as exc: mobile.synchronize(op,REQUEST,db,user)
    assert exc.value.status_code==403
    assert db.query(MobileOperation).count()==0


def test_technician_home_uses_user_link_not_free_text(ctx):
    from app.models import Technician, WorkOrder, WorkOrderTechnician
    db,user,vehicle,*_=ctx
    user.role='mechanic';db.query(CompanyUser).filter_by(user_id=user.id).one().role='mechanic'
    technician=Technician(user_id=user.id,employee_number='TECH-1',full_name='Unrelated display name')
    own=WorkOrder(vehicle_id=vehicle.id,title='Assigned repair',status='In Progress',priority='Critical')
    other=WorkOrder(vehicle_id=vehicle.id,title='Name-only repair',assigned_to=user.full_name,status='Open',priority='Medium')
    db.add_all([technician,own,other]);db.flush()
    db.add(WorkOrderTechnician(work_order_id=own.id,technician_id=technician.id));db.commit()
    result=mobile.home(db,user)
    assert [o['id'] for o in result['orders']]==[own.id]


def test_http_conflict_is_localized(ctx):
    db,user,*_=ctx;record=prepare(ctx);op=completion(ctx,record)
    row=db.get(Inspection,record['id']);row.notes='Server';db.commit()
    app.dependency_overrides[get_db]=lambda: db
    app.dependency_overrides[get_current_user]=lambda: user
    response=TestClient(app).post('/api/v1/mobile/sync',json=op.model_dump(mode='json'),headers={'Accept-Language':'sq'})
    assert response.status_code==409
    assert response.json()['code']=='mobile_conflict'
    assert 'Drafti lokal ruhet' in response.json()['message']


def test_operation_permission_scope_is_checked_even_when_vehicle_view_is_unrestricted(ctx, monkeypatch):
    from app.core.authorization import AuthorizationScope
    original=mobile.authorization_scope
    monkeypatch.setattr(mobile, 'authorization_scope', lambda db,user,permission:
        AuthorizationScope(location_ids={999}) if permission=='inspections.create' else original(db,user,permission))
    with pytest.raises(HTTPException) as exc: prepare(ctx)
    assert exc.value.status_code==403
    assert ctx[0].query(MobileOperation).count()==0
