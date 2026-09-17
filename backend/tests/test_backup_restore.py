"""Real dump/encrypt/restore against disposable PostgreSQL, with mocked S3 transport.

The container suite additionally exercises real MinIO. Local execution requires
age/age-keygen and matching PostgreSQL clients on PATH.
"""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from moto import mock_aws
from sqlalchemy.engine import make_url
from alembic import command
from tests.test_postgresql_deployment import pg_database


@pytest.mark.skipif(not all(shutil.which(name) for name in ('age','age-keygen','pg_dump','pg_restore','createdb')),
                    reason='age and PostgreSQL client programs are required')
def test_encrypted_backup_restore_roundtrip_and_guard(pg_database, tmp_path, monkeypatch):
    engine, config, url = pg_database
    command.upgrade(config, 'head')
    spec = importlib.util.spec_from_file_location('fleet_backup', Path(__file__).parents[2]/'deploy/backup/backup.py')
    backup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backup)
    uri = make_url(url)
    identity = tmp_path/'identity'
    subprocess.run(['age-keygen','-o',str(identity)],check=True,capture_output=True)
    recipient = subprocess.check_output(['age-keygen','-y',str(identity)],text=True).strip()
    values = {'PGHOST':uri.query.get('host',uri.host or 'localhost'),'PGPORT':str(uri.port or 5432),
              'PGUSER':uri.username,'PGPASSWORD':uri.password or '', 'PGDATABASE':uri.database,
              'BACKUP_S3_ENDPOINT':'','BACKUP_S3_BUCKET':'backup-test','BACKUP_S3_ACCESS_KEY':'test',
              'BACKUP_S3_SECRET_KEY':'test','BACKUP_S3_REGION':'us-east-1','BACKUP_PREFIX':'tests/database',
              'BACKUP_RETENTION_DAYS':'7','BACKUP_AGE_RECIPIENT':recipient,'BACKUP_AGE_IDENTITY_FILE':str(identity),
              'RESTORE_DATABASE':'fleet_restore_'+uri.database.removeprefix('fleet_test_')}
    for key,value in values.items():monkeypatch.setenv(key,value)
    monkeypatch.delenv('PGPASSWORD_FILE',raising=False)
    with mock_aws():
        store=backup.client()
        store.create_bucket(Bucket='backup-test')
        key=backup.backup()
        encrypted=store.get_object(Bucket='backup-test',Key=key+'.dump.age')['Body'].read()
        assert encrypted.startswith(b'age-encryption.org/v1')
        assert b'Default Company' not in encrypted
        try:
            backup.restore_test(key)
            with backup.connect(values['RESTORE_DATABASE']) as db:
                assert db.execute('SELECT "Name" FROM "Companies" WHERE "Id"=1').fetchone()[0]=='Default Company'
            with pytest.raises(subprocess.CalledProcessError):
                backup.restore_test(key)  # Existing databases must never be overwritten.
            monkeypatch.setenv('RESTORE_DATABASE',uri.database)
            with pytest.raises(ValueError):backup.restore_test(key)
        finally:
            # Only the test-created restoration database is removed.
            with backup.connect() as db:
                db.autocommit=True
                db.execute('DROP DATABASE IF EXISTS "'+values['RESTORE_DATABASE']+'" WITH (FORCE)')
