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
"""Tenants: the MSP's clients in ImmyBot."""

from collections import Counter
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import ImmyBotClient
from ._common import (
    ACTION_RESULT,
    DEFAULT,
    READ_ONLY,
    ClientFactory,
    Limit,
    TenantId,
    as_list,
    compact,
    enum_name,
    listing,
    names,
    run_tool,
    sieve_params,
)
from .deployments import all_assignments, assignments_view

_TENANT_FIELDS = ("id", "name", "slug", "active", "isMsp", "parentTenantId", "ownerTenantId", "tenantTagNames", "createdDateUTC", "markedForDeletionAtUtc")


def _tenant(row: dict) -> dict:
    return {k: row.get(k) for k in _TENANT_FIELDS if row.get(k) is not None}


async def tenant_computers(client: ImmyBotClient, tenant_id: int, take: int = 500) -> list[dict]:
    payload = await client.get("computers/paged", {"tenantId": tenant_id, "includeOffline": True, "take": take, "skip": 0})
    return [r for r in as_list(payload) if isinstance(r, dict) and r.get("tenantId") == tenant_id]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def immybot_tenants_list(
        search: Annotated[str | None, Field(description="Text the tenant name contains.")] = None,
        status: Annotated[Literal["Active", "Inactive", "Suspended"] | None, Field(description="Inactive and Suspended both mean deactivated.")] = None,
        limit: Limit = DEFAULT,
    ) -> str:
        """List tenants (clients) with id, name, active flag, MSP flag, parent and tags."""

        async def action(client: ImmyBotClient) -> dict:
            rows = [r for r in as_list(await client.get("tenants", sieve_params(500 if status else limit, search))) if isinstance(r, dict)]
            if status:
                rows = [r for r in rows if bool(r.get("active")) is (status == "Active")]
            return listing("tenants", [_tenant(r) for r in rows], limit)

        return await run_tool("immybot_tenants_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_tenants_get(tenantId: TenantId) -> str:
        """Get one tenant: name, slug, active flag, parent, linked Entra tenant and tags."""

        async def action(client: ImmyBotClient) -> Any:
            return await client.get(f"tenants/{tenantId}")

        return await run_tool("immybot_tenants_get", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_tenants_search(query: Annotated[str, Field(description="Text the tenant name contains.", min_length=1)]) -> str:
        """Find tenants by name."""

        async def action(client: ImmyBotClient) -> dict:
            rows = [r for r in as_list(await client.get("tenants", sieve_params(100, query))) if isinstance(r, dict)]
            return listing("tenants", [_tenant(r) for r in rows], 100)

        return await run_tool("immybot_tenants_search", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_tenants_stats(tenantId: TenantId) -> str:
        """Key numbers for a tenant: computers (online / offline), deployments and non-compliant items."""

        async def action(client: ImmyBotClient) -> dict:
            counts = as_list(await client.get("tenants/computer-counts"))
            computer_count = next((c.get("computerCount") for c in counts if isinstance(c, dict) and c.get("tenantId") == tenantId), 0)
            computers = await tenant_computers(client, tenantId)
            deployments = [r for r in await all_assignments(client) if r.get("tenantId") == tenantId]
            non_compliant = as_list(await client.get(f"maintenance-actions/latest-non-compliant-actions-for-tenant/{tenantId}"))
            return {
                "tenant_id": tenantId,
                "computers": computer_count,
                "online": sum(1 for c in computers if c.get("isOnline")),
                "offline": sum(1 for c in computers if c.get("isOnline") is False),
                "pending_reboot": sum(1 for c in computers if c.get("hasPendingReboot")),
                "deployments": len(deployments),
                "non_compliant_items": len(non_compliant),
            }

        return await run_tool("immybot_tenants_stats", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_tenants_computers(
        tenantId: TenantId,
        limit: Annotated[int, Field(description="Maximum computers to return.", ge=1, le=500)] = 50,
    ) -> str:
        """List a tenant's computers with online state, OS, model, primary user and active session."""

        async def action(client: ImmyBotClient) -> dict:
            return listing("computers", await tenant_computers(client, tenantId, limit), limit)

        return await run_tool("immybot_tenants_computers", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_tenants_deployments(tenantId: TenantId) -> str:
        """List the deployments scoped to a tenant (secret task parameter values masked)."""

        async def action(client: ImmyBotClient) -> dict:
            rows = [r for r in await all_assignments(client) if r.get("tenantId") == tenantId]
            return assignments_view(rows, 200)

        return await run_tool("immybot_tenants_deployments", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_tenants_compliance(tenantId: TenantId) -> str:
        """List a tenant's non-compliant items: latest failed or pending action per computer and deployment."""

        async def action(client: ImmyBotClient) -> dict:
            rows = [r for r in as_list(await client.get(f"maintenance-actions/latest-non-compliant-actions-for-tenant/{tenantId}")) if isinstance(r, dict)]
            keep = (
                "computerId", "computerName", "maintenanceDisplayName", "maintenanceIdentifier", "actionType", "result",
                "detectedVersionString", "desiredVersionString", "resultReasonMessage", "assignmentId", "createdDateUTC",
            )
            items = names([{k: r.get(k) for k in keep if r.get(k) is not None} for r in rows])
            by_result = Counter(str(enum_name(r.get("result"), ACTION_RESULT)) for r in rows)
            return compact(
                {
                    "tenant_id": tenantId,
                    "non_compliant": len(items),
                    "computers_affected": len({r.get("computerId") for r in rows}),
                    "by_result": dict(by_result),
                    "items": items[:200],
                    "truncated": True if len(items) > 200 else None,
                }
            )

        return await run_tool("immybot_tenants_compliance", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_tenants_software_inventory(tenantId: TenantId) -> str:
        """List software detected on a tenant's computers, grouped by name and version with computer counts."""

        async def action(client: ImmyBotClient) -> dict:
            rows = [r for r in as_list(await client.get(f"tenants/software-from-inventory/{tenantId}")) if isinstance(r, dict)]
            groups: dict[tuple, set] = {}
            for r in rows:
                name = r.get("displayName") or r.get("softwareName") or r.get("globalSoftwareName")
                version = r.get("displayVersion") or r.get("version") or r.get("globalSoftwareVersion")
                groups.setdefault((name, version), set()).add(r.get("computerId"))
            software = sorted(
                ({"name": n, "version": v, "computers": len(c)} for (n, v), c in groups.items()),
                key=lambda x: (-x["computers"], str(x["name"])),
            )
            return {"tenant_id": tenantId, "software": software[:500], "distinct": len(software), "detections": len(rows)}

        return await run_tool("immybot_tenants_software_inventory", client_factory, action)
