#!/bin/bash
# setup.sh — Generate deployment configs from templates and load launchd services.
#
# Usage:
#   cd web_slicer_core/deploy
#   cp .env.example .env   # edit with real values
#   ./setup.sh
#
# Requires: envsubst (from gettext — `brew install gettext`)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/templates"
ENV_FILE="$SCRIPT_DIR/.env"

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Copy .env.example to .env and fill in values."
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# ---------------------------------------------------------------------------
# Validate required variables
# ---------------------------------------------------------------------------
for var in FRONTEND_DIST BACKEND_DIR SLICER_ENGINE_BIN \
           PYTHON_BIN NGINX_BIN NGINX_PORT BACKEND_PORT LOG_DIR; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: Required variable $var is not set in .env"
        exit 1
    fi
done

# Validate paths exist
for path_var in FRONTEND_DIST BACKEND_DIR SLICER_ENGINE_BIN PYTHON_BIN NGINX_BIN; do
    if [ ! -e "${!path_var}" ]; then
        echo "WARNING: ${path_var}=${!path_var} does not exist"
    fi
done

# ---------------------------------------------------------------------------
# Ensure output directories exist
# ---------------------------------------------------------------------------
mkdir -p "$LOG_DIR"
mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "/opt/homebrew/etc/nginx/servers"

# ---------------------------------------------------------------------------
# envsubst variable list — only substitute our variables, not nginx $vars
# ---------------------------------------------------------------------------
ENVSUBST_VARS='${BACKEND_PORT} ${NGINX_PORT} ${FRONTEND_DIST} ${LOG_DIR} ${PYTHON_BIN} ${BACKEND_DIR} ${SLICER_ENGINE_BIN} ${NGINX_BIN} ${HOME}'

# ---------------------------------------------------------------------------
# Generate configs
# ---------------------------------------------------------------------------
echo "=== Generating Nginx config ==="
envsubst "$ENVSUBST_VARS" < "$TEMPLATE_DIR/nginx.conf.template" \
    > /opt/homebrew/etc/nginx/servers/dentalslice.conf
echo "  -> /opt/homebrew/etc/nginx/servers/dentalslice.conf"

echo "=== Generating launchd plists ==="
for service in backend nginx; do
    envsubst "$ENVSUBST_VARS" < "$TEMPLATE_DIR/${service}.plist.template" \
        > "$HOME/Library/LaunchAgents/com.dentalslice.${service}.plist"
    echo "  -> ~/Library/LaunchAgents/com.dentalslice.${service}.plist"
done

# ---------------------------------------------------------------------------
# Validate nginx config
# ---------------------------------------------------------------------------
echo ""
echo "=== Validating Nginx config ==="
if "$NGINX_BIN" -t 2>&1; then
    echo "  Nginx config OK"
else
    echo "ERROR: Nginx config validation failed. Fix the config and re-run."
    exit 1
fi

# ---------------------------------------------------------------------------
# Load launchd services
# ---------------------------------------------------------------------------
echo ""
echo "=== Loading launchd services ==="
UID_NUM="$(id -u)"
for service in backend nginx; do
    plist="$HOME/Library/LaunchAgents/com.dentalslice.${service}.plist"
    label="com.dentalslice.${service}"
    # Unload if already loaded (ignore errors), then reload
    if launchctl print "gui/${UID_NUM}/${label}" &>/dev/null; then
        launchctl bootout "gui/${UID_NUM}/${label}" 2>/dev/null || true
        sleep 1
    fi
    launchctl bootstrap "gui/${UID_NUM}" "$plist"
    echo "  Loaded ${label}"
done

echo ""
echo "=== Setup complete ==="
echo "Services should be starting. Check with:"
echo "  launchctl list | grep dentalslice"
echo "  curl http://localhost:${NGINX_PORT}/"
echo "  curl http://localhost:${NGINX_PORT}/api/"
