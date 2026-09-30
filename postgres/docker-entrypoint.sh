#!/usr/bin/env bash
set -euo pipefail

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "Initializing database cluster in $PGDATA..."
  PWFILE="$(mktemp)"
  printf '%s' "$POSTGRES_PASSWORD" > "$PWFILE"
  initdb -D "$PGDATA" -U "$POSTGRES_USER" --pwfile="$PWFILE" -E UTF8 \
    --auth-host=md5 --auth-local=trust
  rm -f "$PWFILE"

  {
    echo ""
    echo "# --- aidb-rag demo ---"
    echo "shared_preload_libraries = 'aidb'"
    echo "listen_addresses = '*'"
  } >> "$PGDATA/postgresql.conf"

  {
    # initdb only allows loopback host connections by default; the webapp
    # container reaches Postgres over the compose network, not loopback.
    echo "host all all 0.0.0.0/0 md5"
    echo "host all all ::/0      md5"
  } >> "$PGDATA/pg_hba.conf"
fi

exec postgres -D "$PGDATA"
