"""Origin write guard middleware for /api/ write requests.

Rules (deliberately different from local-library-service):
- Missing Origin → allow (local scripts).
- Origin present but not in CORS allowlist → 403 ORIGIN_FORBIDDEN.
- Origin allowed → enforce Content-Length ≤ 500 MiB before call_next.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .cors import cors_headers_for_request, cors_origins, enable_cors
from .errors import origin_forbidden, payload_too_large

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MiB


class OriginWriteGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not enable_cors:
            return await call_next(request)

        method = request.method.upper()
        if method not in WRITE_METHODS:
            return await call_next(request)

        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        origin = request.headers.get("origin")
        if not origin:
            # No Origin → allow (local scripts). Do not apply the 500MB gate here.
            return await call_next(request)

        if origin not in cors_origins:
            return origin_forbidden().to_response(cors_headers_for_request(request))

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                size = -1
            if size > MAX_UPLOAD_BYTES:
                return payload_too_large().to_response(cors_headers_for_request(request))

        return await call_next(request)
