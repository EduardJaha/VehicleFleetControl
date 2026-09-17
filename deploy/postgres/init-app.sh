#!/usr/bin/env bash
# Runs only for a new PostgreSQL volume. Existing installations need an explicit role migration.
set -euo pipefail
: "${POSTGRES_APP_USER:?Set the application database role}"
: "${POSTGRES_APP_PASSWORD_FILE:?Set the application password secret file}"
[[ "$POSTGRES_APP_USER" != "$POSTGRES_USER" ]]
export FLEET_APP_PASSWORD
FLEET_APP_PASSWORD=$(cat "$POSTGRES_APP_PASSWORD_FILE")
psql --no-psqlrc --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv app_user POSTGRES_APP_USER
\getenv app_password FLEET_APP_PASSWORD
\getenv app_database POSTGRES_DB
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'app_user', :'app_password') \gexec
SELECT format('ALTER DATABASE %I OWNER TO %I', :'app_database', :'app_user') \gexec
SELECT format('GRANT USAGE, CREATE ON SCHEMA public TO %I', :'app_user') \gexec
SQL
unset FLEET_APP_PASSWORD
