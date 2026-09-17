# Deployment and operations

PostgreSQL 17 is the recommended production database. `docker-compose.yml` remains a bind-mounted SQLite development environment. `docker-compose.prod.yml` is a **separate** deployment file, not a development override. It runs built, non-root application images, PostgreSQL on a named volume, a single scheduler, Caddy with automatic HTTPS, and a daily backup worker. Only Caddy publishes ports. Object storage is an external private AWS S3 bucket or a durable MinIO installation with HTTPS; it is not an ephemeral application container.

## Environment boundaries

| Resource | Development | Staging | Production |
|---|---|---|---|
| Database | SQLite or disposable PostgreSQL | Dedicated PostgreSQL database/credentials | Dedicated PostgreSQL database/credentials |
| App settings | `ENVIRONMENT=development` | `ENVIRONMENT=staging` | `ENVIRONMENT=production` |
| Attachments | Local uploads or test MinIO | Separate private staging bucket | Separate private production bucket |
| Domain | localhost | staging.example.com | fleet.example.com |
| JWT, SMTP, S3, monitoring secrets | Local only | Independent credentials | Independent credentials |
| Email | Console/mock | Mock or sandbox SMTP | TLS SMTP |
| Backups | Optional | Dedicated staging prefix/bucket | Dedicated encrypted backup bucket |

For staging, copy the templates into `/etc/vehiclefleetcontrol/staging/`, set `ENVIRONMENT=staging`, use `fleet_staging` and separate database passwords, set `EMAIL_BACKEND=mock`, select a staging-only bucket and JWT key, and update all env-file paths, project name and domain. Use separate hosts/accounts when practical. Both staging and production fail startup validation for insecure cookies, debug mode, unsafe JWT secrets, non-HTTPS browser origins, SQLite, local storage, non-HTTPS custom S3 endpoints, or a frontend URL outside the trusted origins. Production also requires SMTP. `DATABASE_URL` accepts `sqlite:///...`, `postgresql://...`, `postgres://...`, or `postgresql+psycopg://...`; PostgreSQL URLs normalize to psycopg 3. URL-encode database passwords. On an external PostgreSQL service use its required TLS settings (usually `?sslmode=verify-full&sslrootcert=...`). The bundled database stays on the private Docker network; protect and encrypt the host volume. Its first-volume initialization creates a separate application role with no superuser, role-creation or database-creation privileges. The application owns only its database objects; migrations use that same owner. The backup worker receives only the application password. Restores use a separate recovery-cluster administrator through the recovery env file. Changing these initialization variables does not rotate credentials on existing volumes; use an explicit PostgreSQL role/password rotation and update all consumers.

## First installation

1. Install Docker Engine and Compose v2 on a secured host. Point your domain's DNS to that host; permit 80/443 for HTTPS issuance. Provision private S3 buckets with encryption, versioning, and public-access blocking. Give the app only bucket metadata/list and object read/write permissions on its attachment bucket; no public ACLs or delete rights are needed. Use a separate backup identity/bucket. MinIO needs persistent replicated disks, a trusted TLS endpoint, and its own recovery plan.
2. Copy `deploy/production.env.example`, `deploy/backend.env.example`, and `deploy/backup.env.example` into `/etc/vehiclefleetcontrol/production/` as `compose.env`, `backend.env`, and `backup.env`. Restrict them to the deployment account (0600). Create independent `postgres-password` (cluster administrator) and `app-database-password` secret files and set their permissions to allow the PostgreSQL container to read the Compose secret. Replace every placeholder. Generate JWT entropy with `openssl rand -hex 48`. Never commit these files. Runtime env files are visible to Docker administrators; use your orchestrator's secret store if that trust model is insufficient.
3. Set immutable image tags from a successful release workflow (or build reviewed images with `docker build -t ... backend` and `docker build -t ... frontend`). The frontend image builds with `/api/v1`; the same artifact works on either domain through Caddy. Public Next.js build variables are not runtime secrets.
4. Define a shell helper from the release root:

   ```sh
   fleet() { docker compose --env-file /etc/vehiclefleetcontrol/production/compose.env -p fleet-production -f docker-compose.prod.yml "$@"; }
   fleet config --quiet
   fleet pull backend frontend scheduler migrate backup
   fleet up -d --wait database
   fleet run --rm --no-deps backend python -m app.core.deployment
   fleet run --rm --no-deps migrate
   fleet up -d --wait --wait-timeout 240
   ```

   An empty database cannot be backed up using the application's verification manifest yet, so this first-install sequence migrates before the first backup. Run `fleet run --rm backup once` after initialization and perform the restore drill below before accepting real data.
5. Check `https://fleet.example.com/health/live` and `/health/ready`, register the first company, upload/download a logo or attachment, and verify denial from another company. Readiness checks database connectivity, the release's Alembic head, and bucket access. It returns only `ready` or `not_ready`, without credentials or dependency exception details. `/health` remains a liveness alias.

The example subnet is `172.30.10.0/24`. Set `APP_SUBNET` to a non-overlapping subnet when necessary; staging on the same host must use a different subnet (for example `172.30.11.0/24`), different volumes/project name, and a separately configured host-level ingress because both stacks cannot bind the same 80/443 ports. Do not publish backend/database ports. Gunicorn trusts forwarded client addresses only from the configured app subnet. Caddy supplies them; do not add an untrusted forwarding proxy without configuring its trust boundary.

## Release and rollback

GitHub Actions installs pinned dependencies, compiles Python, tests SQLite and disposable PostgreSQL databases, checks translations/lint/types, builds Next.js, runs Chromium workflows, builds production containers, restarts PostgreSQL/MinIO to check persistence, validates Caddy, and executes encrypted backup/restore. Any failure blocks image publication and deployment. The tested backend/frontend/backup images are exported from the container job and published without rebuilding; automated deployment pins the resulting registry digests. Tag `v*` publishes commit-SHA image tags; workflow dispatch with `deploy=true` deploys the same verified revision. Configure GitHub `staging`/`production` environments and branch restrictions; protect production with required reviewers. Set environment secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_KEY`, and pinned `DEPLOY_KNOWN_HOSTS`. The host must already have its env files, registry read credentials, initial schema, and writable `/opt/vehiclefleetcontrol/<environment>/releases`.

`deploy/remote-deploy.sh` validates settings, pulls the tested images, stops ingress and writers, takes an encrypted backup, runs the serialized migration job, and starts healthy services. This is a maintenance-window deployment, not zero downtime. A failed backup or migration stops the rollout and leaves writers stopped for investigation. The initial installation must use the first-install steps above. Automated releases save non-secret image digests in `images.env` within the release directory. For later operator commands, include it after the main Compose environment file (`--env-file /etc/vehiclefleetcontrol/production/compose.env --env-file /opt/vehiclefleetcontrol/production/current/images.env`) and use the current release's Compose file. This preserves the deployed digests instead of reverting to older template tags. Do not blindly restart old application code after a schema change. Prefer a forward fix; restore into a new database and repoint `DATABASE_URL` if recovery is necessary. Several historical migrations deliberately prohibit downgrade.

Migrations run once as a deployment job, never in every web worker. A PostgreSQL advisory lock serializes concurrent migration runners. Existing migration IDs and the legacy bridge remain intact. Portability repairs use Boolean literals, deterministic PostgreSQL constraint-name truncation, and sequence advancement after inserting the legacy default company. A fresh bootstrap still uses current metadata; tests also exercise the reversible program/inspection/notification suffix against populated PostgreSQL. These tests do not replace a rehearsal with a sanitized copy of your actual pre-release database.

Python dependencies, including transitive runtime packages, are exact-pinned in `backend/requirements.txt`; test tools are pinned separately in `requirements-dev.txt`. `requirements.in` lists roots for deliberate lock refreshes. Validate updates on Python 3.12/Linux and with `pip check`; do not casually replace a lock with `pip freeze` from a workstation. Build base images are version-family tags to receive security updates; publish and deploy application images by immutable release tags/digests, and rebuild after base-image updates.

## Private files and imports

`LocalStorageProvider` and `ObjectStorageProvider` share validated relative keys. New uploads are validated/scanned in private temporary files, then written to storage. S3 streaming downloads go through the same authenticated API, after company, permission and record checks; no public bucket URLs or presigned URLs bypass those checks. Company logos and retained CSV/XLSX import sources use the provider too. Import parsing uses temporary seekable copies removed on exit; import progress sidecars are atomic local writes or S3 object writes so different workers can read progress.

`STORAGE_PROVIDER=local` is for development/tests; `s3` uses `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`, and optional `S3_ADDRESSING_STYLE=path` for MinIO. Omit both credentials to use AWS workload IAM. Preserve encryption/versioning settings at the bucket policy. Readiness's `HeadBucket` is a connectivity check, not proof of write permission: the staging upload/download smoke test verifies writes.

Before switching an existing installation: stop all writers, back up the database and entire upload tree, copy every file to the bucket with its relative path unchanged (including `imports/`), compare source/object counts and checksums, and test authenticated attachment/legacy/logo/import reads. Then change the provider and restart all workers together. Keep the original files until recovery has been tested. There is no automatic fallback between stores and no automatic SQLite-to-PostgreSQL data conversion; migrate existing SQLite records through a separately reviewed, rehearsed ETL preserving IDs, tenant links, numeric precision and PostgreSQL sequences. `alembic upgrade` creates/upgrades schemas; it does not copy databases.

Normal archive actions retain object data. Transaction failures can still leave orphan objects; retain them until an explicit reconciliation/retention job verifies references. Antivirus remains the existing no-op extension point. S3 support does not introduce a malware scanner.

## Backups and restored evidence

`backup` runs daily at **02:00 UTC**, using `pg_dump --format=custom` with an exported repeatable-read snapshot. Manifest row counts and Alembic revision come from that same snapshot. The dump streams directly through `age` encryption before S3 upload; the manifest is encrypted too. Default retention is 30 days (minimum 7). Cleanup only deletes old backup objects beneath `BACKUP_PREFIX`; versioned buckets also need a matching noncurrent-version lifecycle policy. A completed encrypted manifest marks a complete backup. Alert on missing success events for 26 hours or any `backup_or_restore_failed` event. A failed scheduled backup exits nonzero; Docker restarts it and an operator should run an immediate retry after fixing the failure.

Generate an age identity on a separate recovery machine (`age-keygen -o recovery-identity`). Put **only its public recipient** in `BACKUP_AGE_RECIPIENT`. Store the identity in an independent encrypted secrets vault and test access by the on-call team. The backup worker has no private decryption key. Enable server-side encryption, versioning and an off-account copy for the backup bucket. Host snapshots alone are insufficient. Attachments need bucket versioning/replication and a restore point consistent with the database; database dumps contain file references, not file contents. For point-in-time recovery below a 24-hour RPO, use a managed PostgreSQL backup/WAL archive service in addition to these daily dumps.

Restore drill, from the release directory on a **recovery/staging host** with network access to a disposable PostgreSQL cluster and the backup bucket:

```sh
# Recovery env supplies PGHOST/PGUSER/PGDATABASE for that isolated cluster and read access to the backup bucket.
# The new database must not exist and must be named fleet_restore_*.
docker build -f deploy/backup/Dockerfile -t fleet-backup:recovery .
docker run --rm --read-only --tmpfs /tmp:mode=1777,size=2147483648 \
  --env-file /secure/recovery.env \
  -e RESTORE_DATABASE=fleet_restore_20260916 \
  -e BACKUP_AGE_IDENTITY_FILE=/run/recovery/identity \
  -v /secure/recovery-identity:/run/recovery/identity:ro \
  fleet-backup:recovery restore-test --key production/postgresql/COMPLETE_BACKUP_TIMESTAMP
```

The recovery database hostname must be reachable from that container; add the recovery Docker network if required. Make the mounted identity readable by the container's `postgres` user without granting other host users access. Restore never overwrites an existing database. It verifies the encrypted dump checksum, uses `pg_restore --exit-on-error --single-transaction`, and compares company/user/vehicle/driver/attachment/import/document-version counts and migration revision. Keep the restored database until application checks finish; explicitly delete only that disposable database afterward.

Point a staging app at the restored database and a recovered copy of the attachment bucket. Disable real email (`EMAIL_BACKEND=mock`), use a new JWT key, verify login/company isolation, open several historical attachments, and inspect maintenance/fuel totals. Record backup key, timestamp, counts, success/failure, operator and elapsed restoration time in the operations log. Perform monthly and before major upgrades. CI executes a real encrypted dump/upload/download/decrypt/restore with disposable PostgreSQL and MinIO on every passing release candidate; that validates the scripts but does not prove access to your production backup, recovery key, or bucket replication.

## Observability and capacity

In staging and production, the backend/scheduler emit allowlisted JSON to stdout with `timestamp`, `level`, `request_id`, `company_id`, `user_id`, route **template**, `duration` in milliseconds, and `status_code`. Identity fields are set only after successful authentication. Query strings, headers, bodies, tokens, passwords and arbitrary exception values are excluded. Incoming correlation IDs must match a bounded safe format; invalid values are replaced. Responses include `X-Request-ID`, including generated 500 responses. Non-request events have null request fields. Known Uvicorn lifecycle events include a safe readable message. Development and test environments use concise console output with the same privacy rules and request correlation IDs. Aggregate logs centrally and alert on 5xx rate, latency, readiness failures, backup age, disk usage, scheduler failures and SMTP delivery backlog. Avoid enabling verbose SDK/SQL access logging that includes payloads.

Optional `ERROR_MONITORING_PROVIDER=sentry` and `SENTRY_DSN` send sanitized exception type/correlation events with default integrations and PII disabled. The `ErrorMonitor` interface permits another provider. This intentionally excludes exception values and request payloads; use correlation IDs to join events to access logs. Caddy has no request access log enabled, avoiding unfiltered URL queries.

Caddy limits request bodies to 12 MB, providing multipart overhead above the application's 10 MiB document/import limit (images retain their existing validation limits). Header timeout is 10s; body/write/upstream response timeouts are 180s. Gunicorn uses two Uvicorn workers by default, no reload, and 180s shutdown/request timeout. Size workers against CPU, memory and database pool limits; imports remain synchronous and may exceed proxy timeouts for large workloads, so test representative imports and use job polling/recovery procedures rather than increasing timeouts indiscriminately. Run exactly one scheduler replica. Container tmpfs space must accommodate concurrent validated files/import copies; the backup worker's 2 GiB default temp space must be increased for larger encrypted backups and restore drills.

## Clean source releases and local verification

Commit the intended source changes, then run:

```sh
python3 scripts/clean-source-archive.py --ref HEAD --output /tmp/vehiclefleetcontrol-source.tar.gz
```

This archives a specific commit, excludes untracked files, then independently filters `.git`, dependencies, Next output, virtual environments, Python caches, SQLite files, uploads, Playwright output and real environment files even if accidentally tracked. It never archives the working tree's uncommitted edits. Example env templates remain included. Docker contexts apply corresponding exclusions. Inspect the tar listing before distribution; do not use a recursive folder zip.

Local checks:

```sh
cd backend
python -m pip install -r requirements-dev.txt
python -m compileall -q app alembic
pytest -q
# Optional isolated PostgreSQL admin connection; tests create/drop only random fleet_test_* databases.
TEST_POSTGRES_URL=postgresql+psycopg://test:password@localhost/fleet_test pytest -q tests/test_postgresql_deployment.py
cd ../frontend
npm ci
npm run i18n:check
npm run lint
npm run build
npx playwright install chromium
npm run test:e2e
cd ..
docker compose -p fleet-ci -f deploy/compose.test.yml up --build --wait backend frontend proxy
python3 scripts/container-smoke.py
docker compose -p fleet-ci -f deploy/compose.test.yml restart database storage backend frontend proxy
docker compose -p fleet-ci -f deploy/compose.test.yml up --wait backend frontend proxy
python3 scripts/container-smoke.py --verify
bash scripts/container-backup-test.sh
docker compose -p fleet-ci -f deploy/compose.test.yml down -v
```

The final command intentionally destroys only the disposable `fleet-ci` volumes. Never use it with the production project.

References: [Next.js 14 self-hosting](https://nextjs.org/docs/14/app/building-your-application/deploying), [Uvicorn deployment and supported worker package](https://www.uvicorn.org/deployment/), [PostgreSQL dump/restore](https://www.postgresql.org/docs/17/backup-dump.html).

## Verification in the implementation workspace

Local verification used PostgreSQL 16.2 in isolated temporary databases: all revision upgrades, populated program/inspection/notification upgrades, persistent rows, non-superuser migration execution, real company onboarding, and an encrypted backup/restore passed. S3 transport was mocked for these local checks. Gunicorn worker startup and the built Next standalone server passed smoke checks. The backend suite, 24 Chromium tests, translation parity, lint (existing hook warnings) and Next production build passed. The PostgreSQL 17/MinIO/Caddy container suite is defined as a required CI gate but was not run locally because Docker was unavailable. Run that gate before deployment; host DNS, certificate issuance, real buckets, SMTP credentials and production recovery-key access require environment-specific verification.
