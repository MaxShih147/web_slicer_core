"""Origin write guard + 500MB limit (agent-origin-write-guard).

Seam: HTTP middleware on the agent app for `/api/` write methods.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent import cors, main
from agent.api_v2 import _pending_jobs

WHITELIST_ORIGIN = "https://slicergo-dental.phrozen3d.info"
FORGED_ORIGIN = "https://evil.example"
LOCALHOST_ORIGIN = "http://localhost:5173"
MAX_BYTES = 500 * 1024 * 1024


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def _cors_allowlist(monkeypatch):
    """Keep a known allowlist; restore after each test."""
    original = set(cors.cors_origins)
    cors.cors_origins.clear()
    cors.cors_origins.update(
        {
            "https://dev.slicergo-dental.phrozen3d.info",
            "https://release.slicergo-dental.phrozen3d.info",
            "https://slicergo-dental.phrozen3d.info",
            "https://dsonline.phrozen3d.info",
            LOCALHOST_ORIGIN,
        }
    )
    monkeypatch.setattr(cors, "enable_cors", True)
    yield
    cors.cors_origins.clear()
    cors.cors_origins.update(original)


def _create_slice(client: TestClient, *, origin: str | None = None, extra_headers: dict | None = None):
    headers = {}
    if origin is not None:
        headers["Origin"] = origin
    if extra_headers:
        headers.update(extra_headers)
    return client.post("/api/v2/slices", json={}, headers=headers)


class TestWhitelistOriginWrite:
    def test_allowed_origin_write_succeeds(self, client):
        before = set(_pending_jobs)
        resp = _create_slice(client, origin=WHITELIST_ORIGIN)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert set(_pending_jobs) - before  # job created


class TestForgedOriginWrite:
    def test_forged_origin_write_is_forbidden_without_side_effects(self, client):
        before = set(_pending_jobs)
        resp = _create_slice(client, origin=FORGED_ORIGIN)
        assert resp.status_code == 403
        body = resp.json()
        assert body["success"] is False
        assert body["code"] == "ORIGIN_FORBIDDEN"
        assert body["data"]["retryable"] is False
        assert set(_pending_jobs) == before


class TestMissingOriginWrite:
    def test_missing_origin_write_succeeds(self, client):
        resp = _create_slice(client, origin=None)
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestExemptPaths:
    def test_get_api_with_forged_origin_is_not_blocked(self, client):
        resp = client.get("/api/health", headers={"Origin": FORGED_ORIGIN})
        assert resp.status_code == 200
        assert resp.json().get("code") != "ORIGIN_FORBIDDEN"

    def test_non_api_write_with_forged_origin_is_not_origin_forbidden(self, client):
        resp = client.post("/", headers={"Origin": FORGED_ORIGIN})
        assert resp.status_code != 403 or resp.json().get("code") != "ORIGIN_FORBIDDEN"


class TestPayloadLimit:
    def test_oversized_content_length_is_413_with_cors(self, client):
        """Reject via Content-Length only — do not upload 500MB."""
        before = set(_pending_jobs)
        # Build a raw ASGI call so Content-Length is not rewritten to match body.
        oversized = str(MAX_BYTES + 1)
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v2/slices",
            "raw_path": b"/api/v2/slices",
            "query_string": b"",
            "headers": [
                (b"host", b"test"),
                (b"origin", WHITELIST_ORIGIN.encode()),
                (b"content-type", b"application/json"),
                (b"content-length", oversized.encode()),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("test", 80),
        }

        status_holder = {}
        headers_holder = {}
        body_chunks = []

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers_holder["headers"] = {
                    k.decode().lower(): v.decode() for k, v in message["headers"]
                }
            elif message["type"] == "http.response.body":
                body_chunks.append(message.get("body", b""))

        import anyio

        async def run():
            await main.app(scope, receive, send)

        anyio.run(run)

        assert status_holder["status"] == 413
        import json

        body = json.loads(b"".join(body_chunks))
        assert body["code"] == "PAYLOAD_TOO_LARGE"
        assert body["data"]["retryable"] is False
        assert headers_holder["headers"].get("access-control-allow-origin") == WHITELIST_ORIGIN
        assert set(_pending_jobs) == before


class TestLocalhostFromEnvAllowlist:
    def test_localhost_origin_write_succeeds(self, client):
        resp = _create_slice(client, origin=LOCALHOST_ORIGIN)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
