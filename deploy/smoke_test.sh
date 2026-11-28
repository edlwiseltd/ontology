#!/usr/bin/env bash
# Smoke-test the Docker image end to end with the insurance example:
# start, health, sign-in, data load, metrics, online backup, graceful stop, restart with data intact.
#   deploy/smoke_test.sh [IMAGE]        (default autology:dev; run from the repository root)
set -euo pipefail
IMAGE="${1:-autology:dev}"
NAME="autology-smoke-$$"
PORT="${SMOKE_PORT:-18800}"
VOLUME="$NAME-data"
ENVS=(-e AUTOLOGY_AUDIT_KEY=smoke-audit-key -e AUTOLOGY_TOKEN_ADMIN=smoke-admin -e AUTOLOGY_TOKEN_ETL=smoke-etl
      -e AUTOLOGY_TOKEN_HANA=smoke-hana -e AUTOLOGY_TOKEN_IVAN=smoke-ivan -e AUTOLOGY_TOKEN_MARIA=smoke-maria)
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm "$VOLUME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

start() {
  docker run -d --name "$NAME" -p "127.0.0.1:$PORT:8800" "${ENVS[@]}" \
    -v "$PWD/examples/auto_insurance:/config:ro" -v "$VOLUME:/data" "$IMAGE" >/dev/null
  for _ in $(seq 1 60); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' "$NAME")" = healthy ] && return 0
    sleep 1
  done
  docker logs "$NAME"; echo "FAIL: container never became healthy"; exit 1
}
api() { curl -fsS -H "Authorization: Bearer $1" "${@:3}" "http://127.0.0.1:$PORT/api/$2"; }
check() { if ! grep -q -- "$2" <<<"$3"; then echo "FAIL: $1 (expected '$2')"; echo "$3"; exit 1; fi; echo "ok: $1"; }

start
check "health" '"status": "ok"' "$(curl -fsS "http://127.0.0.1:$PORT/api/health")"
check "inbox served" "Autology Inbox" "$(curl -fsS "http://127.0.0.1:$PORT/")"
check "sign-in" '"name": "admin"' "$(api smoke-admin me)"
check "data load" '"created": 3' "$(api smoke-etl pipelines/claims_feed/run -X POST -d '{}')"
check "automation settled the new claim" '"status": "paid"' "$(api smoke-admin objects/CL-4)"
check "metrics" 'autology_ingest_rejected_rows_total{pipeline="claims_feed"} 3' "$(api smoke-admin metrics)"
check "bad token refused" "401" "$(curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer nope' \
  "http://127.0.0.1:$PORT/api/me")"
check "online backup" "every audit chain verifies" \
  "$(docker exec "$NAME" autology backup /config/server.json /data/backup.db --store /data/autology.db)"
docker stop -t 20 "$NAME" >/dev/null
check "graceful stop" "Autology stopped" "$(docker logs "$NAME" 2>&1)"
docker rm "$NAME" >/dev/null
start
check "data survives a restart" '"status": "paid"' "$(api smoke-admin objects/CL-4)"
check "runs survive a restart" '"audit_verified": true' \
  "$(api smoke-admin "runs/$(api smoke-admin runs | python3 -c 'import json,sys; print(json.load(sys.stdin)["items"][0]["run_id"])')")"
echo "smoke test passed"
