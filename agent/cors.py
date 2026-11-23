"""CORS allowlist shared by CORSMiddleware and the Origin write guard.

Single source of truth: hardcoded SlicerGo Dental / production dsonline hosts,
plus optional CORS_ALLOWED_ORIGINS (comma-separated). Do not maintain a second
Origin list elsewhere.
"""

from __future__ import annotations

import os

from starlette.requests import Request

# Shipped allowlist: SlicerGo Dental + production dsonline hosted UIs.
# Local / other transitional origins via CORS_ALLOWED_ORIGINS (comma-separated).
# onrender and ds-online.com origins are intentionally not hardcoded.
_HARDCODED_ORIGINS = (
    "https://dev.slicergo-dental.phrozen3d.info",
    "https://release.slicergo-dental.phrozen3d.info",
    "https://slicergo-dental.phrozen3d.info",
    "https://dsonline.phrozen3d.info",
)

cors_origins: set[str] = set(_HARDCODED_ORIGINS)
_extra = os.getenv("CORS_ALLOWED_ORIGINS", "")
if _extra.strip():
    cors_origins.update(
        origin.strip() for origin in _extra.split(",") if origin.strip()
    )

enable_cors = os.getenv("ENABLE_CORS", "true").lower() in ("true", "1", "yes")


def cors_headers_for_request(request: Request) -> dict:
    """Return CORS headers for the given request's origin, if allowed."""
    headers: dict[str, str] = {}
    if enable_cors:
        origin = request.headers.get("origin", "")
        if origin in cors_origins:
            headers["access-control-allow-origin"] = origin
            headers["access-control-allow-credentials"] = "true"
    return headers
