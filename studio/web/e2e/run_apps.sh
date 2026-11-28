#!/usr/bin/env bash
# Application Builder browser tests: three released synthetic solutions, one designer, one renderer.
#   (cd studio/web && npm run build && e2e/run_apps.sh)
set -euo pipefail
cd "$(dirname "$0")/.."
PLATFORM_PORT="${APPS_PLATFORM_PORT:-8703}"; STUDIO_PORT="${APPS_STUDIO_PORT:-8963}"
python3 e2e/serve_domains.py "$PLATFORM_PORT" > /tmp/studio-e2e-apps-platform.log 2>&1 & PLATFORM=$!
AUTOLOGY_PLATFORM_URL="http://127.0.0.1:$PLATFORM_PORT" NEXT_TELEMETRY_DISABLED=1 \
  node node_modules/next/dist/bin/next start --port "$STUDIO_PORT" > /tmp/studio-e2e-apps-next.log 2>&1 & STUDIO=$!
trap 'kill $STUDIO $PLATFORM 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$PLATFORM_PORT/platform/health" >/dev/null && \
  curl -sf "http://127.0.0.1:$STUDIO_PORT/" >/dev/null && break; sleep 1; done
python3 e2e/prepare_apps.py "http://127.0.0.1:$PLATFORM_PORT"
STUDIO_URL="http://127.0.0.1:$STUDIO_PORT" node e2e/apps.mjs
