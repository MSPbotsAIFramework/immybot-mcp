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
"""Persons: the users ImmyBot tracks for a tenant (e.g. to pick a primary user)."""

from mcp.server.fastmcp import FastMCP

from ..api_client import ImmyBotClient
from ._common import DEFAULT, READ_ONLY, ClientFactory, Limit, TenantId, as_list, compact, dx_params, listing, run_tool

_PERSON_FIELDS = ("id", "firstName", "lastName", "emailAddress", "tenantId", "azureId")


def _person(row: dict) -> dict:
    return {k: row.get(k) for k in _PERSON_FIELDS if row.get(k) is not None}


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def immybot_persons_list(tenantId: TenantId, limit: Limit = DEFAULT) -> str:
        """List a tenant's Persons (users): id, name, email, Azure AD id — e.g. to pick a primary user."""

        async def action(client: ImmyBotClient) -> dict:
            params = dx_params(limit, [["tenantId", "=", tenantId]]) | {"requireTotalCount": True}
            payload = await client.get("Persons/dx", params)
            raw_rows = [r for r in as_list(payload) if isinstance(r, dict)]
            rows = [r for r in raw_rows if r.get("tenantId") == tenantId]  # the API may not honor the filter; enforce it here
            total = payload.get("totalCount") if isinstance(payload, dict) else None
            # The request already sends take=<limit>, so the vendor returns at most `limit` rows and
            # len(items) > limit (listing()'s default) can never be true (PRD-21590 review round 1).
            # Derive has_more from the vendor's total instead, like immybot_maintenance_sessions_list
            # (maintenance_sessions.py:110) falls back to len(rows) >= limit when total is unavailable.
            has_more = total > limit if isinstance(total, int) else len(raw_rows) >= limit
            return listing("persons", [_person(r) for r in rows], limit) | compact({"total": total}) | {"has_more": has_more}

        return await run_tool("immybot_persons_list", client_factory, action)
