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

# Check if PrusaSlicer CLI exists
CLI_PATH="$REPO_ROOT/build/src/prusa-slicer"
if [ ! -f "$CLI_PATH" ]; then
    echo "ERROR: PrusaSlicer CLI not found at $CLI_PATH"
    echo "Please build PrusaSlicer first."
    exit 1
fi

echo "Starting web_slicer_core agent on http://127.0.0.1:5179"
echo "Press Ctrl+C to stop"
echo ""

# Run the agent
python -m uvicorn agent.main:app --host 127.0.0.1 --port 5179 --reload
