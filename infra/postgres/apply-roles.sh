#!/bin/sh
# Compose one-shot (db-roles): applies roles.sql as the stack's superuser. All values come from
# the environment (stack.env); nothing secret appears on a command line.
set -eu
PGUSER="$POSTGRES_USER"
PGDATABASE="$POSTGRES_DB"
PGPASSWORD="$POSTGRES_PASSWORD"
export PGUSER PGDATABASE PGPASSWORD
exec psql -v ON_ERROR_STOP=1 -q -v db="$POSTGRES_DB" \
  -v platform_user=lr_platform -v realtime_user=lr_realtime -v portal_role=lr_portal \
  -f "$(dirname "$0")/roles.sql"
