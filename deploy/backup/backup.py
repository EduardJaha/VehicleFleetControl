"""Daily age-encrypted PostgreSQL snapshots and a guarded restore drill.

Credentials are read from the environment/file, never passed in command arguments.
Backup bucket credentials are deliberately separate from application storage.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import re

import boto3
from botocore.config import Config
import psycopg

TABLES = ('Companies', 'Users', 'Vehicles', 'Drivers', 'Attachments', 'ImportJobs', 'DocumentVersions')


def client():
    return boto3.client('s3', endpoint_url=os.getenv('BACKUP_S3_ENDPOINT') or None,
                        aws_access_key_id=os.environ['BACKUP_S3_ACCESS_KEY'],
                        aws_secret_access_key=os.environ['BACKUP_S3_SECRET_KEY'],
                        region_name=os.getenv('BACKUP_S3_REGION', 'us-east-1'),
                        config=Config(connect_timeout=5, read_timeout=60, retries={'max_attempts': 3}))


def pg_env():
    env = dict(os.environ)
    env.setdefault("PGCONNECT_TIMEOUT", "5")
    if env.get('PGPASSWORD_FILE'):
        env['PGPASSWORD'] = Path(env['PGPASSWORD_FILE']).read_text().strip()
    return env


def connect(database=None):
    env = pg_env()
    return psycopg.connect(host=env['PGHOST'], port=env.get('PGPORT', '5432'),
                          user=env['PGUSER'], password=env.get('PGPASSWORD'),
                          dbname=database or env['PGDATABASE'], connect_timeout=5)


def run(args, **kwargs):
    # Do not echo subprocess stderr: SQL errors can include business data.
    return subprocess.run(args, env=pg_env(), check=True, stderr=subprocess.PIPE, **kwargs)


def snapshot_metadata(connection):
    counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in TABLES}
    versions = [r[0] for r in connection.execute('SELECT version_num FROM alembic_version')]
    return {'counts': counts, 'alembic': versions}


def encrypt_file(source, destination):
    run(['age', '-r', os.environ['BACKUP_AGE_RECIPIENT'], '-o', str(destination), str(source)])


def backup():
    bucket = os.environ['BACKUP_S3_BUCKET']
    prefix = os.environ['BACKUP_PREFIX'].strip('/') + '/'
    if prefix == '/' or int(os.environ.get('BACKUP_RETENTION_DAYS', '30')) < 7:
        raise ValueError('A dedicated backup prefix and retention of at least seven days are required')
    key = prefix + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    store = client()
    with tempfile.TemporaryDirectory(prefix='fleet-backup-') as folder:
        folder = Path(folder)
        encrypted = folder / 'database.dump.age'
        # Dump and verification counts share one PostgreSQL snapshot.
        with connect() as connection:
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            snapshot = connection.execute('SELECT pg_export_snapshot()').fetchone()[0]
            metadata = snapshot_metadata(connection)
            # Plain database contents flow through a pipe, never onto persistent disk.
            with tempfile.TemporaryFile() as errors:
                dump = subprocess.Popen(['pg_dump', '--format=custom', '--no-owner', '--no-acl', '--snapshot', snapshot],
                                        stdout=subprocess.PIPE, stderr=errors, env=pg_env())
                try:
                    run(['age', '-r', os.environ['BACKUP_AGE_RECIPIENT'], '-o', str(encrypted)], stdin=dump.stdout)
                finally:
                    dump.stdout.close()
                    code = dump.wait()
                if code:
                    raise RuntimeError('pg_dump failed')
        with encrypted.open('rb') as stream:
            metadata['sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        manifest = folder / 'manifest.json'
        manifest.write_text(json.dumps(metadata))
        encrypt_file(manifest, folder / 'manifest.age')
        store.upload_file(str(encrypted), bucket, key + '.dump.age')
        # The manifest marks a complete backup; restore ignores incomplete uploads.
        store.upload_file(str(folder / 'manifest.age'), bucket, key + '.manifest.age')
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(os.getenv('BACKUP_RETENTION_DAYS', '30')))
    for page in store.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            if obj['LastModified'] < cutoff and obj['Key'].endswith(('.dump.age', '.manifest.age')):
                store.delete_object(Bucket=bucket, Key=obj['Key'])
    print(json.dumps({'event': 'backup_complete', 'key': key}), flush=True)
    return key


def restore_test(key):
    target = os.environ['RESTORE_DATABASE']
    if not re.fullmatch(r'fleet_restore_[a-z0-9_]+', target) or target == os.environ['PGDATABASE']:
        raise ValueError('RESTORE_DATABASE must be a distinct fleet_restore_* database')
    if not key.startswith(os.environ['BACKUP_PREFIX'].strip('/') + '/') or '..' in key:
        raise ValueError('Backup key must be inside BACKUP_PREFIX')
    store = client()
    with tempfile.TemporaryDirectory(prefix='fleet-restore-') as folder:
        folder = Path(folder)
        for suffix in ('dump', 'manifest'):
            encrypted = folder / (suffix + '.age')
            store.download_file(os.environ['BACKUP_S3_BUCKET'], key + '.' + suffix + '.age', str(encrypted))
            run(['age', '-d', '-i', os.environ['BACKUP_AGE_IDENTITY_FILE'], '-o', str(folder / suffix), str(encrypted)])
        metadata = json.loads((folder / 'manifest').read_text())
        with (folder / 'dump.age').open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != metadata['sha256']:
                raise RuntimeError('Backup checksum mismatch')
        # createdb fails if target exists; there is deliberately no overwrite or drop option.
        run(['createdb', target])
        run(['pg_restore', '--exit-on-error', '--single-transaction', '--no-owner', '--no-acl', '--dbname', target, str(folder / 'dump')])
        with connect(target) as connection:
            actual = snapshot_metadata(connection)
        if actual != {k: metadata[k] for k in ('counts', 'alembic')}:
            raise RuntimeError('Restore validation failed')
    print(json.dumps({'event': 'restore_verified', 'database': target, 'backup': key}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['once', 'schedule', 'restore-test'])
    parser.add_argument('--key')
    args = parser.parse_args()
    if args.action == 'restore-test':
        if not args.key:
            parser.error('--key is required')
        restore_test(args.key)
    elif args.action == 'once':
        backup()
    else:
        while True:
            now = datetime.now(timezone.utc)
            due = now.replace(hour=2, minute=0, second=0, microsecond=0)
            if due <= now:
                due += timedelta(days=1)
            time.sleep((due - now).total_seconds())
            backup()  # Failure exits nonzero for supervisor/monitoring to detect.


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'event': 'backup_or_restore_failed', 'error_type': type(exc).__name__}), flush=True)
        raise SystemExit(1)
