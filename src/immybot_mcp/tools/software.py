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
"""Software: ImmyBot's global (shared) and local (MSP-owned) software catalogs."""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import ImmyBotClient
from ._common import (
    DEFAULT,
    DESTRUCTIVE,
    LOCAL,
    READ_ONLY,
    ClientFactory,
    Confirm,
    Limit,
    as_list,
    compact,
    drop,
    get_from_catalog,
    listing,
    names,
    not_confirmed,
    run_tool,
    unsupported,
)
from ._maintenance import run_immy_service

SoftwareId = Annotated[int, Field(description="Software id.", ge=1)]
SoftwareType = Annotated[
    Literal["Global", "Local"] | None,
    Field(description="Catalog the id belongs to; global and local ids can collide. Omit to try Local, then Global."),
]
_FIELDS = ("id", "name", "identifier", "databaseType", "softwareType", "recommended", "hidden", "licenseRequirement", "upgradeCode", "updatedDateUTC")
_VERSION_FIELDS = (
    "semanticVersionString", "displayName", "displayVersion", "softwareId", "testRequired", "numActionSuccesses",
    "numActionFailures", "lastResult", "notes", "createdDateUTC", "updatedDateUTC",
)


def _summary(row: dict, db: str) -> dict:
    return {k: row.get(k) for k in _FIELDS if row.get(k) is not None} | {"databaseType": row.get("databaseType") or db}


async def catalog(client: ImmyBotClient, which: str | None) -> list[dict]:
    """Software summaries from the Local and / or Global catalog."""
    rows: list[dict] = []
    for db in ([which] if which else ["Local", "Global"]):
        rows += [_summary(r, db) for r in as_list(await client.get(f"software/{db.lower()}")) if isinstance(r, dict)]
    return rows


def _named(rows: list[dict], text: str | None) -> list[dict]:
    if not text:
        return rows
    needle = text.lower()
    return [r for r in rows if needle in str(r.get("name") or "").lower()]


async def _software_path(client: ImmyBotClient, software_id: int, software_type: str | None, suffix: str = "") -> tuple[Any, str]:
    return await get_from_catalog(client, "software", software_id, software_type, suffix)


def _versions(rows: Any) -> list[dict]:
    return names([{k: r.get(k) for k in _VERSION_FIELDS if r.get(k) is not None} for r in as_list(rows) if isinstance(r, dict)])


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def immybot_software_list_global(
        search: Annotated[str | None, Field(description="Text the software name contains.")] = None,
        limit: Limit = DEFAULT,
    ) -> str:
        """List software in ImmyBot's global (shared) catalog: id, name, type, recommended flag."""

        async def action(client: ImmyBotClient) -> dict:
            return listing("software", _named(await catalog(client, "Global"), search), limit)

        return await run_tool("immybot_software_list_global", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_software_list(
        search: Annotated[str | None, Field(description="Text the software name contains.")] = None,
        isGlobal: Annotated[bool | None, Field(description="true = global catalog only, false = local only; omit for both.")] = None,
        limit: Limit = DEFAULT,
    ) -> str:
        """List software from the local (MSP-owned) and / or global catalog with id, name and catalog."""

        async def action(client: ImmyBotClient) -> dict:
            which = None if isGlobal is None else ("Global" if isGlobal else "Local")
            return listing("software", _named(await catalog(client, which), search), limit)

        return await run_tool("immybot_software_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_software_get(softwareId: SoftwareId, softwareType: SoftwareType = None) -> str:
        """Get one software item: detection method, install / uninstall scripts, license and reboot needs."""

        async def action(client: ImmyBotClient) -> Any:
            record, db = await _software_path(client, softwareId, softwareType)
            if isinstance(record, dict):
                return names(drop(record, "softwareVersions", "softwareIcon")) | {"databaseType": record.get("databaseType") or db}
            return record

        return await run_tool("immybot_software_get", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_software_search(query: Annotated[str, Field(description="Text the software name contains.", min_length=1)]) -> str:
        """Search software by name across the local and global catalogs."""

        async def action(client: ImmyBotClient) -> dict:
            return listing("software", _named(await catalog(client, None), query), 100)

        return await run_tool("immybot_software_search", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_software_versions(softwareId: SoftwareId, softwareType: SoftwareType = None) -> str:
        """List the versions ImmyBot has for a software item, with success / failure counts."""

        async def action(client: ImmyBotClient) -> dict:
            rows, db = await _software_path(client, softwareId, softwareType, "/versions")
            versions = _versions(rows)
            return {"software_id": softwareId, "databaseType": db, "versions": versions, "count": len(versions)}

        return await run_tool("immybot_software_versions", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_software_latest_version(softwareId: SoftwareId, softwareType: SoftwareType = None) -> str:
        """Get the latest version ImmyBot knows for a software item."""

        async def action(client: ImmyBotClient) -> Any:
            record, db = await _software_path(client, softwareId, softwareType, "/latest")
            version = _versions([record])
            return (version[0] if version else {}) | {"software_id": softwareId, "databaseType": db}

        return await run_tool("immybot_software_latest_version", client_factory, action)

    @mcp.tool(annotations=LOCAL)
    async def immybot_software_categories() -> str:
        """Not available: ImmyBot software has no categories; search by name instead."""
        return unsupported("software categories", "Use immybot_software_search(query) or immybot_software_list(search=...).")

    @mcp.tool(annotations=LOCAL)
    async def immybot_software_publishers() -> str:
        """Not available: ImmyBot does not track software publishers; search by name instead."""
        return unsupported("software publishers", "Use immybot_software_search(query) or immybot_software_list(search=...).")

    @mcp.tool(annotations=DESTRUCTIVE)
    async def immybot_software_install(
        softwareId: SoftwareId,
        computerIds: Annotated[list[int] | None, Field(description="Computers to install on (or tenantId).")] = None,
        tenantId: Annotated[int | None, Field(description="Install on every computer of this tenant.", ge=1)] = None,
        softwareType: Annotated[Literal["Global", "Local"], Field(description="Catalog of the software id.")] = "Global",
        allowReboot: Annotated[bool, Field(description="false = suppress reboots.")] = False,
        confirm: Confirm = None,
    ) -> str:
        """Install (or update to latest) one software item now on computers or a tenant. Needs confirm: true.

        Starts maintenance for just that item. Only when the user explicitly asks.
        """

        async def action(client: ImmyBotClient) -> Any:
            if not computerIds and tenantId is None:
                raise ValueError("Pass computerIds or tenantId.")
            where = f"computers {', '.join(map(str, computerIds))}" if computerIds else f"every computer of tenant {tenantId}"
            if confirm is not True:
                return not_confirmed(f"Install {softwareType.lower()} software {softwareId} (latest version) now on {where}")
            maintenance = {
                "maintenanceIdentifier": str(softwareId),
                "maintenanceType": f"{softwareType}Software",
                "desiredSoftwareState": "LatestVersion",
                "repair": False,
            }
            return await run_immy_service(
                client,
                computer_ids=computerIds or None,
                tenant_ids=[tenantId] if tenantId and not computerIds else None,
                maintenance=maintenance,
                allow_reboot=allowReboot,
            )

        return await run_tool("immybot_software_install", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_software_stats(softwareId: SoftwareId, softwareType: SoftwareType = None) -> str:
        """Success / failure counts of a software item's actions, in total and per version."""

        async def action(client: ImmyBotClient) -> dict:
            rows, db = await _software_path(client, softwareId, softwareType, "/versions")
            versions = _versions(rows)
            ok = sum(int(v.get("numActionSuccesses") or 0) for v in versions)
            failed = sum(int(v.get("numActionFailures") or 0) for v in versions)
            per_version = [
                compact({"version": v.get("semanticVersionString"), "successes": v.get("numActionSuccesses"), "failures": v.get("numActionFailures")})
                for v in versions
            ]
            return {
                "software_id": softwareId,
                "databaseType": db,
                "versions": len(versions),
                "action_successes": ok,
                "action_failures": failed,
                "success_rate": round(ok / (ok + failed), 3) if ok + failed else None,
                "per_version": per_version,
            }

        return await run_tool("immybot_software_stats", client_factory, action)
