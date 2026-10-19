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
"""Starting maintenance through POST /run-immy-service, shared by several tools."""

from typing import Any

from ..api_client import ImmyBotClient
from ._common import compact


async def run_immy_service(
    client: ImmyBotClient,
    *,
    computer_ids: list[int] | None = None,
    tenant_ids: list[int] | None = None,
    maintenance: dict[str, Any] | None = None,
    allow_reboot: bool = True,
    full_maintenance: bool = False,
    **flags: Any,
) -> dict:
    """Start maintenance now and return the sessions ImmyBot started or found already running."""
    if not computer_ids and not tenant_ids:
        raise ValueError("Pass a computer or a tenant to run maintenance on.")
    body = compact(
        {
            "computers": [{"computerId": c} for c in computer_ids] if computer_ids else None,
            "tenants": [{"tenantId": t} for t in tenant_ids] if tenant_ids else None,
            "maintenanceParams": maintenance,
            "fullMaintenance": full_maintenance,
            "rebootPreference": "Normal" if allow_reboot else "Suppress",
            "offlineBehavior": "ApplyOnConnect",
            "useWinningDeployment": maintenance is None,
        }
        | flags
    )
    result = await client.post("run-immy-service", body)
    result = result if isinstance(result, dict) else {}
    started = result.get("sessionsStarted") or []
    running = result.get("sessionsAlreadyInProgress") or []
    return {
        "done": True,
        "sessions_started": started,
        "sessions_already_in_progress": running,
        "next": "Follow progress with immybot_maintenance_sessions_get / _results using the session ids.",
    }
