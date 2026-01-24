"""Configuration for the web_slicer_core agent."""

import os
from pathlib import Path

# Base paths
AGENT_DIR = Path(__file__).parent
REPO_ROOT = AGENT_DIR.parent
JOBS_DIR = AGENT_DIR / "jobs"

# PrusaSlicer CLI path
PRUSA_SLICER_CLI = REPO_ROOT / "build" / "src" / "prusa-slicer"

# Server config
HOST = "127.0.0.1"
PORT = 5179

# Ensure jobs directory exists
JOBS_DIR.mkdir(exist_ok=True)
