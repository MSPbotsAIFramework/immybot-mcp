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
"""Task-queue tools kept for compatibility.

ImmyBot has no task queue API: its work is done in maintenance sessions, made of
maintenance actions. These tools keep their names so existing callers get a clear
error that names the tool to use instead.
"""

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ._common import LOCAL, ClientFactory, unsupported

TaskId = Annotated[int, Field(description="Not used: see the tool description.")]
Unused = Annotated[str | None, Field(description="Not used.")]
UnusedInt = Annotated[int | None, Field(description="Not used.")]

_FEATURE = "task queue"
_SESSIONS = "Use immybot_maintenance_sessions_list"
_ONE = "Use immybot_maintenance_sessions_get, _results or _logs with a session id"


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_list(
        computerId: UnusedInt = None,
        tenantId: UnusedInt = None,
        status: Annotated[Literal["Queued", "Running", "Completed", "Failed", "Cancelled", "Retrying"] | None, Field(description="Not used.")] = None,
        type: Unused = None,
        parentTaskId: UnusedInt = None,
        priority: Annotated[Literal["Low", "Normal", "High", "Emergency"] | None, Field(description="Not used.")] = None,
        startDate: Unused = None,
        endDate: Unused = None,
        limit: Annotated[int, Field(description="Not used.")] = 50,
    ) -> str:
        """Not available: ImmyBot has no task queue. Use immybot_maintenance_sessions_list instead."""
        return unsupported(_FEATURE, f"{_SESSIONS} (it filters by computerId, tenantId, status and dates).")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_get(taskId: TaskId) -> str:
        """Not available: ImmyBot has no tasks. Use immybot_maintenance_sessions_get with a session id."""
        return unsupported(_FEATURE, f"{_ONE}.")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_running() -> str:
        """Not available: ImmyBot has no task queue. Use immybot_maintenance_sessions_active instead."""
        return unsupported(_FEATURE, "Use immybot_maintenance_sessions_active for the sessions running now.")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_queued() -> str:
        """Not available: ImmyBot has no task queue. Use immybot_maintenance_sessions_list(status='Queued')."""
        return unsupported(_FEATURE, f"{_SESSIONS}(status='Queued') for pending sessions.")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_failed() -> str:
        """Not available: ImmyBot has no task queue. Use immybot_maintenance_sessions_list(status='Failed')."""
        return unsupported(_FEATURE, f"{_SESSIONS}(status='Failed'), then immybot_maintenance_sessions_results.")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_for_computer(computerId: TaskId) -> str:
        """Not available: ImmyBot has no task queue. Use immybot_maintenance_sessions_list(computerId=...)."""
        return unsupported(_FEATURE, f"{_SESSIONS}(computerId=...) or immybot_computers_deployments.")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_for_tenant(tenantId: TaskId) -> str:
        """Not available: ImmyBot has no task queue. Use immybot_maintenance_sessions_list(tenantId=...)."""
        return unsupported(_FEATURE, f"{_SESSIONS}(tenantId=...) or immybot_tenants_compliance.")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_by_type(taskType: Annotated[str, Field(description="Not used.")]) -> str:
        """Not available: ImmyBot has no task types. Use immybot_maintenance_sessions_summary instead."""
        return unsupported(_FEATURE, "Use immybot_maintenance_sessions_summary or immybot_maintenance_sessions_list.")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_queue_stats() -> str:
        """Not available: ImmyBot has no task queue. Use immybot_maintenance_sessions_summary instead."""
        return unsupported(_FEATURE, "Use immybot_maintenance_sessions_summary for session counts by status.")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_history(
        computerId: UnusedInt = None,
        tenantId: UnusedInt = None,
        taskType: Unused = None,
        startDate: Unused = None,
        endDate: Unused = None,
        limit: Annotated[int, Field(description="Not used.")] = 50,
    ) -> str:
        """Not available: ImmyBot has no task history. Use immybot_maintenance_sessions_list instead."""
        return unsupported(_FEATURE, f"{_SESSIONS} with computerId / tenantId / startDate / endDate.")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_dependencies(taskId: TaskId) -> str:
        """Not available: ImmyBot has no tasks. Use immybot_maintenance_sessions_results with a session id."""
        return unsupported(_FEATURE, f"{_ONE}.")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_child_tasks(parentTaskId: TaskId) -> str:
        """Not available: ImmyBot has no tasks. Use immybot_maintenance_sessions_results with a session id."""
        return unsupported(_FEATURE, f"{_ONE}.")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_logs(taskId: TaskId) -> str:
        """Not available: ImmyBot has no tasks. Use immybot_maintenance_sessions_logs with a session id."""
        return unsupported(_FEATURE, "Use immybot_maintenance_sessions_logs with a session id.")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_metrics(taskId: TaskId) -> str:
        """Not available: ImmyBot has no tasks. Use immybot_maintenance_sessions_get with a session id."""
        return unsupported(_FEATURE, f"{_ONE}.")

    @mcp.tool(annotations=LOCAL)
    async def immybot_tasks_estimated_completion(taskId: TaskId) -> str:
        """Not available: ImmyBot gives no completion estimates. Use immybot_maintenance_sessions_get."""
        return unsupported("completion estimate", "Use immybot_maintenance_sessions_get to see a session's stage statuses.")
