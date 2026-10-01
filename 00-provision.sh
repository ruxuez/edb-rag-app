#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -f .env ]; then
  echo "No .env found. Copy .env-example to .env and fill it in first:"
  echo "  cp .env-example .env"
  exit 1
fi

echo "Building and starting containers..."
docker compose up --build -d

echo "Waiting for the dashboard to respond..."
for _ in $(seq 1 60); do
  if curl -sf http://localhost:8080/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! curl -sf http://localhost:8080/api/health >/dev/null 2>&1; then
  echo "Dashboard didn't come up in time. Check logs with: docker compose logs -f"
  exit 1
fi

cat <<'EOF'

Ready.

  Dashboard:      http://localhost:8080
  RustFS console: http://localhost:9001
  Postgres:       postgres://postgres:postgres@localhost:5434/demo

Open the dashboard and click through the Setup tab, in order, to build
the demo's knowledge bases.
EOF
