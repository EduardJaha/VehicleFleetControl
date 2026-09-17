#!/usr/bin/env bash
set -euo pipefail
revision=$1
export BACKEND_IMAGE=$2 FRONTEND_IMAGE=$3 BACKUP_IMAGE=$4
target=$5
[[ "$revision" =~ ^[a-f0-9]{40}$ ]]
for image in "$BACKEND_IMAGE" "$FRONTEND_IMAGE" "$BACKUP_IMAGE"; do
  [[ "$image" =~ ^ghcr.io/[a-z0-9_./-]+@sha256:[a-f0-9]{64}$ ]]
done
[[ "$target" == staging || "$target" == production ]]
release="/opt/vehiclefleetcontrol/$target/releases/$revision"
mkdir -p "$release"
tar -xzf "/tmp/fleet-$revision.tar.gz" -C "$release"
cd "$release"
# Persist non-secret immutable image references for subsequent operator commands.
printf 'BACKEND_IMAGE=%s\nFRONTEND_IMAGE=%s\nBACKUP_IMAGE=%s\n' "$BACKEND_IMAGE" "$FRONTEND_IMAGE" "$BACKUP_IMAGE" > images.env
compose=(docker compose --env-file "/etc/vehiclefleetcontrol/$target/compose.env" -p "fleet-$target" -f docker-compose.prod.yml)
"${compose[@]}" config --quiet
"${compose[@]}" pull backend frontend scheduler migrate backup
"${compose[@]}" up -d --wait database
"${compose[@]}" run --rm --no-deps backend python -m app.core.deployment
# Quiesce writers; take an encrypted backup before changing the schema.
"${compose[@]}" stop proxy scheduler backend
"${compose[@]}" run --rm --no-deps backup once
"${compose[@]}" run --rm --no-deps migrate
"${compose[@]}" up -d --wait --wait-timeout 240
ln -sfn "$release" "/opt/vehiclefleetcontrol/$target/current"
rm "/tmp/fleet-$revision.tar.gz"
