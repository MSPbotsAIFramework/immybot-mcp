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
"""Maintenance sessions: ImmyBot runs that detect and apply deployments on a computer."""

from collections import Counter
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import ImmyBotClient
from ._common import (
    DEFAULT,
    DESTRUCTIVE,
    LOCAL,
    READ_ONLY,
    SESSION_STATUS,
    WRITES,
    WRITES_IDEMPOTENT,
    ClientFactory,
    Confirm,
    DateText,
    Limit,
    OptionalTenantId,
    SessionId,
    as_list,
    compact,
    drop,
    dx_date,
    dx_params,
    enum_name,
    listing,
    mask_parameters,
    names,
    not_confirmed,
    run_tool,
    unsupported,
)
from ._maintenance import run_immy_service

Status = Literal["Queued", "Running", "Completed", "Failed", "Cancelled", "Paused"]
# Older status words -> ImmyBot SessionStatus.
_STATUS = {"Queued": "Pending", "Running": "Running", "Completed": "Passed", "Failed": "Failed", "Cancelled": "Cancelled", "Paused": "Postponed"}
_SESSION_FIELDS = (
    "id", "computerId", "computerName", "tenantId", "tenantName", "sessionStatus", "fullMaintenance", "onboarding",
    "createdDateUTC", "updatedDateUTC", "duration", "scheduledId", "createdBy",
)


async def list_sessions(
    client: ImmyBotClient,
    limit: int,
    computer_id: int | None = None,
    tenant_id: int | None = None,
    status: str | None = None,
    start: str | None = None,
    end: str | None = None,
    scheduled: bool | None = None,
) -> list[dict]:
    filters: list[list[Any]] = []
    if status:
        filters.append(["sessionStatus", "=", SESSION_STATUS.index(status)])
    if start:
        filters.append(["createdDate", ">=", dx_date(start)])
    if end:
        filters.append(["createdDate", "<=", dx_date(end)])
    params = dx_params(limit, filters, sort_desc="createdDate") | compact(
        {"computerId": computer_id, "tenantId": tenant_id, "scheduledFilter": scheduled}
    )
    rows = [r for r in as_list(await client.get("maintenance-sessions/dx", params)) if isinstance(r, dict)]
    return rows


def session_rows(rows: list[dict]) -> list[dict]:
    return [{k: r.get(k) for k in _SESSION_FIELDS if r.get(k) is not None} or r for r in rows]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def immybot_maintenance_sessions_list(
        computerId: Annotated[int | None, Field(description="Only this computer.", ge=1)] = None,
        tenantId: OptionalTenantId = None,
        status: Annotated[Status | None, Field(description="Queued = pending, Completed = passed, Paused = postponed.")] = None,
        sessionType: Annotated[
            Literal["Manual", "Scheduled", "Automated", "Emergency"] | None,
            Field(description="Scheduled = only sessions started by a schedule; other values do not filter."),
        ] = None,
        startDate: DateText = None,
        endDate: DateText = None,
        limit: Limit = DEFAULT,
    ) -> str:
        """List maintenance sessions, newest first, with computer, tenant, status, duration and start time."""

        async def action(client: ImmyBotClient) -> dict:
            rows = await list_sessions(
                client, limit, computerId, tenantId, _STATUS[status] if status else None, startDate, endDate,
                True if sessionType == "Scheduled" else None,
            )
            return listing("sessions", session_rows(rows), limit) | {"has_more": len(rows) >= limit}

        return await run_tool("immybot_maintenance_sessions_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_maintenance_sessions_get(sessionId: SessionId) -> str:
        """Get one maintenance session: status of each stage, timings and its maintenance actions."""

        async def action(client: ImmyBotClient) -> Any:
            record = await client.get(f"maintenance-sessions/{sessionId}", {"includeActions": True, "includeStages": True})
            # sessionJobArgs carries task parameter values in clear text; logs / computer / tenant are large.
            return names(mask_parameters(drop(record, "sessionJobArgs", "logs", "activities", "computer", "tenant")))

        return await run_tool("immybot_maintenance_sessions_get", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def immybot_maintenance_sessions_start(
        computerId: Annotated[int | None, Field(description="Computer to maintain (this or tenantId).", ge=1)] = None,
        tenantId: Annotated[int | None, Field(description="Maintain every computer of this tenant.", ge=1)] = None,
        sessionType: Annotated[Literal["Manual", "Scheduled", "Emergency"], Field(description="Kept for compatibility; sessions start now.")] = "Manual",
        priority: Annotated[Literal["Low", "Normal", "High", "Emergency"], Field(description="Kept for compatibility; not used by ImmyBot.")] = "Normal",
        allowReboot: Annotated[bool, Field(description="false = suppress reboots.")] = True,
        description: Annotated[str | None, Field(description="Not sent: ImmyBot sessions have no description.")] = None,
        detectionOnly: Annotated[bool, Field(description="Only detect what would change; install nothing.")] = False,
        confirm: Confirm = None,
    ) -> str:
        """Start full maintenance now on a computer or a whole tenant (applies all deployments).

        Needs confirm: true. Only when the user explicitly asks. detectionOnly previews without changing anything.
        """

        async def action(client: ImmyBotClient) -> Any:
            if computerId is None and tenantId is None:
                raise ValueError("Pass computerId or tenantId.")
            where = f"computer {computerId}" if computerId else f"every computer of tenant {tenantId}"
            if confirm is not True:
                kind = "detection-only maintenance" if detectionOnly else "full maintenance"
                return not_confirmed(f"Start {kind} now on {where}{'' if allowReboot else ' (no reboots)'}")
            return await run_immy_service(
                client,
                computer_ids=[computerId] if computerId else None,
                tenant_ids=[tenantId] if tenantId and not computerId else None,
                allow_reboot=allowReboot,
                full_maintenance=True,
                detectionOnly=detectionOnly,
            )

        return await run_tool("immybot_maintenance_sessions_start", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def immybot_maintenance_sessions_cancel(
        sessionId: SessionId,
        reason: Annotated[str | None, Field(description="Not sent: ImmyBot records no cancel reason.")] = None,
    ) -> str:
        """Cancel a running or pending maintenance session. Only when the user explicitly asks."""

        async def action(client: ImmyBotClient) -> Any:
            await client.post("maintenance-sessions/cancel", {"sessionIds": [sessionId]})
            return {"done": True, "cancelled_session_id": sessionId}

        return await run_tool("immybot_maintenance_sessions_cancel", client_factory, action)

    @mcp.tool(annotations=LOCAL)
    async def immybot_maintenance_sessions_pause(
        sessionId: SessionId,
        reason: Annotated[str | None, Field(description="Not used.")] = None,
    ) -> str:
        """Not available: ImmyBot sessions cannot be paused (cancel and later resume instead)."""
        return unsupported(
            "pause for maintenance sessions",
            "Use immybot_maintenance_sessions_cancel to stop it and immybot_maintenance_sessions_resume to continue a stopped session.",
        )

    @mcp.tool(annotations=WRITES)
    async def immybot_maintenance_sessions_resume(sessionId: SessionId) -> str:
        """Resume a maintenance session that stopped (e.g. cancelled or postponed). Only when explicitly asked."""

        async def action(client: ImmyBotClient) -> Any:
            await client.post(f"maintenance-sessions/{sessionId}/resume")
            return {"done": True, "resumed_session_id": sessionId}

        return await run_tool("immybot_maintenance_sessions_resume", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_maintenance_sessions_logs(
        sessionId: SessionId,
        limit: Annotated[int, Field(description="Newest log lines to return.", ge=1, le=1000)] = 200,
    ) -> str:
        """Get the log lines of a maintenance session (messages, time, action status; script bodies left out)."""

        async def action(client: ImmyBotClient) -> dict:
            rows = as_list(await client.get(f"maintenance-sessions/{sessionId}/logs"))
            keep = ("time", "message", "maintenanceActionId", "maintenanceActionStatus", "sessionLogType", "scriptId")
            lines = [{k: r.get(k) for k in keep if r.get(k) is not None} for r in rows if isinstance(r, dict)]
            return {"session_id": sessionId, "lines": names(lines[-limit:]), "count": min(len(lines), limit), "total": len(lines)}

        return await run_tool("immybot_maintenance_sessions_logs", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_maintenance_sessions_results(sessionId: SessionId) -> str:
        """Get the per-item results of a session: each action, its type, result, versions and failure reason."""

        async def action(client: ImmyBotClient) -> dict:
            params = dx_params(500, [["maintenanceSessionId", "=", sessionId]])
            rows = as_list(await client.get("maintenance-actions/dx", params))
            keep = (
                "id", "maintenanceDisplayName", "maintenanceType", "actionType", "result", "status", "detectedVersionString",
                "desiredVersionString", "resultReasonMessage", "startTime", "endTime",
            )
            actions = names([{k: r.get(k) for k in keep if r.get(k) is not None} for r in rows if isinstance(r, dict)])
            counts = Counter(str(a.get("result")) for a in actions)
            return {"session_id": sessionId, "results": dict(counts), "actions": actions, "count": len(actions)}

        return await run_tool("immybot_maintenance_sessions_results", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_maintenance_sessions_active() -> str:
        """List maintenance sessions running right now."""

        async def action(client: ImmyBotClient) -> dict:
            rows = await list_sessions(client, 200, status="Running")
            return listing("sessions", session_rows(rows), 200)

        return await run_tool("immybot_maintenance_sessions_active", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_maintenance_sessions_summary(
        tenantId: OptionalTenantId = None,
        startDate: DateText = None,
        endDate: DateText = None,
    ) -> str:
        """Count maintenance sessions by status, for the whole instance or one tenant / date range."""

        async def action(client: ImmyBotClient) -> dict:
            if tenantId is None and not startDate and not endDate:
                payload = await client.get("maintenance-sessions/status-counts")
                payload = payload if isinstance(payload, dict) else {}
                counts = payload.get("counts") or {}
                named = {str(enum_name(int(k), SESSION_STATUS)) if str(k).isdigit() else k: v for k, v in counts.items()}
                return {"scope": "instance", "counts": named, "total": payload.get("total")}
            rows = await list_sessions(client, 1000, tenant_id=tenantId, start=startDate, end=endDate)
            counts = Counter(str(enum_name(r.get("sessionStatus"), SESSION_STATUS)) for r in rows)
            return compact(
                {
                    "scope": "filtered",
                    "tenant_id": tenantId,
                    "counts": dict(counts),
                    "total": len(rows),
                    "note": "Counted from the newest 1000 matching sessions." if len(rows) >= 1000 else None,
                }
            )

        return await run_tool("immybot_maintenance_sessions_summary", client_factory, action)
