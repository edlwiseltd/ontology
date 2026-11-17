#!/usr/bin/env bash
# Browser tests of Studio against a real platform, then proof that the engine keeps working with Studio stopped.
#   (cd studio/web && npm run build && e2e/run.sh)
set -euo pipefail
cd "$(dirname "$0")/.."
PLATFORM_PORT="${PLATFORM_PORT:-8701}"; STUDIO_PORT="${STUDIO_PORT:-8961}"
python3 e2e/serve_platform.py "$PLATFORM_PORT" > /tmp/studio-e2e-platform.log 2>&1 & PLATFORM=$!
AUTOLOGY_PLATFORM_URL="http://127.0.0.1:$PLATFORM_PORT" NEXT_TELEMETRY_DISABLED=1 \
  node node_modules/next/dist/bin/next start --port "$STUDIO_PORT" > /tmp/studio-e2e-next.log 2>&1 & STUDIO=$!
trap 'kill $STUDIO $PLATFORM 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$PLATFORM_PORT/platform/health" >/dev/null && \
  curl -sf "http://127.0.0.1:$STUDIO_PORT/" >/dev/null && break; sleep 1; done
STUDIO_URL="http://127.0.0.1:$STUDIO_PORT" node e2e/run.mjs
kill $STUDIO 2>/dev/null || true; wait $STUDIO 2>/dev/null || true
for _ in $(seq 1 20); do curl -sf "http://127.0.0.1:$STUDIO_PORT/" >/dev/null || break; sleep 0.5; done
if curl -sf "http://127.0.0.1:$STUDIO_PORT/" >/dev/null; then echo "FAIL Studio is still running"; exit 1; fi
echo "PASS Studio is stopped"
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer acme-hana' "http://127.0.0.1:$PLATFORM_PORT/w/acme/u/claims/api/ontology")
[ "$code" = 200 ] && echo "PASS engine answers with Studio stopped (HTTP $code)" || { echo "FAIL engine with Studio stopped: $code"; exit 1; }
e2e/run_domains.sh
