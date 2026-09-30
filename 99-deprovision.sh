#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

docker compose down -v
echo "Torn down. Run ./00-provision.sh to start fresh."
