"""Configuration for the web_slicer_core agent."""

import os
from pathlib import Path

# Base paths
AGENT_DIR = Path(__file__).parent
REPO_ROOT = AGENT_DIR.parent
# Use BUNDLE_JOBS_DIR when set by Bundle Launcher (packaged Windows/macOS) so jobs dir is user-writable; otherwise use agent dir (dev or standalone).
JOBS_DIR = Path(os.getenv("BUNDLE_JOBS_DIR", str(AGENT_DIR / "jobs")))

# PrusaSlicer CLI path
# Use PRUSA_SLICER_BIN env var if set, otherwise fall back to local build
import sys
if sys.platform == "win32":
    _default_cli = REPO_ROOT / "third_party" / "prusaslicer_build" / "src" / "Release" / "prusa-slicer.exe"
else:
    _default_cli = REPO_ROOT / "third_party" / "prusaslicer_build" / "src" / "prusa-slicer"
PRUSA_SLICER_CLI = Path(os.getenv("PRUSA_SLICER_BIN", str(_default_cli)))

# Server config
HOST = "127.0.0.1"
PORT = 5179
TLS_DIR = AGENT_DIR / "tls"


def _resolve_tls_path(env_name: str, default_filename: str) -> Path:
    env_value = os.getenv(env_name, "").strip()
    if env_value:
        return Path(env_value)

    candidates = [
        TLS_DIR / default_filename,
        # Cross-repo dev fallback: reuse Bundle-Launcher prepared certs.
        REPO_ROOT.parent / "Bundle-Launcher" / "bundle-mac" / "agent" / "tls" / default_filename,
        REPO_ROOT.parent / "Bundle-Launcher" / "bundle-win" / "agent" / "tls" / default_filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    # Keep primary default for clearer error message on startup.
    return TLS_DIR / default_filename


TLS_CERT_PATH = _resolve_tls_path("AGENT_TLS_CERTFILE", "localhost.crt")
TLS_KEY_PATH = _resolve_tls_path("AGENT_TLS_KEYFILE", "localhost.key")

# Experimental: Export 3MF project file alongside SLA layers
# DISABLED: Testing confirmed that PrusaSlicer CLI --export-3mf exports only
# the base model geometry and does NOT preserve support information.
# The exported 3MF is equivalent to the input STL wrapped in 3MF format.
# Keeping code for future reference; set to True to re-enable if needed.
EXPORT_PROJECT_3MF = False

# Ensure jobs directory exists (parents=True when using BUNDLE_JOBS_DIR under user data)
JOBS_DIR.mkdir(parents=True, exist_ok=True)
