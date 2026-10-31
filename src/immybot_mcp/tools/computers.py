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
"""Computers: the endpoints ImmyBot manages."""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import ImmyBotClient
from ._common import (
    DEFAULT,
    DESTRUCTIVE,
    LOCAL,
    MAX_PAGE_LIMIT,
    READ_ONLY,
    WRITES_IDEMPOTENT,
    ClientFactory,
    ComputerId,
    Confirm,
    PageLimit,
    OptionalTenantId,
    as_list,
    compact,
    drop,
    listing,
    mask_parameters,
    names,
    not_confirmed,
    run_tool,
    unsupported,
)

OperatingSystem = Literal["Windows", "macOS", "Linux"]


async def latest_actions_for_computer(client: ImmyBotClient, computer_id: int) -> dict:
    rows = as_list(await client.get(f"maintenance-actions/latest-for-computer/{computer_id}"))
    return {"computer_id": computer_id, "items": names(mask_parameters(rows)), "count": len(rows)}


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def immybot_computers_list(
        tenantId: OptionalTenantId = None,
        isOnline: Annotated[bool | None, Field(description="true = only online, false = only offline.")] = None,
        operatingSystem: Annotated[OperatingSystem | None, Field(description="Operating system family.")] = None,
        search: Annotated[str | None, Field(description="Text to match (computer name, user, serial ...).")] = None,
        skip: Annotated[int, Field(description="Records to skip, for paging.", ge=0)] = 0,
        limit: PageLimit = DEFAULT,
    ) -> str:
        """List computers with tenant, online state, OS, model, serial, IPs, primary user and active session."""

        async def action(client: ImmyBotClient) -> dict:
            params = compact(
                {
                    "tenantId": tenantId,
                    "includeOffline": isOnline is not True,
                    "filter": search,
                    "skip": skip,
                    "take": limit,
                    "sort": "computerName",
                }
            )
            payload = await client.get("computers/paged", params)
            rows = as_list(payload)
            total = payload.get("count") if isinstance(payload, dict) else None
            if tenantId is not None:  # the API may ignore tenantId; enforce it here
                rows = [r for r in rows if r.get("tenantId") == tenantId]
            if isOnline is False:
                rows = [r for r in rows if r.get("isOnline") is False]
            if operatingSystem:
                key = {"Windows": "windows", "macOS": "mac", "Linux": "linux"}[operatingSystem]
                rows = [r for r in rows if key in str(r.get("operatingSystem") or "").lower()]
            more = total is not None and skip + limit < total
            out = listing("computers", rows, limit) | compact({"total": total, "has_more": more, "next_skip": skip + limit if more else None})
            if not operatingSystem:
                # Rows map 1:1 to the API's skip offsets, so the size cap can continue right after the last row it returns.
                out["_resume"] = {"key": "next_skip", "start": skip}
            return out

        return await run_tool("immybot_computers_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_computers_get(computerId: ComputerId) -> str:
        """Get one computer: tenant, online state, onboarding status, primary person, agents and flags."""

        async def action(client: ImmyBotClient) -> Any:
            record = await client.get(f"computers/{computerId}", {"includePrimaryPerson": True, "includeProviderAgents": True})
            return names(drop(record, "inventory"))

        return await run_tool("immybot_computers_get", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_computers_search(
        query: Annotated[str, Field(description="Computer name or part of it.", min_length=1)],
        tenantId: OptionalTenantId = None,
    ) -> str:
        """Find computers by name; returns id, tenant, online state and last update."""

        async def action(client: ImmyBotClient) -> dict:
            rows = as_list(await client.get("computers", compact({"name": query, "tenantId": tenantId, "pageSize": 50})))
            if tenantId is not None:
                rows = [r for r in rows if r.get("tenantId") == tenantId]
            return listing("computers", rows, 50)

        return await run_tool("immybot_computers_search", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_computers_inventory(computerId: ComputerId) -> str:
        """Get a computer's inventory: hardware / OS inventory results and the software detected on it."""

        async def action(client: ImmyBotClient) -> dict:
            record = await client.get(f"computers/{computerId}")
            software = as_list(await client.get(f"computers/{computerId}/detected-computer-software"))
            fields = ("softwareName", "version", "platform", "installDate", "detectedAt", "softwareId", "productCode", "installLocation")
            return {
                "computer_id": computerId,
                "computer_name": record.get("computerName") if isinstance(record, dict) else None,
                "inventory": record.get("inventory") if isinstance(record, dict) else None,
                "software": [{k: s.get(k) for k in fields if s.get(k) is not None} for s in software],
                "software_count": len(software),
            }

        return await run_tool("immybot_computers_inventory", client_factory, action)

    @mcp.tool(annotations=LOCAL)
    async def immybot_computers_create(
        name: Annotated[str, Field(description="Not used: see the tool description.")],
        tenantId: Annotated[int, Field(description="Not used: see the tool description.")],
        serialNumber: Annotated[str | None, Field(description="Not used.")] = None,
        macAddress: Annotated[str | None, Field(description="Not used.")] = None,
        description: Annotated[str | None, Field(description="Not used.")] = None,
        location: Annotated[str | None, Field(description="Not used.")] = None,
    ) -> str:
        """Not available: ImmyBot computers are added by installing the ImmyBot agent, not via the API."""
        return unsupported(
            "endpoint for creating computers",
            "Computers appear once the ImmyBot agent is installed on them (installer per tenant in the ImmyBot portal); "
            "then find them with immybot_computers_search.",
        )

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_computers_deployments(computerId: ComputerId) -> str:
        """List what applies to a computer: the latest action per deployed item, with desired state and result."""

        async def action(client: ImmyBotClient) -> dict:
            return await latest_actions_for_computer(client, computerId)

        return await run_tool("immybot_computers_deployments", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def immybot_computers_trigger_checkin(computerId: ComputerId) -> str:
        """Ask a computer to re-run its inventory now (refreshes its data). Only when the user explicitly asks."""

        async def action(client: ImmyBotClient) -> Any:
            result = await client.post(f"computers/{computerId}/reinventory")
            return {"done": True, "computer_id": computerId, "result": result}

        return await run_tool("immybot_computers_trigger_checkin", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def immybot_computers_set_needs_onboarding(computerId: ComputerId) -> str:
        """Mark a computer as needing onboarding; the next run starts it. Only when the user explicitly asks."""

        async def action(client: ImmyBotClient) -> Any:
            result = await client.post(f"computers/{computerId}/set-to-needs-onboarding")
            return {"done": True, "computer_id": computerId, "result": result}

        return await run_tool("immybot_computers_set_needs_onboarding", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def immybot_computers_delete(
        computerIds: Annotated[
            list[int], Field(description="Computer ids to permanently delete.", min_length=1, max_length=MAX_PAGE_LIMIT)
        ],
        confirm: Confirm = None,
    ) -> str:
        """Permanently delete one or more computer records (device offboarding). Needs confirm: true.

        Only when the user explicitly asks. This removes ImmyBot's own record; it does not
        uninstall the ImmyBot agent from the physical device.
        """

        async def action(client: ImmyBotClient) -> Any:
            if confirm is not True:
                return not_confirmed(f"Delete {len(computerIds)} computer record(s): {', '.join(map(str, computerIds))}")
            result = await client.post("computers/bulk-delete", {"ids": computerIds})
            return {"done": True, "deleted_count": len(computerIds), "computer_ids": computerIds, "result": result}

        return await run_tool("immybot_computers_delete", client_factory, action)
