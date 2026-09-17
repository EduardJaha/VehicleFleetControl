import asyncio
import io
import json
import logging
import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from starlette.datastructures import Headers
from sqlalchemy import create_engine, text
from app.core.config import Settings
from app.core.deployment import validate_deployment
from app.core.observability import JsonFormatter
from app.services import storage
from app.utils import files
from app.main import app


@pytest.mark.parametrize('provider', ['local', 's3'])
def test_storage_upload_download_and_materialization(provider, tmp_path, monkeypatch):
    from moto import mock_aws
    with mock_aws():
        if provider == 'local':
            store = storage.LocalStorageProvider(tmp_path)
        else:
            store = storage.ObjectStorageProvider(Settings(_env_file=None, storage_provider='s3', s3_bucket='fleet-test', s3_access_key='test', s3_secret_key='test'))
            store.client.create_bucket(Bucket='fleet-test')
        monkeypatch.setattr(storage, 'get_storage', lambda: store)
        monkeypatch.setattr(files, 'get_storage', lambda: store)
        upload = UploadFile(filename='invoice.pdf', file=io.BytesIO(b'%PDF-1.4 test'), headers=Headers({'content-type':'application/pdf'}))
        saved = asyncio.run(files.store_upload(upload, 'bills', 'document'))
        store.check()
        with store.open(saved.storage_path) as stream:
            assert stream.read() == b'%PDF-1.4 test'
        with storage.materialize(saved.storage_path) as path:
            assert path.read_bytes() == b'%PDF-1.4 test'
        assert not path.exists()
        response = storage.download_response(saved.storage_path, 'invoice.pdf')
        async def read():
            return b''.join([c async for c in response.body_iterator])
        assert asyncio.run(read()) == b'%PDF-1.4 test'
        assert response.headers['cache-control'] == 'private, no-store'
        with pytest.raises(HTTPException) as exc:
            storage.download_response('missing.pdf', 'missing.pdf')
        assert exc.value.status_code == 404
        with pytest.raises(ValueError):
            store.open('../secret')


def test_storage_rejects_symlink_escape(tmp_path):
    store = storage.LocalStorageProvider(tmp_path / 'storage')
    store.check()
    (tmp_path / 'storage' / 'outside').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        store.put('outside/secret', io.BytesIO(b'no'), 'text/plain')


def test_health_database_schema_storage_and_correlation(tmp_path, monkeypatch):
    import app.main as main
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    engine = create_engine(f'sqlite:///{tmp_path}/health.db')
    monkeypatch.setattr(main, 'engine', engine)
    monkeypatch.setattr(main, 'get_storage', lambda: storage.LocalStorageProvider(tmp_path / 'storage'))
    client = TestClient(app)
    assert client.get('/health/live').json() == {'status':'ok'}
    assert client.get('/health/ready').status_code == 503
    with engine.begin() as db:
        db.execute(text('CREATE TABLE alembic_version (version_num TEXT)'))
        db.execute(text('INSERT INTO alembic_version VALUES (:head)'), {'head':ScriptDirectory.from_config(Config('alembic.ini')).get_current_head()})
    response = client.get('/health/ready', headers={'X-Request-ID':'test-request-123'})
    assert response.status_code == 200
    assert response.headers['x-request-id'] == 'test-request-123'
    assert client.get('/health/live', headers={'X-Request-ID':'bad'}).headers['x-request-id'] != 'bad'
    class FailedStorage:
        def check(self):
            raise RuntimeError('password=NEVER_EXPOSE')
    monkeypatch.setattr(main, 'get_storage', FailedStorage)
    response = client.get('/health/ready')
    assert response.status_code == 503 and 'NEVER_EXPOSE' not in response.text
    engine.dispose()


@pytest.mark.parametrize('environment', ['staging','production'])
def test_deployment_validation(environment):
    values = dict(_env_file=None, environment=environment, JWT_SECRET_KEY='s0me-test-secret-With-32-unique-characters!', cookie_secure=True, CORS_ORIGINS='https://fleet.example', frontend_url='https://fleet.example', database_url='postgresql://user:password@database/fleet', storage_provider='s3', s3_bucket=f'fleet-{environment}', email_backend='smtp', smtp_host='smtp.example')
    settings = Settings(**values)
    assert settings.database_url.startswith('postgresql+psycopg://')
    validate_deployment(settings)
    for bad in ({'database_url':'sqlite:///local.db'}, {'storage_provider':'local'}, {'s3_endpoint':'http://storage:9000'}, {'frontend_url':'http://localhost:3000'}, {'smtp_use_tls':False}):
        with pytest.raises(ValueError):
            validate_deployment(Settings(**{**values, **bad}))
    with pytest.raises(ValueError):
        Settings(**{**values, 'cookie_secure':False})


def test_logs_drop_sensitive_payloads():
    record = logging.LogRecord('fleet', logging.ERROR, '', 1, 'password=secret token=abc', (), None)
    record.request_id = 'request-123'
    payload = json.loads(JsonFormatter().format(record))
    assert 'secret' not in json.dumps(payload) and 'abc' not in json.dumps(payload)
    assert {'timestamp','level','request_id','company_id','user_id','route','duration','status_code'} <= payload.keys()


# Exercise the real authentication/tenant dependencies before S3 is consulted.
from tests.test_auth_security import auth_context, PASSWORD


def test_object_storage_authorization(auth_context, monkeypatch):
    from moto import mock_aws
    from app.models import CompanySettings
    factory, users = auth_context
    with mock_aws():
        provider = storage.ObjectStorageProvider(Settings(_env_file=None, storage_provider='s3', s3_bucket='tenant-files', s3_access_key='test', s3_secret_key='test'))
        provider.client.create_bucket(Bucket='tenant-files')
        provider.put('alpha/logo.png', io.BytesIO(b'private-alpha'), 'image/png')
        monkeypatch.setattr(storage, 'get_storage', lambda: provider)
        with factory() as db:
            db.add(CompanySettings(company_id=1, logo_path='alpha/logo.png'))
            db.add(CompanySettings(company_id=2))
            db.commit()
        with TestClient(app, headers={'Origin':'http://localhost:3000'}) as client:
            assert client.get('/api/v1/admin/company-settings/logo').status_code == 401
            assert client.post('/api/v1/auth/login',json={'email':users['admin'].email,'password':PASSWORD}).status_code == 200
            response=client.get('/api/v1/admin/company-settings/logo')
            assert response.status_code == 200 and response.content == b'private-alpha'
            assert client.post('/api/v1/auth/login',json={'email':users['outsider'].email,'password':PASSWORD}).status_code == 200
            assert client.get('/api/v1/admin/company-settings/logo').status_code == 404
            assert client.post('/api/v1/auth/login',json={'email':users['viewer'].email,'password':PASSWORD}).status_code == 200
            assert client.get('/api/v1/admin/company-settings/logo').status_code == 403


def test_uncaught_errors_are_generic_and_correlated():
    from starlette.applications import Starlette
    from starlette.routing import Route
    from app.core.observability import RequestTelemetryMiddleware
    async def broken(request):
        raise RuntimeError('password=NEVER_EXPOSE')
    application=Starlette(routes=[Route('/broken',broken)])
    application.add_middleware(RequestTelemetryMiddleware)
    response=TestClient(application).get('/broken',headers={'X-Request-ID':'request-error-test'})
    assert response.status_code == 500
    assert response.headers['x-request-id'] == 'request-error-test'
    assert 'NEVER_EXPOSE' not in response.text


def test_release_archive_filters_secrets_and_generated_files():
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('archive',Path(__file__).parents[2]/'scripts/clean-source-archive.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ['.git/config','frontend/node_modules/lib/index.js','frontend/.next/server.js','backend/.venv/bin/python',
                 'backend/__pycache__/main.pyc','backend/data/fleet.sqlite3-wal','backend/uploads/a.pdf',
                 'frontend/test-results/trace.zip','deploy/backend.env','deploy/backend.env.production','.env']:
        assert not module.allowed(name),name
    assert module.allowed('deploy/backend.env.example')
    assert module.allowed('backend/tests/fixtures/historical.sql')
