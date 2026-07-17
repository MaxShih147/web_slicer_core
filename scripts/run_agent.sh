#!/bin/bash
# Run the web_slicer_core agent

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q -r requirements.txt

# Check if slicer-engine CLI exists
# Prefer SLICER_ENGINE_BIN (canonical); accept legacy PRUSA_SLICER_BIN for local transition
if [ -n "${SLICER_ENGINE_BIN:-}" ]; then
  CLI_PATH="$SLICER_ENGINE_BIN"
elif [ -n "${PRUSA_SLICER_BIN:-}" ]; then
  CLI_PATH="$PRUSA_SLICER_BIN"
elif [ -f "$REPO_ROOT/slicer-engine/bin/slicer-engine" ]; then
  CLI_PATH="$REPO_ROOT/slicer-engine/bin/slicer-engine"
else
  CLI_PATH="$REPO_ROOT/third_party/prusaslicer_build/src/slicer-engine"
fi
if [ ! -f "$CLI_PATH" ]; then
    echo "ERROR: Slicer engine CLI not found at $CLI_PATH"
    echo "Please build first: ./scripts/build_prusaslicer_fork_macos.sh"
    echo "Or set SLICER_ENGINE_BIN to the correct path."
    exit 1
fi
export SLICER_ENGINE_BIN="$CLI_PATH"

# TLS resolution order matches agent/config.py: env, then agent/tls/, then Bundle-Launcher (mac, win).
if [ -n "${AGENT_TLS_CERTFILE:-}" ]; then
  CERT_PATH="$AGENT_TLS_CERTFILE"
else
  CERT_PATH=""
  for c in \
    "$REPO_ROOT/agent/tls/localhost.crt" \
    "$REPO_ROOT/../Bundle-Launcher/bundle-mac/agent/tls/localhost.crt" \
    "$REPO_ROOT/../Bundle-Launcher/bundle-win/agent/tls/localhost.crt"; do
    if [ -f "$c" ]; then CERT_PATH="$c"; break; fi
  done
fi
if [ -n "${AGENT_TLS_KEYFILE:-}" ]; then
  KEY_PATH="$AGENT_TLS_KEYFILE"
else
  KEY_PATH=""
  for k in \
    "$REPO_ROOT/agent/tls/localhost.key" \
    "$REPO_ROOT/../Bundle-Launcher/bundle-mac/agent/tls/localhost.key" \
    "$REPO_ROOT/../Bundle-Launcher/bundle-win/agent/tls/localhost.key"; do
    if [ -f "$k" ]; then KEY_PATH="$k"; break; fi
  done
fi
if [ -z "$CERT_PATH" ] || [ ! -f "$CERT_PATH" ] || [ -z "$KEY_PATH" ] || [ ! -f "$KEY_PATH" ]; then
    echo "ERROR: TLS cert/key not found."
    echo "Checked:"
    echo "  cert: $CERT_PATH"
    echo "  key : $KEY_PATH"
    echo "Set AGENT_TLS_CERTFILE and AGENT_TLS_KEYFILE, or prepare agent/tls/localhost.crt|key."
    exit 1
fi
export AGENT_TLS_CERTFILE="$CERT_PATH"
export AGENT_TLS_KEYFILE="$KEY_PATH"

echo "Starting web_slicer_core agent on https://127.0.0.1:5179"
echo "Press Ctrl+C to stop"
echo ""

# Run the agent
python -m uvicorn agent.main:app --host 127.0.0.1 --port 5179 --reload --ssl-certfile "$AGENT_TLS_CERTFILE" --ssl-keyfile "$AGENT_TLS_KEYFILE"
