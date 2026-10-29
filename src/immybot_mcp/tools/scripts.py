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
"""Scripts: ImmyBot's global (shared) and local (MSP-owned) PowerShell / command-line scripts."""

import uuid
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import ImmyBotClient
from ._common import (
    DEFAULT,
    DESTRUCTIVE,
    LOCAL,
    READ_ONLY,
    SCRIPT_CATEGORY,
    SCRIPT_LANGUAGE,
    ClientFactory,
    ComputerId,
    Confirm,
    DatabaseType,
    Limit,
    as_list,
    compact,
    enum_name,
    enum_value,
    get_from_catalog,
    listing,
    names,
    not_confirmed,
    run_tool,
    sieve_params,
    unsupported,
)

ScriptId = Annotated[int, Field(description="Script id.", ge=1)]
Category = Annotated[str | None, Field(description=f"Script category: {', '.join(SCRIPT_CATEGORY)}.")]
ValidateLanguage = Literal["PowerShell", "CommandLine"]
# /scripts/run streams until the script ends; ImmyBot's own gateway stops it near 120s
# and ours at 120s, so cap the wait below both.
_RUN_READ_TIMEOUT = 95.0
_RUN_FIELDS = (
    "id", "name", "action", "databaseType", "filterScriptMode", "outputType", "scriptCategory", "scriptLanguage",
    "scriptExecutionContext",
)


def _matches(row: dict, category: str | None, language: str | None) -> bool:
    if category and str(enum_name(row.get("scriptCategory"), SCRIPT_CATEGORY)).lower() != category.lower():
        return False
    if language and str(enum_name(row.get("scriptLanguage"), SCRIPT_LANGUAGE)).lower() != language.lower():
        return False
    return True


async def search_scripts(client: ImmyBotClient, limit: int, text: str | None, is_global: bool | None) -> list[dict]:
    params = sieve_params(limit, text) | compact({"globalOnly": True if is_global is True else None, "localOnly": True if is_global is False else None})
    return [r for r in as_list(await client.get("scripts/search", params)) if isinstance(r, dict)]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def immybot_scripts_list(
        category: Category = None,
        isGlobal: Annotated[bool | None, Field(description="true = global catalog only, false = local only.")] = None,
        search: Annotated[str | None, Field(description="Text the script name contains.")] = None,
        language: Annotated[str | None, Field(description="PowerShell or CommandLine.")] = None,
        limit: Limit = DEFAULT,
    ) -> str:
        """List scripts with id, catalog (Global / Local), category, language and execution context."""

        async def action(client: ImmyBotClient) -> dict:
            fetch = limit if not (category or language) else 500
            rows = [r for r in await search_scripts(client, fetch, search, isGlobal) if _matches(r, category, language)]
            return listing("scripts", rows, limit)

        return await run_tool("immybot_scripts_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_scripts_get(scriptId: ScriptId, databaseType: DatabaseType = None) -> str:
        """Get one script including its body (action), category, language, context and timeout."""

        async def action(client: ImmyBotClient) -> Any:
            record, db = await get_from_catalog(client, "scripts", scriptId, databaseType)
            return names(record) | {"databaseType": db} if isinstance(record, dict) else record

        return await run_tool("immybot_scripts_get", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_scripts_search(
        query: Annotated[str, Field(description="Text the script name contains.", min_length=1)],
        category: Category = None,
        isGlobal: Annotated[bool | None, Field(description="true = global only, false = local only.")] = None,
    ) -> str:
        """Search scripts by name across the global and local catalogs."""

        async def action(client: ImmyBotClient) -> dict:
            rows = [r for r in await search_scripts(client, 100 if not category else 500, query, isGlobal) if _matches(r, category, None)]
            return listing("scripts", rows, 100)

        return await run_tool("immybot_scripts_search", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def immybot_scripts_run(
        scriptId: ScriptId,
        computerId: ComputerId,
        parameters: Annotated[dict[str, Any] | None, Field(description="Parameter values by name.")] = None,
        timeout: Annotated[int, Field(description="Script timeout in seconds (max 90 here).", ge=1, le=90)] = 30,
        runAs: Annotated[Literal["System", "User"], Field(description="User = run as the logged-on user; System keeps the script's own context.")] = "System",
        databaseType: DatabaseType = None,
        confirm: Confirm = None,
    ) -> str:
        """Run a saved script on one computer now and return its output. Needs confirm: true.

        Executes code on the endpoint. Only when the user explicitly asks; review the script first with
        immybot_scripts_get. Reviewing first is optional when the script id was already approved by an
        administrator or a pre-reviewed workflow.
        """

        async def action(client: ImmyBotClient) -> Any:
            script, db = await get_from_catalog(client, "scripts", scriptId, databaseType)
            if not isinstance(script, dict):
                raise ValueError(f"Script {scriptId} was not found.")
            if confirm is not True:
                return not_confirmed(f"Run script {scriptId} ({script.get('name')}) on computer {computerId} as {runAs}")
            payload = {k: script.get(k) for k in _RUN_FIELDS} | {
                "databaseType": script.get("databaseType") or db,
                "timeout": timeout,
                "parameterOverrides": parameters or {},
                "variables": {},
            }
            if runAs == "User":
                payload["scriptExecutionContext"] = "CurrentUser"
            elif payload.get("scriptExecutionContext") is None:
                payload["scriptExecutionContext"] = "System"
            output = await client.post(
                "scripts/run",
                {"body": payload, "computerId": computerId, "cancellationId": str(uuid.uuid4())},
                read_timeout=_RUN_READ_TIMEOUT,
            )
            return {"done": True, "script_id": scriptId, "computer_id": computerId, "output": output}

        return await run_tool("immybot_scripts_run", client_factory, action)

    @mcp.tool(annotations=LOCAL)
    async def immybot_scripts_categories() -> str:
        """List the script categories ImmyBot uses (a fixed set)."""
        from .._json import compact as to_json

        return to_json({"categories": SCRIPT_CATEGORY})

    @mcp.tool(annotations=LOCAL)
    async def immybot_scripts_execution_history(
        computerId: ComputerId,
        limit: Annotated[int, Field(description="Not used.", ge=1)] = 50,
    ) -> str:
        """Not available: ImmyBot keeps no script run history; see maintenance session logs instead."""
        return unsupported(
            "script execution history",
            "Scripts run during maintenance appear in immybot_maintenance_sessions_logs; "
            "list the computer's sessions with immybot_maintenance_sessions_list(computerId=...).",
        )

    @mcp.tool(annotations=LOCAL)
    async def immybot_scripts_execution_result(
        scriptId: ScriptId,
        executionId: Annotated[int, Field(description="Not used.", ge=1)],
    ) -> str:
        """Not available: ImmyBot does not store script runs; immybot_scripts_run returns the output directly."""
        return unsupported("stored script execution results", "immybot_scripts_run returns the script output in its response.")

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_scripts_validate(
        content: Annotated[str, Field(description="Script text to check.", min_length=1)],
        language: Annotated[ValidateLanguage | str, Field(description="Script language.")] = "PowerShell",
    ) -> str:
        """Check a script's syntax without running it; returns whether it is valid and the errors."""

        async def action(client: ImmyBotClient) -> Any:
            return await client.post("scripts/syntax-check", {"script": content, "scriptLanguage": enum_value(language, ValidateLanguage)})

        return await run_tool("immybot_scripts_validate", client_factory, action)
