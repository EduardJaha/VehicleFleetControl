#!/usr/bin/env bash
set -euo pipefail
export BACKUP_TEST_DIR
BACKUP_TEST_DIR=$(mktemp -d /tmp/fleet-backup-test.XXXXXX)
# This folder contains only disposable CI keys. Permit the postgres container user to create its identity.
chmod 777 "$BACKUP_TEST_DIR"
trap 'rm -rf "$BACKUP_TEST_DIR"' EXIT
compose=(docker compose -p fleet-ci -f deploy/compose.test.yml)
"${compose[@]}" --profile backup build backup
"${compose[@]}" run --rm --entrypoint age-keygen backup -o /test/identity
recipient=$("${compose[@]}" run --rm --entrypoint age-keygen backup -y /test/identity)
"${compose[@]}" run --rm -e "BACKUP_AGE_RECIPIENT=$recipient" backup once > "$BACKUP_TEST_DIR/result.json"
key=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["key"])' "$BACKUP_TEST_DIR/result.json")
"${compose[@]}" run --rm -e PGUSER=fleet_admin -e PGPASSWORD=test-admin-password -e RESTORE_DATABASE=fleet_restore_ci -e BACKUP_AGE_IDENTITY_FILE=/test/identity backup restore-test --key "$key"
