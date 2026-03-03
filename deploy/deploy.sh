#!/bin/bash
# deploy.sh — Build frontend + restart services.
#
# Usage:
#   cd web_slicer_core/deploy
#   ./deploy.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Run setup.sh first."
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

UID_NUM="$(id -u)"

# ---------------------------------------------------------------------------
# Step 1: Build frontend
# ---------------------------------------------------------------------------
FRONTEND_SRC="$(dirname "$FRONTEND_DIST")"
echo "=== Building frontend ==="
echo "  Source: $FRONTEND_SRC"
cd "$FRONTEND_SRC"
npm run build
echo "  Built -> $FRONTEND_DIST"

# ---------------------------------------------------------------------------
# Step 2: Validate nginx config
# ---------------------------------------------------------------------------
echo ""
echo "=== Validating Nginx config ==="
"$NGINX_BIN" -t 2>&1
echo "  OK"

# ---------------------------------------------------------------------------
# Step 3: Restart backend
# ---------------------------------------------------------------------------
echo ""
echo "=== Restarting backend ==="
launchctl kickstart -k "gui/${UID_NUM}/com.dentalslice.backend"
echo "  Backend restarted"

# ---------------------------------------------------------------------------
# Step 4: Reload nginx
# ---------------------------------------------------------------------------
echo ""
echo "=== Reloading Nginx ==="
"$NGINX_BIN" -s reload
echo "  Nginx reloaded"

# ---------------------------------------------------------------------------
# Step 5: Health checks
# ---------------------------------------------------------------------------
echo ""
echo "=== Health checks (waiting 3s for services to start) ==="
sleep 3

echo -n "  Frontend: "
if curl -sf -o /dev/null "http://localhost:${NGINX_PORT}/"; then
    echo "OK"
else
    echo "FAILED"
fi

echo -n "  Backend:  "
if curl -sf "http://localhost:${NGINX_PORT}/api/" 2>/dev/null | grep -q "running"; then
    echo "OK"
else
    echo "FAILED"
fi

echo ""
echo "=== Deploy complete ==="
