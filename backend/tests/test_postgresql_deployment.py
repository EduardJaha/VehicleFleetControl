"""Disposable PostgreSQL databases; CI supplies TEST_POSTGRES_URL with CREATE DATABASE rights."""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import make_url
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.session import Base
from app.models import Company, User, Vehicle, VehicleReservation
from app.core.config import get_settings


@pytest.fixture
def pg_database(monkeypatch):
    url = os.getenv('TEST_POSTGRES_URL')
    if not url:
        pytest.skip('TEST_POSTGRES_URL is not configured')
    url = make_url(url.replace('postgresql://','postgresql+psycopg://'))
    admin = create_engine(url, isolation_level='AUTOCOMMIT')
    name = 'fleet_test_' + uuid4().hex
    with admin.connect() as db:
        db.execute(text(f'CREATE DATABASE "{name}"'))
    target = url.set(database=name).render_as_string(hide_password=False)
    monkeypatch.setenv('DATABASE_URL', target)
    get_settings.cache_clear()
    engine = create_engine(target)
    config = Config('alembic.ini')
    try:
        yield engine, config, target
    finally:
        get_settings.cache_clear()
        engine.dispose()
        with admin.connect() as db:
            db.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def test_postgresql_every_revision_and_persistence(pg_database):
    engine, config, url = pg_database
    revisions = list(reversed(list(ScriptDirectory.from_config(config).walk_revisions())))
    for revision in revisions:
        command.upgrade(config, revision.revision)
    with engine.begin() as db:
        result = db.execute(Company.__table__.insert().values(Name='Persistence check',Slug='persistence'))
        company_id = result.inserted_primary_key[0]
        assert company_id > 1
    engine.dispose()
    subprocess.run([sys.executable,'-m','app.scripts.migrate'],check=True,env={**os.environ,'DATABASE_URL':url,'ENVIRONMENT':'test'})
    with engine.connect() as db:
        assert db.execute(text('SELECT "Name" FROM "Companies" WHERE "Id"=:id'),{'id':company_id}).scalar_one() == 'Persistence check'
        assert db.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == revisions[-1].revision
    assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())


def test_postgresql_populated_upgrade(pg_database):
    engine, config, _ = pg_database
    command.upgrade(config,'head')
    command.downgrade(config,'20260913_0017')
    with engine.begin() as db:
        db.execute(Company.__table__.insert().values(Name='Existing tenant',Slug='existing-tenant'))
    command.upgrade(config,'head')
    with engine.connect() as db:
        assert db.execute(text('SELECT COUNT(*) FROM "Companies" WHERE "Slug"=\'existing-tenant\'')).scalar_one() == 1
    assert {'ServicePrograms','InspectionTemplates','LoginRateLimits'} <= set(inspect(engine).get_table_names())


def test_postgresql_real_onboarding_cookie_and_object_storage(pg_database, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from moto import mock_aws
    from app.main import app
    from app.db.session import get_db, TenantSession
    from app.services import storage
    from app.utils import files
    from app.core.config import Settings
    engine, config, _ = pg_database
    command.upgrade(config,'head')
    factory=sessionmaker(bind=engine,class_=TenantSession)
    def database():
        with factory() as db: yield db
    app.dependency_overrides[get_db]=database
    try:
        with mock_aws():
            store=storage.ObjectStorageProvider(Settings(_env_file=None,storage_provider='s3',s3_bucket='pg-files',s3_access_key='test',s3_secret_key='test'))
            store.client.create_bucket(Bucket='pg-files')
            monkeypatch.setattr(storage,'get_storage',lambda:store)
            monkeypatch.setattr(files,'get_storage',lambda:store)
            with TestClient(app,headers={'Origin':'http://localhost:3000'}) as client:
                r=client.post('/api/v1/auth/register',json={'company_name':'Postgres company','full_name':'Admin','email':'pg@example.test','password':'long test password for pg'})
                assert r.status_code == 201, r.text
                assert client.get('/api/v1/auth/me').status_code == 200
                r=client.post('/api/v1/admin/company-settings/logo',files={'file':('logo.png',b'\x89PNG\r\n\x1a\nfixture','image/png')})
                assert r.status_code == 200,r.text
                assert client.get('/api/v1/admin/company-settings/logo').content == b'\x89PNG\r\n\x1a\nfixture'
    finally:
        app.dependency_overrides.clear()


def test_postgresql_limited_application_role_can_migrate(pg_database, tmp_path, monkeypatch):
    import shutil
    if not shutil.which('psql'):
        pytest.skip('PostgreSQL psql client is required')
    engine, config, url = pg_database
    uri=make_url(url)
    role='fleet_role_'+uuid4().hex
    password=tmp_path/'app-password'
    password.write_text('isolated application password')
    password.chmod(0o600)
    from pathlib import Path
    script=Path(__file__).parents[2]/'deploy/postgres/init-app.sh'
    env={**os.environ,'PGHOST':uri.query.get('host',uri.host or 'localhost'),'PGPORT':str(uri.port or 5432),
         'PGPASSWORD':uri.password or '', 'POSTGRES_USER':uri.username,'POSTGRES_DB':uri.database,
         'POSTGRES_APP_USER':role,'POSTGRES_APP_PASSWORD_FILE':str(password)}
    subprocess.run(['bash',str(script)],check=True,env=env,capture_output=True)
    try:
        monkeypatch.setenv('DATABASE_URL',uri.set(username=role,password=password.read_text()).render_as_string(hide_password=False))
        get_settings.cache_clear()
        command.upgrade(config,'head')
        with engine.connect() as db:
            assert db.execute(text('SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=:role'),{'role':role}).one() == (False,False,False)
            assert db.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == ScriptDirectory.from_config(config).get_current_head()
    finally:
        quote=engine.dialect.identifier_preparer.quote
        with engine.begin() as db:
            db.execute(text(f'REASSIGN OWNED BY {quote(role)} TO {quote(uri.username)}'))
            db.execute(text(f'DROP OWNED BY {quote(role)}'))
            db.execute(text(f'DROP ROLE {quote(role)}'))


@pytest.mark.parametrize('race', ('create_create', 'create_approve', 'approve_approve'))
def test_postgresql_concurrent_reservation_activation(pg_database, monkeypatch, race):
    """Independent HTTP requests must serialize activation on the vehicle row."""
    from datetime import datetime
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app.api.v1.endpoints import reservations
    from app.core.security import get_current_user
    from app.db.session import get_db, TenantSession, set_tenant_context
    from app.main import app

    engine, config, _ = pg_database
    command.upgrade(config, 'head')
    factory = sessionmaker(bind=engine, class_=TenantSession)
    with factory() as db:
        manager = User(company_id=1, email=f'{race}@example.test', full_name='Race manager',
                       hashed_password='unused', role='fleet_manager', is_active=True)
        vehicle = Vehicle(company_id=1, brand='Toyota', model='Corolla', fuel_type='Petrol',
                          vehicle_location='Depot', license_plate='01-111-AA',
                          registration_country='XK', license_plate_normalized='01111AA')
        db.add_all([manager, vehicle])
        db.flush()
        manager_id, vehicle_id = manager.id, vehicle.id
        rejected_ids = []
        for _ in range(2 if race == 'approve_approve' else 1 if race == 'create_approve' else 0):
            row = VehicleReservation(company_id=1, vehicle_id=vehicle_id,
                                     reserved_by='Driver', reservation_type='Business',
                                     start_date=datetime(2030, 1, 10), end_date=datetime(2030, 1, 12),
                                     status=2)
            db.add(row)
            db.flush()
            rejected_ids.append(row.id)
        db.commit()

    def database():
        with factory() as db:
            set_tenant_context(db, 1)
            db.info['user_id'] = manager_id
            yield db

    def current_user(db=Depends(get_db)):
        return db.get(User, manager_id)

    barrier = Barrier(2)
    original = reservations.ensure_no_reservation_overlap

    def synchronized_check(*args, **kwargs):
        barrier.wait(timeout=15)
        return original(*args, **kwargs)

    monkeypatch.setattr(reservations, 'ensure_no_reservation_overlap', synchronized_check)
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = current_user
    create = ('POST', '/api/v1/reservations', {
        'license_plate': '01-111-AA', 'reserved_by': 'Driver',
        'reservation_type': 'Business', 'start_date': '10-01-2030', 'end_date': '12-01-2030',
    })
    def approve_request(reservation_id):
        return ('PUT', f'/api/v1/reservations/{reservation_id}/approve', None)

    if race == 'create_create':
        requests = (create, create)
    elif race == 'create_approve':
        requests = (create, approve_request(rejected_ids[0]))
    else:
        requests = tuple(approve_request(row_id) for row_id in rejected_ids)
    try:
        with TestClient(app, headers={'Origin': 'http://localhost:3000'}) as client:
            def send(item):
                method, path, body = item
                return client.request(method, path, json=body).status_code

            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(send, requests))
        assert sorted(responses) == [200, 409]
        with factory() as db:
            active = db.query(VehicleReservation).filter(
                VehicleReservation.vehicle_id == vehicle_id,
                VehicleReservation.archived.is_(False),
                VehicleReservation.status.in_((0, 1)),
            ).all()
            assert len(active) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize('entity_type', ('VehicleAccident', 'VehicleConditionRecord'))
def test_postgresql_attachment_archive_authorization_over_http(pg_database, entity_type):
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session
    from app.core.security import get_current_user
    from app.db.session import get_db
    from app.main import app
    from app.models import Attachment
    from tests.test_file_archive_authorization import setup_record

    engine, config, _ = pg_database
    command.upgrade(config, 'head')
    with Session(engine) as db:
        users, parent, attachment = setup_record(db, entity_type)
        user_ids = {name: user.id for name, user in users.items()}
        parent_id, attachment_id = parent.id, attachment.id

    actor = {'id': user_ids['scoped']}

    def database():
        with Session(engine) as db:
            yield db

    def current_user(db=Depends(get_db)):
        return db.get(User, actor['id'])

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = current_user
    url = f'/api/v1/files/{attachment_id}'
    try:
        with TestClient(app, headers={'Origin': 'http://localhost:3000'}) as client:
            assert client.delete(url).status_code == 403
            assert client.get(f'/api/v1/files?entity_type={entity_type}&entity_id={parent_id}').status_code == 403
            assert client.get(f'{url}/download').status_code == 403
            actor['id'] = user_ids['viewer']
            assert client.delete(url).status_code == 403
            actor['id'] = user_ids['outsider']
            assert client.delete(url).status_code == 404
            with Session(engine) as db:
                assert not db.get(Attachment, attachment_id).archived
            actor['id'] = user_ids['manager']
            with Session(engine) as db:
                if entity_type == 'VehicleAccident':
                    db.get(type(parent), parent_id).archived = True
                else:
                    record = db.get(type(parent), parent_id)
                    record.vehicle_assignment.archived = True
                db.commit()
            assert client.delete(url).status_code == 404
            with Session(engine) as db:
                if entity_type == 'VehicleAccident':
                    db.get(type(parent), parent_id).archived = False
                else:
                    db.get(type(parent), parent_id).vehicle_assignment.archived = False
                db.commit()
            assert client.delete(url).status_code == 200
        with Session(engine) as db:
            row = db.get(Attachment, attachment_id)
            assert row.archived and row.archived_by == user_ids['manager']
    finally:
        app.dependency_overrides.clear()


def test_postgresql_accident_terminal_transitions_over_http(pg_database):
    from datetime import datetime
    from decimal import Decimal
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session
    from app.core.security import get_current_user
    from app.db.session import get_db
    from app.main import app
    from app.models import AccidentClaim, VehicleAccident, WorkOrder

    engine, config, _ = pg_database
    command.upgrade(config, 'head')
    with Session(engine) as db:
        manager = User(company_id=1, email='accident-http@example.test', full_name='Manager',
                       hashed_password='unused', role='fleet_manager', is_active=True)
        vehicle = Vehicle(company_id=1, brand='Toyota', model='Corolla', fuel_type='Petrol',
                          vehicle_location='Depot', license_plate='01-111-AA',
                          registration_country='XK', license_plate_normalized='01111AA')
        db.add_all([manager, vehicle])
        db.flush()
        accident = VehicleAccident(company_id=1, vehicle_id=vehicle.id, accident_date=datetime.utcnow(),
                                   location='Depot', severity='Minor', status='Repair In Progress')
        db.add(accident)
        db.flush()
        order = WorkOrder(company_id=1, vehicle_id=vehicle.id, accident_id=accident.id,
                          title='Repair', status='Open', total_cost=Decimal('125.00'))
        claim = AccidentClaim(company_id=1, accident_id=accident.id,
                              insurance_company='Test insurer', policy_number='P-1', claim_number='C-1',
                              claim_status='Open', claim_opened_date=datetime.utcnow())
        rejected = VehicleAccident(company_id=1, vehicle_id=vehicle.id, accident_date=datetime.utcnow(),
                                   location='Depot', severity='Minor', status='Rejected')
        db.add_all([order, claim, rejected])
        db.flush()
        rejected_claim = AccidentClaim(company_id=1, accident_id=rejected.id,
                                       insurance_company='Test insurer', policy_number='P-2',
                                       claim_number='C-2', claim_status='Open',
                                       claim_opened_date=datetime.utcnow())
        db.add(rejected_claim)
        db.commit()
        manager_id, accident_id, order_id, claim_id = manager.id, accident.id, order.id, claim.id
        rejected_id, rejected_claim_id = rejected.id, rejected_claim.id

    def database():
        with Session(engine) as db:
            yield db

    def current_user(db=Depends(get_db)):
        return db.get(User, manager_id)

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = current_user
    base = f'/api/v1/accidents/id/{accident_id}'
    try:
        with TestClient(app, headers={'Origin': 'http://localhost:3000'}) as client:
            assert client.post(f'{base}/transition/Resolved').status_code == 409
            assert client.post(f'{base}/actions/resolve').status_code == 409
            with Session(engine) as db:
                db.get(WorkOrder, order_id).status = 'Completed'
                db.commit()
            assert client.post(f'{base}/transition/Resolved').status_code == 409
            with Session(engine) as db:
                db.get(AccidentClaim, claim_id).claim_status = 'Closed'
                db.commit()
            assert client.post(f'{base}/transition/Resolved').status_code == 200
            assert client.post(f'{base}/actions/close').status_code == 200
            assert client.post(f'{base}/transition/Closed').status_code == 409
            rejected_url = f'/api/v1/accidents/id/{rejected_id}/transition/Closed'
            assert client.post(rejected_url).status_code == 409
            with Session(engine) as db:
                db.get(AccidentClaim, rejected_claim_id).claim_status = 'Rejected'
                db.commit()
            assert client.post(rejected_url).status_code == 200
        with Session(engine) as db:
            row = db.get(VehicleAccident, accident_id)
            assert row.status == 'Closed' and row.resolved_at and row.closed_at
            assert row.actual_damage_cost == Decimal('125.00')
            assert db.get(VehicleAccident, rejected_id).status == 'Closed'
    finally:
        app.dependency_overrides.clear()
