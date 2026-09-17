"""Disposable PostgreSQL databases; CI supplies TEST_POSTGRES_URL with CREATE DATABASE rights."""
import os
import subprocess
import sys
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import make_url
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.session import Base
from app.models import Company
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
