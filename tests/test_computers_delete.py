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
"""immybot_computers_delete: confirm gate, bulk-delete call shape, errors (PRD-21591)."""

import json

import pytest

from immybot_mcp.api_client import ImmyBotClient, ImmyBotCredentials, ImmyBotError
from immybot_mcp.server import _credentials_var, create_mcp_server

CREDS = ImmyBotCredentials(subdomain="examplemsp", tenant_id="t1", client_id="c1", client_secret="secret")


def _envelope(content) -> dict:
    return json.loads(content[0].text)


async def _never_called(self, *args, **kwargs):
    raise AssertionError("ImmyBotClient.post must not be called")


@pytest.fixture
def mcp():
    return create_mcp_server()


@pytest.fixture
def with_credentials():
    token = _credentials_var.set(CREDS)
    try:
        yield
    finally:
        _credentials_var.reset(token)


async def test_computers_delete_without_confirm_returns_not_confirmed(mcp, with_credentials, monkeypatch):
    monkeypatch.setattr(ImmyBotClient, "post", _never_called)
    content, _ = await mcp.call_tool("immybot_computers_delete", {"computerIds": [123, 456]})
    result = _envelope(content)
    assert result["done"] is False
    assert "123" in result["action"] and "456" in result["action"]


async def test_computers_delete_confirmed_calls_bulk_delete_once(mcp, with_credentials, monkeypatch):
    calls = []

    async def fake_post(self, path, body=None, params=None, read_timeout=None):
        calls.append((path, body))
        return {"ok": True}

    monkeypatch.setattr(ImmyBotClient, "post", fake_post)
    content, _ = await mcp.call_tool("immybot_computers_delete", {"computerIds": [123, 456], "confirm": True})
    result = _envelope(content)
    assert calls == [("computers/bulk-delete", {"ids": [123, 456]})]
    assert result == {"done": True, "deleted_count": 2, "computer_ids": [123, 456], "result": {"ok": True}}


async def test_computers_delete_upstream_error_returns_envelope(mcp, with_credentials, monkeypatch):
    async def fake_post(self, path, body=None, params=None, read_timeout=None):
        raise ImmyBotError(404, "computer 999 not found")

    monkeypatch.setattr(ImmyBotClient, "post", fake_post)
    content, _ = await mcp.call_tool("immybot_computers_delete", {"computerIds": [999], "confirm": True})
    error = _envelope(content)["error"]
    assert error == {"code": "not_found", "message": "computer 999 not found", "retryable": False}


async def test_computers_delete_empty_ids_rejected(mcp, with_credentials, monkeypatch):
    monkeypatch.setattr(ImmyBotClient, "post", _never_called)
    content, _ = await mcp.call_tool("immybot_computers_delete", {"computerIds": [], "confirm": True})
    error = _envelope(content)["error"]
    assert error["code"] == "invalid_argument"


async def test_computers_delete_oversized_batch_rejected(mcp, with_credentials, monkeypatch):
    monkeypatch.setattr(ImmyBotClient, "post", _never_called)
    content, _ = await mcp.call_tool("immybot_computers_delete", {"computerIds": list(range(1, 202)), "confirm": True})
    error = _envelope(content)["error"]
    assert error["code"] == "invalid_argument"


async def test_computers_delete_missing_credentials_returns_not_configured(mcp, monkeypatch):
    monkeypatch.setattr(ImmyBotClient, "post", _never_called)
    assert _credentials_var.get() is None  # no with_credentials fixture: outside any request context
    content, _ = await mcp.call_tool("immybot_computers_delete", {"computerIds": [123], "confirm": True})
    error = _envelope(content)["error"]
    assert error["code"] == "not_configured"
