# Copyright 2026 MSPbots.ai
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Credential middleware: 401 / 400 on bad headers, subdomain normalisation, isolation."""

import asyncio

import pytest
from starlette.testclient import TestClient

from immybot_mcp.__main__ import build_http_app
from immybot_mcp.server import (
    GatewayCredentialsMiddleware,
    _credentials_var,
    create_mcp_server,
    get_client_from_context,
    normalize_subdomain,
)

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
CREDS = {
    "X-Immybot-Instance-Subdomain": "examplemsp",
    "X-Immybot-Tenant-Id": "00000000-0000-0000-0000-000000000001",
    "X-Immybot-Client-Id": "00000000-0000-0000-0000-000000000002",
    "X-Immybot-Client-Secret": "secret",
}


def _client() -> TestClient:
    return TestClient(build_http_app(create_mcp_server()))


def test_health_is_local():
    with _client() as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize("missing", list(CREDS))
def test_missing_header_returns_401(missing):
    headers = {k: v for k, v in CREDS.items() if k != missing}
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | headers)
    assert resp.status_code == 401
    assert missing in resp.json()["message"]
    assert resp.json()["required_headers"] == list(CREDS)


def test_placeholder_counts_as_missing():
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | CREDS | {"X-Immybot-Client-Secret": "${SECRET}"})
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "header,value",
    [("X-Immybot-Instance-Subdomain", "bad_name!"), ("X-Immybot-Instance-Subdomain", "https://example.com"), ("X-Immybot-Tenant-Id", "a/b")],
)
def test_invalid_values_return_400(header, value):
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | CREDS | {header: value})
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "value,expected",
    [
        ("examplemsp", "examplemsp"),
        ("ExampleMSP", "examplemsp"),
        ("examplemsp.immy.bot", "examplemsp"),
        ("https://examplemsp.immy.bot/", "examplemsp"),
        ("https://examplemsp.immy.bot/api/v1", "examplemsp"),
        ("example-msp", "example-msp"),
        ("-bad", None),
        ("a.b", None),
        ("", None),
    ],
)
def test_normalize_subdomain(value, expected):
    assert normalize_subdomain(value) == expected


def test_tools_list_over_http():
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | CREDS)
    assert resp.status_code == 200
    for name in ("immybot_computers_list", "immybot_tasks_queue_stats", "immybot_tenants_software_inventory"):
        assert name in resp.text


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(_message):
    return None


def _headers(**overrides: bytes) -> list[tuple[bytes, bytes]]:
    base = {k.lower().encode(): v.encode() for k, v in CREDS.items()}
    base.update({k.encode(): v for k, v in overrides.items()})
    return list(base.items())


def _run_middleware(headers: list[tuple[bytes, bytes]]) -> dict:
    seen: dict = {}

    async def app(scope, receive, send):
        seen["credentials"] = _credentials_var.get()
        seen["client"] = get_client_from_context()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(GatewayCredentialsMiddleware(app)({"type": "http", "path": "/mcp", "headers": headers}, _receive, _send))
    return seen


def test_credentials_reach_request_context_and_are_reset():
    seen = _run_middleware(_headers(**{"x-immybot-instance-subdomain": b" examplemsp.immy.bot "}))
    assert seen["client"].base_url == "https://examplemsp.immy.bot/api/v1"
    assert seen["credentials"].client_secret == "secret"
    assert _credentials_var.get() is None


def test_concurrent_requests_do_not_share_credentials():
    observed: list[tuple[str, str]] = []

    async def app(scope, receive, send):
        before = _credentials_var.get().subdomain
        await asyncio.sleep(0.01)
        observed.append((before, _credentials_var.get().subdomain))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = GatewayCredentialsMiddleware(app)

    def scope(sub: bytes) -> dict:
        return {"type": "http", "path": "/mcp", "headers": _headers(**{"x-immybot-instance-subdomain": sub})}

    async def both():
        await asyncio.gather(middleware(scope(b"tenant-a"), _receive, _send), middleware(scope(b"tenant-b"), _receive, _send))

    asyncio.run(both())
    assert sorted(observed) == [("tenant-a", "tenant-a"), ("tenant-b", "tenant-b")]


def test_credentials_repr_hides_secret():
    seen = _run_middleware(_headers(**{"x-immybot-client-secret": b"very-secret-value"}))
    assert "very-secret-value" not in repr(seen["credentials"])
