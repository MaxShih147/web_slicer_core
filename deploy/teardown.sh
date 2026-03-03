#!/bin/bash
# teardown.sh — Stop and unload all dentalslice launchd services.
#
# Usage:
#   cd web_slicer_core/deploy
#   ./teardown.sh
#
set -euo pipefail

UID_NUM="$(id -u)"

echo "=== Stopping dentalslice services ==="
for service in backend nginx; do
    label="com.dentalslice.${service}"
    if launchctl print "gui/${UID_NUM}/${label}" &>/dev/null; then
        launchctl bootout "gui/${UID_NUM}/${label}" 2>/dev/null || true
        echo "  Unloaded ${label}"
    else
        echo "  ${label} not loaded (skipping)"
    fi
done

echo ""
echo "=== Teardown complete ==="
echo "Configs remain in place. Re-run setup.sh to restart."
