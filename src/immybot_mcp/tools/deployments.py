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
"""Deployments: ImmyBot target assignments (an item, its desired state and its targets)."""

from collections import Counter
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import ImmyBotClient
from ._common import (
    DEFAULT,
    DESTRUCTIVE,
    READ_ONLY,
    WRITES,
    ClientFactory,
    ComputerId,
    Confirm,
    Limit,
    as_list,
    compact,
    dx_params,
    enum_name,
    listing,
    mask_parameters,
    names,
    not_confirmed,
    run_tool,
    ACTION_RESULT,
    DESIRED_STATE,
)
from ._maintenance import run_immy_service
from .computers import latest_actions_for_computer

DeploymentId = Annotated[int, Field(description="Deployment (target assignment) id.", ge=1)]
SoftwareId = Annotated[int, Field(description="Software id.", ge=1)]
TargetKind = Literal["Computer", "Tenant", "Group"]
DesiredState = Literal["Installed", "Uninstalled", "Updated"]

_STATE_GROUPS: dict[str, set[str]] = {
    "Installed": {"LatestVersion", "NewerOrEqualVersion", "AnyVersion", "ThisVersion", "OlderOrEqualVersion"},
    "Uninstalled": {"NotPresent"},
    "Updated": {"UpdateIfFound", "LatestVersion"},
}
_SOFTWARE_TYPES = {"GlobalSoftware", "LocalSoftware", 0, 1}
_PAGE = 1000


async def all_assignments(client: ImmyBotClient) -> list[dict]:
    return [r for r in as_list(await client.get("target-assignments", {"Page": 1, "PageSize": _PAGE})) if isinstance(r, dict)]


def assignments_view(rows: list[dict], limit: int) -> dict:
    return listing("deployments", mask_parameters(rows), limit)


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def immybot_deployments_list(
        targetType: Annotated[TargetKind | None, Field(description="Kind of target targetId refers to.")] = None,
        targetId: Annotated[int | None, Field(description="Computer, tenant or group (tag) id.", ge=1)] = None,
        softwareId: Annotated[int | None, Field(description="Only deployments of this software id.", ge=1)] = None,
        desiredState: Annotated[DesiredState | None, Field(description="Desired software state.")] = None,
        limit: Limit = DEFAULT,
    ) -> str:
        """List deployments: item, desired state, target, tenant, enforcement and when they changed."""

        async def action(client: ImmyBotClient) -> dict:
            rows = await all_assignments(client)
            if targetId is not None:
                if targetType == "Tenant":
                    rows = [r for r in rows if r.get("tenantId") == targetId]
                else:
                    rows = [r for r in rows if str(r.get("target")) == str(targetId)]
            if softwareId is not None:
                rows = [r for r in rows if str(r.get("maintenanceIdentifier")) == str(softwareId) and r.get("maintenanceType") in _SOFTWARE_TYPES]
            if desiredState:
                wanted = _STATE_GROUPS[desiredState]
                rows = [r for r in rows if enum_name(r.get("desiredSoftwareState"), DESIRED_STATE) in wanted]
            return assignments_view(rows, limit)

        return await run_tool("immybot_deployments_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_deployments_get(deploymentId: DeploymentId) -> str:
        """Get one deployment with its target, desired state and task parameters (secret values masked)."""

        async def action(client: ImmyBotClient) -> Any:
            return names(mask_parameters(await client.get(f"target-assignments/{deploymentId}")))

        return await run_tool("immybot_deployments_get", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def immybot_deployments_create(
        name: Annotated[str, Field(description="Short label, saved as the deployment's notes.", min_length=1)],
        softwareId: SoftwareId,
        targetType: Annotated[TargetKind, Field(description="Computer = one computer, Tenant = all its computers, Group = a computer tag.")],
        targetId: Annotated[int, Field(description="Computer id, tenant id or tag id.", ge=1)],
        desiredState: Annotated[DesiredState, Field(description="Installed, Uninstalled, or Updated (update only where found).")],
        autoUpdate: Annotated[bool, Field(description="With Installed: keep it on the latest version.")] = False,
        description: Annotated[str | None, Field(description="Added to the notes.")] = None,
        softwareType: Annotated[Literal["Global", "Local"], Field(description="Catalog of the software id.")] = "Global",
    ) -> str:
        """Create a deployment: software in a desired state on a computer, tenant or tag.

        Only when the user explicitly asks. It takes effect at the targets' next maintenance; use immybot_deployments_trigger to run it now.
        """

        async def action(client: ImmyBotClient) -> Any:
            if desiredState == "Installed":
                state = "LatestVersion" if autoUpdate else "AnyVersion"
            else:
                state = "NotPresent" if desiredState == "Uninstalled" else "UpdateIfFound"
            target: dict[str, Any] = {
                "Computer": {"targetType": "Computer", "target": str(targetId)},
                "Tenant": {"targetType": "AllForTenant", "tenantId": targetId},
                "Group": {"targetType": "Tag", "target": str(targetId)},
            }[targetType]
            payload = {
                "maintenanceIdentifier": str(softwareId),
                "maintenanceType": f"{softwareType}Software",
                "targetCategory": "Computer",
                "desiredSoftwareState": state,
                "targetEnforcement": "Required",
                "onboardingOnly": False,
                "excluded": False,
                "propagateToChildTenants": False,
            } | target
            created = await client.post("target-assignments", payload)
            new_id = created.get("id") if isinstance(created, dict) else None
            notes = name if not description else f"{name}: {description}"
            if new_id:
                await client.post(f"target-assignments/{new_id}/notes", {"notes": notes})
            return names(mask_parameters(created))

        return await run_tool("immybot_deployments_create", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def immybot_deployments_trigger(deploymentId: DeploymentId, confirm: Confirm = None) -> str:
        """Run one deployment now on its computer or tenant (installs / removes software). Needs confirm: true.

        Only when the user explicitly asks. Tag and filter targets cannot be run from here.
        """

        async def action(client: ImmyBotClient) -> Any:
            assignment = await client.get(f"target-assignments/{deploymentId}")
            if not isinstance(assignment, dict):
                raise ValueError(f"Deployment {deploymentId} was not found.")
            # targetType may arrive as a name or a number; targetTypeName is always text.
            is_computer = assignment.get("targetType") == "Computer" or str(assignment.get("targetTypeName") or "").lower() in (
                "computer",
                "specific computer",
            )
            computers = tenants = None
            if is_computer and str(assignment.get("target") or "").isdigit():
                computers = [int(assignment["target"])]
            elif assignment.get("tenantId"):
                tenants = [int(assignment["tenantId"])]
            else:
                raise ValueError("This deployment targets a group or filter; start maintenance on the computers or tenant instead.")
            where = f"computer {computers[0]}" if computers else f"tenant {tenants[0]}"
            if confirm is not True:
                return not_confirmed(f"Run deployment {deploymentId} ({assignment.get('maintenanceDisplayName') or assignment.get('targetText') or ''}) now on {where}")
            maintenance = compact(
                {
                    "maintenanceIdentifier": assignment.get("maintenanceIdentifier"),
                    "maintenanceType": assignment.get("maintenanceType"),
                    "desiredSoftwareState": assignment.get("desiredSoftwareState"),
                    "maintenanceTaskMode": assignment.get("maintenanceTaskMode"),
                    "semanticVersion": assignment.get("softwareSemanticVersion"),
                }
            )
            return await run_immy_service(
                client,
                computer_ids=computers,
                tenant_ids=tenants,
                maintenance=maintenance,
                deploymentId=deploymentId,
                deploymentType=assignment.get("databaseType") or "Local",
            )

        return await run_tool("immybot_deployments_trigger", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_deployments_compliance(deploymentId: DeploymentId) -> str:
        """Compliance of one deployment: latest result per computer (success / failed / pending counts)."""

        async def action(client: ImmyBotClient) -> dict:
            params = dx_params(1000, [["assignmentId", "=", deploymentId]], sort_desc="createdDateUTC")
            rows = as_list(await client.get("maintenance-actions/dx", params))
            latest: dict[Any, dict] = {}
            for row in rows:  # newest first: keep the first action seen per computer
                latest.setdefault(row.get("computerId"), row)
            counts = Counter(str(enum_name(r.get("result"), ACTION_RESULT)) for r in latest.values())
            failing = [
                compact(
                    {
                        "computer_id": r.get("computerId"),
                        "computer_name": r.get("computerName"),
                        "result": enum_name(r.get("result"), ACTION_RESULT),
                        "reason": r.get("resultReasonMessage"),
                        "detected_version": r.get("detectedVersionString"),
                        "when": r.get("createdDateUTC"),
                    }
                )
                for r in latest.values()
                if enum_name(r.get("result"), ACTION_RESULT) != "Success"
            ]
            return {
                "deployment_id": deploymentId,
                "computers": len(latest),
                "results": dict(counts),
                "not_compliant": failing[:100],
                "actions_scanned": len(rows),
            }

        return await run_tool("immybot_deployments_compliance", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_deployments_for_computer(computerId: ComputerId) -> str:
        """List the deployments that apply to a computer, with the latest action and result for each."""

        async def action(client: ImmyBotClient) -> dict:
            return await latest_actions_for_computer(client, computerId)

        return await run_tool("immybot_deployments_for_computer", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def immybot_deployments_for_software(softwareId: SoftwareId) -> str:
        """List the deployments of one software item and their targets."""

        async def action(client: ImmyBotClient) -> dict:
            rows = [
                r
                for r in await all_assignments(client)
                if str(r.get("maintenanceIdentifier")) == str(softwareId) and r.get("maintenanceType") in _SOFTWARE_TYPES
            ]
            return assignments_view(rows, 200)

        return await run_tool("immybot_deployments_for_software", client_factory, action)
