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
"""Tool discovery (kept for compatibility: every tool is always listed) and the connection check."""

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .._json import compact as to_json
from ..api_client import ImmyBotClient
from ._common import LOCAL, READ_ONLY, ClientFactory, run_tool

DOMAINS: dict[str, tuple[str, list[str]]] = {
    "computers": (
        "Managed computers: find, inspect, inventory, effective deployments, re-inventory.",
        [
            "immybot_computers_list",
            "immybot_computers_get",
            "immybot_computers_search",
            "immybot_computers_inventory",
            "immybot_computers_create",
            "immybot_computers_deployments",
            "immybot_computers_trigger_checkin",
        ],
    ),
    "software": (
        "Global and local software catalog, versions, install.",
        [
            "immybot_software_list_global",
            "immybot_software_list",
            "immybot_software_get",
            "immybot_software_search",
            "immybot_software_versions",
            "immybot_software_latest_version",
            "immybot_software_categories",
            "immybot_software_publishers",
            "immybot_software_install",
            "immybot_software_stats",
        ],
    ),
    "deployments": (
        "Deployments (target assignments): which item in which state on which targets.",
        [
            "immybot_deployments_list",
            "immybot_deployments_get",
            "immybot_deployments_create",
            "immybot_deployments_trigger",
            "immybot_deployments_compliance",
            "immybot_deployments_for_computer",
            "immybot_deployments_for_software",
        ],
    ),
    "scripts": (
        "Global and local scripts: browse, run on a computer, syntax check.",
        [
            "immybot_scripts_list",
            "immybot_scripts_get",
            "immybot_scripts_search",
            "immybot_scripts_run",
            "immybot_scripts_categories",
            "immybot_scripts_execution_history",
            "immybot_scripts_execution_result",
            "immybot_scripts_validate",
        ],
    ),
    "tenants": (
        "Tenants (clients): list, stats, computers, deployments, compliance, software inventory.",
        [
            "immybot_tenants_list",
            "immybot_tenants_get",
            "immybot_tenants_search",
            "immybot_tenants_stats",
            "immybot_tenants_computers",
            "immybot_tenants_deployments",
            "immybot_tenants_compliance",
            "immybot_tenants_software_inventory",
        ],
    ),
    "maintenance_sessions": (
        "Maintenance sessions: list, start, cancel, resume, logs, per-item results, status counts.",
        [
            "immybot_maintenance_sessions_list",
            "immybot_maintenance_sessions_get",
            "immybot_maintenance_sessions_start",
            "immybot_maintenance_sessions_cancel",
            "immybot_maintenance_sessions_pause",
            "immybot_maintenance_sessions_resume",
            "immybot_maintenance_sessions_logs",
            "immybot_maintenance_sessions_results",
            "immybot_maintenance_sessions_active",
            "immybot_maintenance_sessions_summary",
        ],
    ),
    "tasks": (
        "No ImmyBot API exists for a task queue; these tools return an error naming the maintenance session tool to use.",
        [
            "immybot_tasks_list",
            "immybot_tasks_get",
            "immybot_tasks_running",
            "immybot_tasks_queued",
            "immybot_tasks_failed",
            "immybot_tasks_for_computer",
            "immybot_tasks_for_tenant",
            "immybot_tasks_by_type",
            "immybot_tasks_queue_stats",
            "immybot_tasks_history",
            "immybot_tasks_dependencies",
            "immybot_tasks_child_tasks",
            "immybot_tasks_logs",
            "immybot_tasks_metrics",
            "immybot_tasks_estimated_completion",
        ],
    ),
}

Domain = Literal["computers", "software", "deployments", "scripts", "tenants", "maintenance_sessions", "tasks"]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=LOCAL)
    async def immybot_navigate(domain: Annotated[Domain, Field(description="Area to describe.")]) -> str:
        """Describe the tools of one ImmyBot area. All tools are already callable; this changes nothing."""
        summary, tools = DOMAINS[domain]
        return to_json({"domain": domain, "summary": summary, "tools": tools})

    @mcp.tool(annotations=LOCAL)
    async def immybot_back() -> str:
        """Kept for compatibility: there is no navigation state, every tool is always available."""
        return to_json({"domains": list(DOMAINS), "message": "All tools are listed; call any of them directly."})

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_status() -> str:
        """Check the ImmyBot connection: instance, signed-in identity, version and plan status."""

        async def action(client: ImmyBotClient) -> dict:
            auth = await client.get("auth")
            auth = auth if isinstance(auth, dict) else {}
            version = auth.get("currentReleaseVersion")
            return {
                "connected": True,
                "instance": client.instance_url,
                "user": auth.get("displayName"),
                "tenant": auth.get("tenantName"),
                "is_admin": auth.get("isAdmin"),
                "version": version.get("release") if isinstance(version, dict) else version,
                "subscription_status": auth.get("status"),
                "domains": list(DOMAINS),
            }

        return await run_tool("immybot_status", client_factory, action)
