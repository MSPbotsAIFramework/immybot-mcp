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
"""tools/list snapshot, annotations and error-envelope mapping. No network access."""

import asyncio
import json

import pytest

from immybot_mcp.api_client import ImmyBotError
from immybot_mcp.server import INSTRUCTIONS, create_mcp_server
from immybot_mcp.tools.navigation import DOMAINS

C, S, T = {"computerId"}, {"sessionId"}, {"tenantId"}
SW, TASK = {"softwareId"}, {"taskId"}

# Tool names are a public contract: existing agents and tenant connections
# depend on them. Changing this snapshot is a breaking change.
EXPECTED_TOOLS: dict[str, set[str]] = {
    "immybot_navigate": {"domain"},
    "immybot_back": set(),
    "immybot_status": set(),
    "immybot_computers_list": set(),
    "immybot_computers_get": C,
    "immybot_computers_search": {"query"},
    "immybot_computers_inventory": C,
    "immybot_computers_create": {"name", "tenantId"},
    "immybot_computers_deployments": C,
    "immybot_computers_trigger_checkin": C,
    "immybot_computers_set_needs_onboarding": C,
    "immybot_computers_delete": {"computerIds"},
    "immybot_deployments_list": set(),
    "immybot_deployments_get": {"deploymentId"},
    "immybot_deployments_create": {"name", "softwareId", "targetType", "targetId", "desiredState"},
    "immybot_deployments_trigger": {"deploymentId"},
    "immybot_deployments_compliance": {"deploymentId"},
    "immybot_deployments_for_computer": C,
    "immybot_deployments_for_software": SW,
    "immybot_maintenance_sessions_list": set(),
    "immybot_maintenance_sessions_get": S,
    "immybot_maintenance_sessions_start": set(),
    "immybot_maintenance_sessions_cancel": S,
    "immybot_maintenance_sessions_pause": S,
    "immybot_maintenance_sessions_resume": S,
    "immybot_maintenance_sessions_logs": S,
    "immybot_maintenance_sessions_results": S,
    "immybot_maintenance_sessions_active": set(),
    "immybot_maintenance_sessions_summary": set(),
    "immybot_scripts_list": set(),
    "immybot_scripts_get": {"scriptId"},
    "immybot_scripts_search": {"query"},
    "immybot_scripts_run": {"scriptId", "computerId"},
    "immybot_scripts_run_adhoc": {"computerId", "content"},
    "immybot_scripts_categories": set(),
    "immybot_scripts_execution_history": C,
    "immybot_scripts_execution_result": {"scriptId", "executionId"},
    "immybot_scripts_validate": {"content"},
    "immybot_software_list_global": set(),
    "immybot_software_list": set(),
    "immybot_software_get": SW,
    "immybot_software_search": {"query"},
    "immybot_software_versions": SW,
    "immybot_software_latest_version": SW,
    "immybot_software_categories": set(),
    "immybot_software_publishers": set(),
    "immybot_software_install": SW,
    "immybot_software_stats": SW,
    "immybot_tasks_list": set(),
    "immybot_tasks_get": TASK,
    "immybot_tasks_running": set(),
    "immybot_tasks_queued": set(),
    "immybot_tasks_failed": set(),
    "immybot_tasks_for_computer": C,
    "immybot_tasks_for_tenant": T,
    "immybot_tasks_by_type": {"taskType"},
    "immybot_tasks_queue_stats": set(),
    "immybot_tasks_history": set(),
    "immybot_tasks_dependencies": TASK,
    "immybot_tasks_child_tasks": {"parentTaskId"},
    "immybot_tasks_logs": TASK,
    "immybot_tasks_metrics": TASK,
    "immybot_tasks_estimated_completion": TASK,
    "immybot_tenants_list": set(),
    "immybot_tenants_get": T,
    "immybot_tenants_search": {"query"},
    "immybot_tenants_stats": T,
    "immybot_tenants_computers": T,
    "immybot_tenants_deployments": T,
    "immybot_tenants_compliance": T,
    "immybot_tenants_software_inventory": T,
}
WRITE_TOOLS = {
    "immybot_computers_trigger_checkin",
    "immybot_computers_set_needs_onboarding",
    "immybot_deployments_create",
    "immybot_maintenance_sessions_cancel",
    "immybot_maintenance_sessions_resume",
}
CONFIRM_TOOLS = {
    "immybot_computers_delete",
    "immybot_deployments_trigger",
    "immybot_maintenance_sessions_start",
    "immybot_scripts_run",
    "immybot_scripts_run_adhoc",
    "immybot_software_install",
}
UNSUPPORTED_TOOLS = {n for n in EXPECTED_TOOLS if n.startswith("immybot_tasks_")} | {
    "immybot_computers_create",
    "immybot_maintenance_sessions_pause",
    "immybot_scripts_execution_history",
    "immybot_scripts_execution_result",
    "immybot_software_categories",
    "immybot_software_publishers",
}
LOCAL_TOOLS = UNSUPPORTED_TOOLS | {"immybot_navigate", "immybot_back", "immybot_scripts_categories"}


@pytest.fixture(scope="module")
def tools():
    return {t.name: t for t in asyncio.run(create_mcp_server().list_tools())}


def test_tool_names_are_stable(tools):
    assert set(tools) == set(EXPECTED_TOOLS)
    assert len(tools) == 71


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_required_params(tools, name):
    assert set(tools[name].inputSchema.get("required", [])) == EXPECTED_TOOLS[name]


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_description_budget(tools, name):
    description = (tools[name].description or "").strip()
    assert description, f"{name} has no description"
    assert len(description) <= 500
    assert len(description.splitlines()[0]) <= 100


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_annotations_match_side_effects(tools, name):
    annotations = tools[name].annotations
    assert annotations is not None
    writes = name in WRITE_TOOLS | CONFIRM_TOOLS
    assert annotations.readOnlyHint is not writes
    assert bool(annotations.destructiveHint) is (name in CONFIRM_TOOLS)
    assert (annotations.openWorldHint is False) is (name in LOCAL_TOOLS)


@pytest.mark.parametrize("name", sorted(WRITE_TOOLS | CONFIRM_TOOLS))
def test_write_tools_say_when_to_use_them(tools, name):
    assert "explicitly ask" in tools[name].description


@pytest.mark.parametrize("name", sorted(CONFIRM_TOOLS))
def test_endpoint_changing_tools_take_confirm(tools, name):
    assert "confirm" in tools[name].inputSchema["properties"]


@pytest.mark.parametrize("name", sorted(UNSUPPORTED_TOOLS))
def test_unsupported_tools_say_so(tools, name):
    assert tools[name].description.startswith("Not available")


@pytest.mark.parametrize("name", sorted(UNSUPPORTED_TOOLS))
def test_unsupported_tools_return_invalid_argument(name, tools):
    args = {p: 1 for p in EXPECTED_TOOLS[name]}
    for p in EXPECTED_TOOLS[name]:
        if tools[name].inputSchema["properties"][p].get("type") == "string":
            args[p] = "x"
    content, _ = asyncio.run(create_mcp_server().call_tool(name, args))
    error = json.loads(content[0].text)["error"]
    assert error["code"] == "invalid_argument" and "immybot_" in error["message"]


def test_navigate_lists_every_tool():
    listed = {tool for _, names in DOMAINS.values() for tool in names}
    assert listed | {"immybot_navigate", "immybot_back", "immybot_status"} == set(EXPECTED_TOOLS)


def test_paging_tool_limit_capped_at_200(tools):
    limit = tools["immybot_computers_list"].inputSchema["properties"]["limit"]
    assert limit["maximum"] == 200
    assert limit["default"] == 50
    assert tools["immybot_scripts_list"].inputSchema["properties"]["limit"]["maximum"] == 500


def test_instructions_budget():
    assert len(INSTRUCTIONS) <= 1500


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (404, "not_found", False),
        (400, "invalid_argument", False),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (0, "upstream_error", True),
    ],
)
def test_error_envelope(status, code, retryable):
    envelope = json.loads(ImmyBotError(status, "boom").to_envelope())
    assert envelope == {"error": {"code": code, "message": "boom", "retryable": retryable}}


def test_tool_without_credentials_returns_not_configured():
    content, _ = asyncio.run(create_mcp_server().call_tool("immybot_computers_list", {}))
    assert json.loads(content[0].text)["error"]["code"] == "not_configured"
