#!/usr/bin/env bash
# Prerequisite checks — run standalone any time ("did my token get rotated?")
# or let ./00-provision.sh call it automatically. Verifies EDB_SUBSCRIPTION_TOKEN
# (against both the package repo postgres/Dockerfile installs aidb/pgfs from,
# and the docker.enterprisedb.com registry the base image is pulled from) and
# NVIDIA_API_KEY, by actually hitting/logging into the real services — so a
# stale/rotated credential fails here in a few seconds with a clear message
# instead of partway through a slow docker build or a confusing NIM 401.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

all_ok=true
pass() { printf '  %-34s ok\n' "$1"; }
fail() { printf '  %-34s FAILED — %s\n' "$1" "$2"; all_ok=false; }

echo "Checking prerequisites..."
echo

if [ -f .env ]; then
  pass ".env file"
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
else
  fail ".env file" "not found — run: cp .env-example .env"
fi

if command -v docker >/dev/null 2>&1; then
  pass "docker installed"
else
  fail "docker installed" "not found — install Docker Desktop first"
fi

if docker info >/dev/null 2>&1; then
  pass "docker daemon running"
else
  fail "docker daemon running" "can't reach it — is Docker Desktop started?"
fi

if docker compose version >/dev/null 2>&1; then
  pass "docker compose v2"
else
  fail "docker compose v2" "not found — update Docker Desktop or install the compose plugin"
fi

if [ -n "${EDB_SUBSCRIPTION_TOKEN:-}" ]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
    "https://downloads.enterprisedb.com/${EDB_SUBSCRIPTION_TOKEN}/enterprise/setup.rpm.sh" 2>/dev/null || echo "000")
  if [ "$code" = "200" ]; then
    pass "EDB_SUBSCRIPTION_TOKEN (packages)"
  else
    fail "EDB_SUBSCRIPTION_TOKEN (packages)" "EDB's package repo returned HTTP $code — token is missing, expired, or was rotated. Get a current one: https://www.enterprisedb.com/repos/getting_started/get_your_token/"
  fi

  # Package-repo access (above) and the container registry (below) are two
  # separate credential checks against two separate EDB services — a token
  # can be valid for one and not the other, and this is also the actual
  # `docker login` step the README's Quickstart otherwise asks for manually,
  # so a passing check here leaves the build ready to pull the base image.
  login_log=$(mktemp)
  if printf '%s' "${EDB_SUBSCRIPTION_TOKEN}" \
      | docker login docker.enterprisedb.com --username k8s --password-stdin >"$login_log" 2>&1; then
    pass "EDB_SUBSCRIPTION_TOKEN (registry)"
  else
    fail "EDB_SUBSCRIPTION_TOKEN (registry)" "docker login docker.enterprisedb.com rejected the token — rotated/expired? Get a current one: https://www.enterprisedb.com/repos/getting_started/get_your_token/"
  fi
  rm -f "$login_log"
else
  fail "EDB_SUBSCRIPTION_TOKEN (packages)" "not set in .env"
  fail "EDB_SUBSCRIPTION_TOKEN (registry)" "not set in .env"
fi

if [ -n "${NVIDIA_API_KEY:-}" ]; then
  # /v1/models is unauthenticated (any key, or none, returns 200 from it) so
  # it can't tell a bad key from a good one — make a real (tiny) embeddings
  # call instead, against the same model create_pipelines.py actually uses.
  embed_model="${NIM_EMBEDDINGS_MODEL:-nvidia/nemotron-3-embed-1b}"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
    -X POST "https://integrate.api.nvidia.com/v1/embeddings" \
    -H "Authorization: Bearer ${NVIDIA_API_KEY}" -H "Content-Type: application/json" \
    -d "{\"input\":[\"prereq check\"],\"model\":\"${embed_model}\",\"input_type\":\"query\"}" \
    2>/dev/null || echo "000")
  case "$code" in
    200)
      pass "NVIDIA_API_KEY" ;;
    401|403)
      fail "NVIDIA_API_KEY" "NVIDIA's API returned HTTP $code — key is missing, invalid, or expired. Get a current one: https://build.nvidia.com/explore/discover" ;;
    404)
      fail "NVIDIA_API_KEY" "NVIDIA's API returned HTTP 404 for model '$embed_model' — the key itself may be fine, but this model may have been retired. See README's 'NVIDIA NIM model churn' note and consider setting NIM_EMBEDDINGS_MODEL in .env." ;;
    *)
      fail "NVIDIA_API_KEY" "NVIDIA's API returned HTTP $code for an unexpected reason" ;;
  esac
else
  fail "NVIDIA_API_KEY" "not set in .env"
fi

echo
if $all_ok; then
  echo "All prerequisites OK."
else
  echo "One or more prerequisites failed — fix them above, then re-run ./00-prereq.sh (or just ./00-provision.sh, which calls this first)."
  exit 1
fi
