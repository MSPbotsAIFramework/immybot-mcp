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
"""Token flow, request shapes, retries and tool behaviour against a mocked ImmyBot API."""

import json
import uuid
from urllib.parse import parse_qs

import httpx
import pytest

from immybot_mcp import api_client
from immybot_mcp.api_client import ImmyBotClient, ImmyBotCredentials, ImmyBotError
from immybot_mcp.server import _credentials_var, create_mcp_server

CREDS = ImmyBotCredentials("examplemsp", "00000000-0000-0000-0000-000000000001", "client-1", "secret-1")
TOKEN_HOST = "login.microsoftonline.com"


@pytest.fixture(autouse=True)
def no_sleep_and_fresh_tokens(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(api_client.asyncio, "sleep", instant)
    api_client._token_cache.clear()
    yield
    api_client._token_cache.clear()


class Recorder:
    """Mock transport: the Entra token endpoint plus ImmyBot routes by method + path below /api/v1/."""

    def __init__(self, routes=None, default=None, token=None):
        self.requests: list[httpx.Request] = []
        self.token_requests: list[httpx.Request] = []
        self.routes = routes or {}
        self.default = default if default is not None else {}
        self.token = token

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == TOKEN_HOST:
            self.token_requests.append(request)
            if callable(self.token):
                return self.token(request)
            return httpx.Response(200, json={"access_token": f"tok-{len(self.token_requests)}", "expires_in": 3600, "token_type": "Bearer"})
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/v1/")
        reply = self.routes.get(f"{request.method} {path}", self.routes.get(path, self.default))
        if callable(reply):
            return reply(request)
        return httpx.Response(200, json=reply)

    def calls(self, path: str, method: str | None = None) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == f"/api/v1/{path}" and (method is None or r.method == method)]


def body(request: httpx.Request):
    return json.loads(request.content) if request.content else None


async def _call(monkeypatch, recorder: Recorder, tool: str, args: dict):
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    monkeypatch.setattr(api_client, "_get_shared_http_client", lambda: http)
    ctx = _credentials_var.set(CREDS)
    try:
        content, _ = await create_mcp_server().call_tool(tool, args)
    finally:
        _credentials_var.reset(ctx)
    return json.loads(content[0].text)


def _client(recorder: Recorder) -> ImmyBotClient:
    return ImmyBotClient(CREDS, httpx.AsyncClient(transport=httpx.MockTransport(recorder)))


# ---- auth ------------------------------------------------------------------


async def test_token_request_uses_instance_scope_and_is_cached():
    rec = Recorder({"tenants": []})
    client = _client(rec)
    await client.get("tenants")
    await client.get("tenants")
    assert len(rec.token_requests) == 1
    token_request = rec.token_requests[0]
    assert token_request.url.path == "/00000000-0000-0000-0000-000000000001/oauth2/v2.0/token"
    form = parse_qs(token_request.content.decode())
    assert form == {
        "grant_type": ["client_credentials"],
        "client_id": ["client-1"],
        "client_secret": ["secret-1"],
        "scope": ["https://examplemsp.immy.bot/.default"],
    }
    assert rec.requests[0].headers["authorization"] == "Bearer tok-1"
    assert str(rec.requests[0].url) == "https://examplemsp.immy.bot/api/v1/tenants"


async def test_token_cache_is_per_credential_set():
    rec = Recorder({"tenants": []})
    await _client(rec).get("tenants")
    other = ImmyBotClient(ImmyBotCredentials("examplemsp", CREDS.tenant_id, "client-1", "other-secret"), httpx.AsyncClient(transport=httpx.MockTransport(rec)))
    await other.get("tenants")
    assert len(rec.token_requests) == 2


async def test_401_refreshes_the_token_once():
    replies = iter([httpx.Response(401), httpx.Response(200, json=[])])
    rec = Recorder({"tenants": lambda r: next(replies)})
    assert await _client(rec).get("tenants") == []
    assert len(rec.token_requests) == 2
    assert rec.requests[1].headers["authorization"] == "Bearer tok-2"


async def test_trace_id_on_the_same_line_is_removed(monkeypatch):
    def token(_request):
        return httpx.Response(400, json={"error": "invalid_request", "error_description": "AADSTS90002: Tenant 'x' not found. Trace ID: 1 Correlation ID: 2"})

    result = await _call(monkeypatch, Recorder(token=token), "immybot_status", {})
    assert result["error"]["message"].endswith("AADSTS90002: Tenant 'x' not found.")


async def test_rejected_credentials_become_unauthorized(monkeypatch):
    def token(_request):
        return httpx.Response(400, json={"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret.\r\nTrace ID: abc"})

    rec = Recorder(token=token)
    result = await _call(monkeypatch, rec, "immybot_status", {})
    assert result["error"]["code"] == "unauthorized"
    assert "AADSTS7000215: Invalid client secret." in result["error"]["message"]
    assert "Trace ID" not in result["error"]["message"] and "secret-1" not in result["error"]["message"]
    assert rec.requests == []


# ---- client ----------------------------------------------------------------


async def test_get_retries_5xx_but_writes_do_not():
    replies = iter([httpx.Response(502), httpx.Response(200, json=[])])
    rec = Recorder({"GET tenants": lambda r: next(replies), "POST tenants": lambda r: httpx.Response(500, json={})})
    client = _client(rec)
    await client.get("tenants")
    with pytest.raises(ImmyBotError):
        await client.post("tenants", {})
    assert len(rec.calls("tenants", "GET")) == 2 and len(rec.calls("tenants", "POST")) == 1


async def test_web_app_page_is_not_found(monkeypatch):
    rec = Recorder({"auth": lambda r: httpx.Response(200, text="<!DOCTYPE html><html></html>", headers={"content-type": "text/html"})})
    result = await _call(monkeypatch, rec, "immybot_status", {})
    assert result["error"]["code"] == "not_found"


async def test_error_body_is_readable(monkeypatch):
    rec = Recorder({"tenants/9": lambda r: httpx.Response(400, json={"error": {"code": "bad", "message": "Tenant is inactive", "details": None}})})
    result = await _call(monkeypatch, rec, "immybot_tenants_get", {"tenantId": 9})
    assert result["error"]["message"].endswith("Tenant is inactive")


async def test_problem_details_errors(monkeypatch):
    problem = {"title": "One or more validation errors occurred.", "errors": {"Name": ["The Name field is required."]}}
    rec = Recorder({"POST scripts/syntax-check": lambda r: httpx.Response(400, json=problem)})
    result = await _call(monkeypatch, rec, "immybot_scripts_validate", {"content": "x"})
    assert "Name: The Name field is required." in result["error"]["message"]


# ---- status / computers ----------------------------------------------------


async def test_status(monkeypatch):
    rec = Recorder({"auth": {"displayName": "Api App", "tenantName": "Example MSP", "isAdmin": True, "currentReleaseVersion": {"release": "0.70.1"}}})
    result = await _call(monkeypatch, rec, "immybot_status", {})
    assert result["connected"] is True and result["instance"] == "https://examplemsp.immy.bot"
    assert result["version"] == "0.70.1" and result["user"] == "Api App"


async def test_computers_list_paging_and_filters(monkeypatch):
    rows = [
        {"id": 1, "computerName": "PC1", "tenantId": 4, "isOnline": True, "operatingSystem": "Microsoft Windows 11 Pro", "activeSessionStatus": 1},
        {"id": 2, "computerName": "MAC1", "tenantId": 4, "isOnline": False, "operatingSystem": "macOS 15"},
        {"id": 3, "computerName": "PC9", "tenantId": 5, "isOnline": True, "operatingSystem": "Windows 10"},
    ]
    rec = Recorder({"computers/paged": {"count": 120, "results": rows}})
    result = await _call(monkeypatch, rec, "immybot_computers_list", {"tenantId": 4, "operatingSystem": "Windows", "limit": 10})
    params = rec.requests[0].url.params
    assert (params["tenantId"], params["take"], params["skip"], params["includeOffline"]) == ("4", "10", "0", "true")
    assert [c["id"] for c in result["computers"]] == [1]
    assert result["computers"][0]["activeSessionStatus"] == "Running"
    assert result["total"] == 120 and result["has_more"] is True and result["next_skip"] == 10


async def test_computers_list_online_only(monkeypatch):
    rec = Recorder({"computers/paged": {"count": 1, "results": []}})
    await _call(monkeypatch, rec, "immybot_computers_list", {"isOnline": True})
    assert rec.requests[0].url.params["includeOffline"] == "false"


async def test_computers_get_drops_inventory(monkeypatch):
    rec = Recorder({"computers/7": {"id": 7, "computerName": "PC7", "inventory": {"big": "blob"}}})
    result = await _call(monkeypatch, rec, "immybot_computers_get", {"computerId": 7})
    assert result == {"id": 7, "computerName": "PC7"}
    assert rec.requests[0].url.params["includePrimaryPerson"] == "true"


async def test_computers_search_and_inventory(monkeypatch):
    rec = Recorder(
        {
            "computers": [{"id": 7, "name": "PC7", "tenantId": 4}, {"id": 8, "name": "PC77", "tenantId": 5}],
            "computers/7": {"id": 7, "computerName": "PC7", "inventory": {"WindowsSystemInfo": {"Model": "X1"}}},
            "computers/7/detected-computer-software": [{"softwareName": "7-Zip", "version": "24.08", "uninstallString": "x"}],
        }
    )
    found = await _call(monkeypatch, rec, "immybot_computers_search", {"query": "PC7", "tenantId": 4})
    assert rec.calls("computers")[0].url.params["name"] == "PC7"
    assert [c["id"] for c in found["computers"]] == [7]
    inventory = await _call(monkeypatch, rec, "immybot_computers_inventory", {"computerId": 7})
    assert inventory["inventory"] == {"WindowsSystemInfo": {"Model": "X1"}}
    assert inventory["software"] == [{"softwareName": "7-Zip", "version": "24.08"}]


async def test_reinventory(monkeypatch):
    rec = Recorder({"POST computers/7/reinventory": {"success": True}})
    result = await _call(monkeypatch, rec, "immybot_computers_trigger_checkin", {"computerId": 7})
    assert result["done"] is True and rec.calls("computers/7/reinventory", "POST")


async def test_set_needs_onboarding(monkeypatch):
    rec = Recorder({"POST computers/7/set-to-needs-onboarding": {"success": True}})
    result = await _call(monkeypatch, rec, "immybot_computers_set_needs_onboarding", {"computerId": 7})
    assert result["done"] is True and rec.calls("computers/7/set-to-needs-onboarding", "POST")


async def test_set_needs_onboarding_invalid_computer(monkeypatch):
    # PRD-21589 TC2/AC2 drafted this against a 404 ("unknown computer"), expecting
    # code=invalid_argument. The connector's existing, shared status map (classify_status,
    # api_client.py) maps 404 -> not_found, not invalid_argument -- proven generically by
    # test_tools.py::test_error_envelope and used identically by every other tool (e.g.
    # test_web_app_page_is_not_found above). This tool adds no custom error handling, so it
    # inherits that mapping unchanged; changing it would be out of scope (it would change the
    # contract of the other 68 tools too). 400 is used here instead so the test still proves
    # AC2's literal claim (structured envelope, code=invalid_argument, retryable=false, no
    # exception escapes) without asserting a mapping this connector doesn't have. Flagged in
    # Self-test for PRD-21589 as a drafting assumption worth a look in a future design round.
    rec = Recorder({"POST computers/999/set-to-needs-onboarding": lambda r: httpx.Response(400, json={"message": "Computer not found"})})
    result = await _call(monkeypatch, rec, "immybot_computers_set_needs_onboarding", {"computerId": 999})
    assert result["error"]["code"] == "invalid_argument"
    assert result["error"]["retryable"] is False


# ---- deployments -----------------------------------------------------------

ASSIGNMENTS = [
    {"id": 1, "maintenanceIdentifier": "12", "maintenanceType": "GlobalSoftware", "target": "7", "targetType": "Computer", "desiredSoftwareState": 5},
    {"id": 2, "maintenanceIdentifier": "12", "maintenanceType": "GlobalSoftware", "tenantId": 4, "targetType": "AllForTenant", "desiredSoftwareState": "NotPresent"},
    {"id": 3, "maintenanceIdentifier": "12", "maintenanceType": "LocalMaintenanceTask", "tenantId": 4, "taskParameterValues": {"ApiKey": "k-123", "Site": "HQ"}},
]


async def test_deployments_list_filters(monkeypatch):
    rec = Recorder({"target-assignments": ASSIGNMENTS})
    by_software = await _call(monkeypatch, rec, "immybot_deployments_list", {"softwareId": 12})
    assert [d["id"] for d in by_software["deployments"]] == [1, 2]
    installed = await _call(monkeypatch, rec, "immybot_deployments_list", {"softwareId": 12, "desiredState": "Installed"})
    assert [d["id"] for d in installed["deployments"]] == [1]
    assert installed["deployments"][0]["desiredSoftwareState"] == "LatestVersion"
    tenant = await _call(monkeypatch, rec, "immybot_deployments_list", {"targetType": "Tenant", "targetId": 4})
    assert [d["id"] for d in tenant["deployments"]] == [2, 3]
    assert rec.requests[0].url.params["PageSize"] == "1000"


async def test_deployment_secrets_are_masked(monkeypatch):
    rec = Recorder({"target-assignments/3": ASSIGNMENTS[2]})
    result = await _call(monkeypatch, rec, "immybot_deployments_get", {"deploymentId": 3})
    assert result["taskParameterValues"] == {"ApiKey": "********", "Site": "HQ"}


async def test_deployment_create_payload_and_notes(monkeypatch):
    rec = Recorder({"POST target-assignments": {"id": 50}})
    args = {"name": "Chrome", "softwareId": 12, "targetType": "Tenant", "targetId": 4, "desiredState": "Installed", "autoUpdate": True}
    await _call(monkeypatch, rec, "immybot_deployments_create", args)
    payload = body(rec.calls("target-assignments", "POST")[0])
    assert payload["maintenanceIdentifier"] == "12" and payload["maintenanceType"] == "GlobalSoftware"
    assert payload["targetType"] == "AllForTenant" and payload["tenantId"] == 4
    assert payload["desiredSoftwareState"] == "LatestVersion"
    assert body(rec.calls("target-assignments/50/notes", "POST")[0]) == {"notes": "Chrome"}


async def test_deployment_trigger_needs_confirm_and_runs_its_target(monkeypatch):
    rec = Recorder({"target-assignments/1": ASSIGNMENTS[0] | {"databaseType": "Local"}, "POST run-immy-service": {"sessionsStarted": [{"sessionId": 900, "computerId": 7}]}})
    preview = await _call(monkeypatch, rec, "immybot_deployments_trigger", {"deploymentId": 1})
    assert preview["done"] is False and not rec.calls("run-immy-service")
    result = await _call(monkeypatch, rec, "immybot_deployments_trigger", {"deploymentId": 1, "confirm": True})
    sent = body(rec.calls("run-immy-service", "POST")[0])
    assert sent["computers"] == [{"computerId": 7}] and sent["deploymentId"] == 1
    assert sent["maintenanceParams"]["maintenanceIdentifier"] == "12"
    assert result["sessions_started"] == [{"sessionId": 900, "computerId": 7}]


async def test_deployment_compliance_counts_latest_result_per_computer(monkeypatch):
    rows = [
        {"computerId": 7, "computerName": "PC7", "result": 2, "resultReasonMessage": "timeout", "createdDateUTC": "2026-10-02"},
        {"computerId": 7, "result": 1, "createdDateUTC": "2026-10-01"},
        {"computerId": 8, "result": "Success"},
    ]
    rec = Recorder({"maintenance-actions/dx": {"data": rows}})
    result = await _call(monkeypatch, rec, "immybot_deployments_compliance", {"deploymentId": 1})
    assert json.loads(rec.requests[0].url.params["filter"]) == ["assignmentId", "=", 1]
    assert result["computers"] == 2 and result["results"] == {"Failed": 1, "Success": 1}
    assert result["not_compliant"][0]["reason"] == "timeout"


async def test_deployments_for_computer_uses_latest_actions(monkeypatch):
    rec = Recorder({"maintenance-actions/latest-for-computer/7": [{"maintenanceDisplayName": "Chrome", "result": 1}]})
    result = await _call(monkeypatch, rec, "immybot_deployments_for_computer", {"computerId": 7})
    assert result["items"] == [{"maintenanceDisplayName": "Chrome", "result": "Success"}]


# ---- maintenance sessions --------------------------------------------------


async def test_sessions_list_dx_query(monkeypatch):
    rec = Recorder({"maintenance-sessions/dx": {"data": [{"id": 5, "sessionStatus": 2, "computerName": "PC7", "sessionJobArgs": {"x": 1}}]}})
    args = {"computerId": 7, "status": "Failed", "startDate": "2026-10-01", "limit": 20, "sessionType": "Scheduled"}
    result = await _call(monkeypatch, rec, "immybot_maintenance_sessions_list", args)
    params = rec.requests[0].url.params
    assert (params["take"], params["computerId"], params["scheduledFilter"], params["requireTotalCount"]) == ("20", "7", "true", "false")
    assert json.loads(params["filter"]) == [["sessionStatus", "=", 2], "and", ["createdDate", ">=", "10/01/2026 00:00:00"]]
    assert json.loads(params["sort"]) == [{"selector": "createdDate", "desc": True}]
    assert result["sessions"] == [{"id": 5, "computerName": "PC7", "sessionStatus": "Failed"}]


async def test_sessions_bad_date_is_invalid(monkeypatch):
    result = await _call(monkeypatch, Recorder(), "immybot_maintenance_sessions_list", {"startDate": "yesterday"})
    assert result["error"]["code"] == "invalid_argument"


async def test_session_get_drops_job_args(monkeypatch):
    record = {"id": 5, "sessionStatus": 0, "sessionJobArgs": {"secret": "x"}, "logs": [1], "maintenanceActions": [{"result": 1}]}
    rec = Recorder({"maintenance-sessions/5": record})
    result = await _call(monkeypatch, rec, "immybot_maintenance_sessions_get", {"sessionId": 5})
    assert result == {"id": 5, "sessionStatus": "Passed", "maintenanceActions": [{"result": "Success"}]}


async def test_session_start_needs_confirm(monkeypatch):
    rec = Recorder({"POST run-immy-service": {"sessionsStarted": [{"sessionId": 1}]}})
    preview = await _call(monkeypatch, rec, "immybot_maintenance_sessions_start", {"computerId": 7, "allowReboot": False})
    assert preview["done"] is False and rec.requests == []
    await _call(monkeypatch, rec, "immybot_maintenance_sessions_start", {"computerId": 7, "allowReboot": False, "confirm": True})
    sent = body(rec.requests[0])
    assert sent["computers"] == [{"computerId": 7}] and sent["fullMaintenance"] is True
    assert sent["rebootPreference"] == "Suppress" and "tenants" not in sent


async def test_session_start_needs_a_target(monkeypatch):
    result = await _call(monkeypatch, Recorder(), "immybot_maintenance_sessions_start", {"confirm": True})
    assert result["error"]["code"] == "invalid_argument"


async def test_session_cancel_resume(monkeypatch):
    rec = Recorder()
    await _call(monkeypatch, rec, "immybot_maintenance_sessions_cancel", {"sessionId": 5})
    await _call(monkeypatch, rec, "immybot_maintenance_sessions_resume", {"sessionId": 5})
    assert body(rec.calls("maintenance-sessions/cancel", "POST")[0]) == {"sessionIds": [5]}
    assert rec.calls("maintenance-sessions/5/resume", "POST")


async def test_session_logs_and_results(monkeypatch):
    logs = [{"time": "t1", "message": "a", "script": "secret body", "scriptParameters": {"Password": "x"}}, {"time": "t2", "message": "b"}]
    actions = [{"id": 1, "maintenanceDisplayName": "Chrome", "result": 1, "actionType": 1}, {"id": 2, "result": 2}]
    rec = Recorder({"maintenance-sessions/5/logs": logs, "maintenance-actions/dx": {"data": actions}})
    log_result = await _call(monkeypatch, rec, "immybot_maintenance_sessions_logs", {"sessionId": 5, "limit": 1})
    assert log_result["lines"] == [{"time": "t2", "message": "b"}] and log_result["total"] == 2
    assert "secret body" not in json.dumps(await _call(monkeypatch, rec, "immybot_maintenance_sessions_logs", {"sessionId": 5}))
    results = await _call(monkeypatch, rec, "immybot_maintenance_sessions_results", {"sessionId": 5})
    assert results["results"] == {"Success": 1, "Failed": 1}
    assert results["actions"][0]["actionType"] == "Install"


async def test_sessions_active_and_summary(monkeypatch):
    rec = Recorder({"maintenance-sessions/dx": {"data": [{"id": 1, "sessionStatus": 1}]}, "maintenance-sessions/status-counts": {"counts": {"0": 10, "2": 3}, "total": 13}})
    active = await _call(monkeypatch, rec, "immybot_maintenance_sessions_active", {})
    assert json.loads(rec.requests[0].url.params["filter"]) == ["sessionStatus", "=", 1]
    assert active["count"] == 1
    summary = await _call(monkeypatch, rec, "immybot_maintenance_sessions_summary", {})
    assert summary == {"scope": "instance", "counts": {"Passed": 10, "Failed": 3}, "total": 13}
    filtered = await _call(monkeypatch, rec, "immybot_maintenance_sessions_summary", {"tenantId": 4})
    assert filtered["counts"] == {"Running": 1} and filtered["tenant_id"] == 4


# ---- scripts ---------------------------------------------------------------

SCRIPT = {
    "id": 31, "name": "Clear temp", "action": "Remove-Item $env:TEMP\\* -Recurse", "databaseType": "Local", "filterScriptMode": "Legacy",
    "outputType": "Object", "scriptCategory": "MaintenanceTaskSetter", "scriptLanguage": "PowerShell", "scriptExecutionContext": "System",
}


async def test_scripts_list_uses_sieve_and_filters(monkeypatch):
    rows = [{"id": 1, "name": "A", "scriptCategory": 0, "scriptLanguage": 1}, {"id": 2, "name": "B", "scriptCategory": 2, "scriptLanguage": 1}]
    rec = Recorder({"scripts/search": rows})
    result = await _call(monkeypatch, rec, "immybot_scripts_list", {"search": "temp, old", "isGlobal": False, "category": "SoftwareDetection"})
    params = rec.requests[0].url.params
    assert params["Filters"] == "name@=*temp\\, old" and params["localOnly"] == "true" and "globalOnly" not in params
    assert result["scripts"] == [{"id": 1, "name": "A", "scriptCategory": "SoftwareDetection", "scriptLanguage": "PowerShell"}]


async def test_script_get_falls_back_to_global(monkeypatch):
    rec = Recorder({"scripts/local/31": lambda r: httpx.Response(404, json={}), "scripts/global/31": SCRIPT | {"databaseType": None}})
    result = await _call(monkeypatch, rec, "immybot_scripts_get", {"scriptId": 31})
    assert result["databaseType"] == "Global"
    assert [r.url.path for r in rec.requests] == ["/api/v1/scripts/local/31", "/api/v1/scripts/global/31"]


async def test_script_run_needs_confirm_and_replays_script(monkeypatch):
    rec = Recorder({"scripts/local/31": SCRIPT, "POST scripts/run": lambda r: httpx.Response(200, text="removed 12 files")})
    preview = await _call(monkeypatch, rec, "immybot_scripts_run", {"scriptId": 31, "computerId": 7})
    assert preview["done"] is False and not rec.calls("scripts/run")
    assert SCRIPT["action"] not in json.dumps(preview)
    result = await _call(
        monkeypatch, rec, "immybot_scripts_run", {"scriptId": 31, "computerId": 7, "parameters": {"Days": 3}, "runAs": "User", "confirm": True}
    )
    sent = body(rec.calls("scripts/run", "POST")[0])
    assert sent["computerId"] == 7
    assert "script" not in sent
    assert sent["body"]["action"] == SCRIPT["action"] and sent["body"]["parameterOverrides"] == {"Days": 3}
    assert sent["body"]["scriptExecutionContext"] == "CurrentUser" and sent["body"]["variables"] == {}
    assert uuid.UUID(sent["cancellationId"]) and sent["cancellationId"] != "mcp-31-7"
    assert result["output"] == {"output": "removed 12 files"}
    assert SCRIPT["action"] not in json.dumps(result)


async def test_script_run_executes_global_script(monkeypatch):
    rec = Recorder(
        {
            "scripts/local/31": lambda r: httpx.Response(404, json={}),
            "scripts/global/31": SCRIPT | {"databaseType": None},
            "POST scripts/run": lambda r: httpx.Response(200, text="removed 12 files"),
        }
    )
    result = await _call(monkeypatch, rec, "immybot_scripts_run", {"scriptId": 31, "computerId": 7, "databaseType": "Global", "confirm": True})
    sent = body(rec.calls("scripts/run", "POST")[0])
    assert sent["body"]["databaseType"] == "Global"
    assert uuid.UUID(sent["cancellationId"])
    assert result["done"] is True


async def test_script_run_cancellation_id_is_unique_per_call(monkeypatch):
    rec = Recorder({"scripts/local/31": SCRIPT, "POST scripts/run": lambda r: httpx.Response(200, text="ok")})
    await _call(monkeypatch, rec, "immybot_scripts_run", {"scriptId": 31, "computerId": 7, "confirm": True})
    await _call(monkeypatch, rec, "immybot_scripts_run", {"scriptId": 31, "computerId": 7, "confirm": True})
    calls = rec.calls("scripts/run", "POST")
    first, second = body(calls[0])["cancellationId"], body(calls[1])["cancellationId"]
    assert uuid.UUID(first) and uuid.UUID(second) and first != second


async def test_script_validate(monkeypatch):
    rec = Recorder({"POST scripts/syntax-check": {"isSyntaxValid": False, "errors": [{"message": "Missing }"}]}})
    result = await _call(monkeypatch, rec, "immybot_scripts_validate", {"content": "if ($x) {"})
    assert body(rec.requests[0]) == {"script": "if ($x) {", "scriptLanguage": "PowerShell"}
    assert result["isSyntaxValid"] is False


async def test_script_categories_are_local(monkeypatch):
    result = await _call(monkeypatch, Recorder(), "immybot_scripts_categories", {})
    assert "SoftwareDetection" in result["categories"]


# ---- software --------------------------------------------------------------


async def test_software_lists_and_search(monkeypatch):
    rec = Recorder(
        {
            "software/local": [{"id": 3, "name": "Example Agent", "softwareVersions": [1, 2]}],
            "software/global": [{"id": 12, "name": "Google Chrome"}, {"id": 13, "name": "7-Zip"}],
        }
    )
    both = await _call(monkeypatch, rec, "immybot_software_list", {})
    assert [(s["id"], s["databaseType"]) for s in both["software"]] == [(3, "Local"), (12, "Global"), (13, "Global")]
    assert "softwareVersions" not in both["software"][0]
    found = await _call(monkeypatch, rec, "immybot_software_search", {"query": "chrome"})
    assert [s["id"] for s in found["software"]] == [12]
    glob = await _call(monkeypatch, rec, "immybot_software_list_global", {"limit": 1})
    assert glob["count"] == 1 and glob["has_more"] is True


async def test_software_versions_latest_and_stats(monkeypatch):
    versions = [
        {"semanticVersionString": "1.0.0", "numActionSuccesses": 8, "numActionFailures": 2, "packageHash": "x"},
        {"semanticVersionString": "1.1.0", "numActionSuccesses": 10, "numActionFailures": 0},
    ]
    rec = Recorder({"software/global/12/versions": versions, "software/global/12/latest": versions[1]})
    listed = await _call(monkeypatch, rec, "immybot_software_versions", {"softwareId": 12, "softwareType": "Global"})
    assert listed["count"] == 2 and "packageHash" not in listed["versions"][0]
    latest = await _call(monkeypatch, rec, "immybot_software_latest_version", {"softwareId": 12, "softwareType": "Global"})
    assert latest["semanticVersionString"] == "1.1.0"
    stats = await _call(monkeypatch, rec, "immybot_software_stats", {"softwareId": 12, "softwareType": "Global"})
    assert (stats["action_successes"], stats["action_failures"], stats["success_rate"]) == (18, 2, 0.9)


async def test_software_install_needs_confirm(monkeypatch):
    rec = Recorder({"POST run-immy-service": {"sessionsStarted": [{"sessionId": 3}]}})
    preview = await _call(monkeypatch, rec, "immybot_software_install", {"softwareId": 12, "computerIds": [7, 8]})
    assert preview["done"] is False and rec.requests == []
    await _call(monkeypatch, rec, "immybot_software_install", {"softwareId": 12, "computerIds": [7, 8], "confirm": True})
    sent = body(rec.requests[0])
    assert sent["computers"] == [{"computerId": 7}, {"computerId": 8}]
    assert sent["maintenanceParams"] == {"maintenanceIdentifier": "12", "maintenanceType": "GlobalSoftware", "desiredSoftwareState": "LatestVersion", "repair": False}
    assert sent["rebootPreference"] == "Suppress" and sent["useWinningDeployment"] is False


# ---- tenants ---------------------------------------------------------------


async def test_tenants_list_and_search(monkeypatch):
    rec = Recorder({"tenants": [{"id": 4, "name": "Example Co", "active": True, "azureTenantLink": {"x": 1}}, {"id": 5, "name": "Old Co", "active": False}]})
    active = await _call(monkeypatch, rec, "immybot_tenants_list", {"status": "Active"})
    assert active["tenants"] == [{"id": 4, "name": "Example Co", "active": True}]
    await _call(monkeypatch, rec, "immybot_tenants_search", {"query": "Example"})
    assert rec.requests[-1].url.params["Filters"] == "name@=*Example"


async def test_tenant_stats(monkeypatch):
    rec = Recorder(
        {
            "tenants/computer-counts": [{"tenantId": 4, "computerCount": 3}, {"tenantId": 5, "computerCount": 9}],
            "computers/paged": {"count": 3, "results": [{"tenantId": 4, "isOnline": True}, {"tenantId": 4, "isOnline": False, "hasPendingReboot": True}]},
            "target-assignments": ASSIGNMENTS,
            "maintenance-actions/latest-non-compliant-actions-for-tenant/4": [{"computerId": 1}],
        }
    )
    result = await _call(monkeypatch, rec, "immybot_tenants_stats", {"tenantId": 4})
    assert result == {"tenant_id": 4, "computers": 3, "online": 1, "offline": 1, "pending_reboot": 1, "deployments": 2, "non_compliant_items": 1}


async def test_tenant_compliance_and_inventory(monkeypatch):
    rec = Recorder(
        {
            "maintenance-actions/latest-non-compliant-actions-for-tenant/4": [
                {"computerId": 1, "maintenanceDisplayName": "Chrome", "result": 2},
                {"computerId": 2, "maintenanceDisplayName": "Chrome", "result": 0},
            ],
            "tenants/software-from-inventory/4": [
                {"computerId": 1, "displayName": "7-Zip", "globalSoftwareVersion": "24.08"},
                {"computerId": 2, "displayName": "7-Zip", "globalSoftwareVersion": "24.08"},
                {"computerId": 2, "displayName": "Notepad++"},
            ],
        }
    )
    compliance = await _call(monkeypatch, rec, "immybot_tenants_compliance", {"tenantId": 4})
    assert compliance["non_compliant"] == 2 and compliance["computers_affected"] == 2
    assert compliance["by_result"] == {"Failed": 1, "Pending": 1}
    inventory = await _call(monkeypatch, rec, "immybot_tenants_software_inventory", {"tenantId": 4})
    assert inventory["software"][0] == {"name": "7-Zip", "version": "24.08", "computers": 2}
    assert inventory["distinct"] == 2 and inventory["detections"] == 3


async def test_tenant_computers_enforces_tenant(monkeypatch):
    rec = Recorder({"computers/paged": {"results": [{"id": 1, "tenantId": 4}, {"id": 2, "tenantId": 6}]}})
    result = await _call(monkeypatch, rec, "immybot_tenants_computers", {"tenantId": 4})
    assert [c["id"] for c in result["computers"]] == [1]


@pytest.mark.parametrize("given,sent", [("powershell", "PowerShell"), ("COMMANDLINE", "CommandLine"), ("Python", "Python")])
async def test_script_validate_language_normalized_or_passed_through(monkeypatch, given, sent):
    rec = Recorder({"POST scripts/syntax-check": {"isSyntaxValid": True}})
    await _call(monkeypatch, rec, "immybot_scripts_validate", {"content": "x", "language": given})
    assert body(rec.requests[0])["scriptLanguage"] == sent
