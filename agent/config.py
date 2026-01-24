"""Configuration for the web_slicer_core agent."""

import os
from pathlib import Path

# Base paths
AGENT_DIR = Path(__file__).parent
REPO_ROOT = AGENT_DIR.parent
JOBS_DIR = AGENT_DIR / "jobs"

# PrusaSlicer CLI path
# Use PRUSA_SLICER_BIN env var if set, otherwise fall back to local build
_default_cli = REPO_ROOT / "build" / "src" / "prusa-slicer"
PRUSA_SLICER_CLI = Path(os.getenv("PRUSA_SLICER_BIN", str(_default_cli)))

# Server config
HOST = "127.0.0.1"
PORT = 5179

# Experimental: Export 3MF project file alongside SLA layers
# DISABLED: Testing confirmed that PrusaSlicer CLI --export-3mf exports only
# the base model geometry and does NOT preserve support information.
# The exported 3MF is equivalent to the input STL wrapped in 3MF format.
# Keeping code for future reference; set to True to re-enable if needed.
EXPORT_PROJECT_3MF = False

# Ensure jobs directory exists
JOBS_DIR.mkdir(exist_ok=True)
