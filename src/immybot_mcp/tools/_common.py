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
"""Shared argument types, query builders, enum / secret handling and the error-handling wrapper."""

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any, Literal, get_args

from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import ImmyBotClient, ImmyBotError
from ..config import DEFAULT_LIMIT, MAX_LIMIT, MAX_PAGE_LIMIT

logger = logging.getLogger("immybot_mcp.tools")

ClientFactory = Callable[[], ImmyBotClient | None]

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
LOCAL = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
WRITES_IDEMPOTENT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)

NOT_CONFIGURED = error_envelope(
    "not_configured",
    "ImmyBot credentials are missing for this request (X-Immybot-Instance-Subdomain, X-Immybot-Tenant-Id, "
    "X-Immybot-Client-Id, X-Immybot-Client-Secret).",
    False,
)

Limit = Annotated[int, Field(description=f"Maximum records to return (max {MAX_LIMIT}).", ge=1, le=MAX_LIMIT)]
PageLimit = Annotated[int, Field(description=f"Records per page (max {MAX_PAGE_LIMIT}).", ge=1, le=MAX_PAGE_LIMIT)]
Confirm = Annotated[bool | None, Field(description="Must be true, set only after the user approved this exact action.")]
ComputerId = Annotated[int, Field(description="ImmyBot computer id.", ge=1)]
TenantId = Annotated[int, Field(description="ImmyBot tenant id (not the Entra tenant id).", ge=1)]
OptionalTenantId = Annotated[int | None, Field(description="Only this ImmyBot tenant id.", ge=1)]
SessionId = Annotated[int, Field(description="Maintenance session id.", ge=1)]
DateText = Annotated[str | None, Field(description="ISO 8601 date or date-time (UTC).")]
DatabaseType = Annotated[
    Literal["Global", "Local"] | None,
    Field(description="Catalog the id belongs to; global and local ids can collide. Omit to try Local, then Global."),
]

DEFAULT = DEFAULT_LIMIT

# Enum names in API order. ImmyBot serializes these enums as integers in some
# responses and as names in others; names() turns integers into names.
SESSION_STATUS = [
    "Passed", "Running", "Failed", "Created", "Cancelled", "Postponed", "Pending", "PartialPassed",
    "PendingConnectivity", "Missed", "MaxTrackedDevicesPerMonthExceeded", "PendingPreflight",
    "PendingEphemeralAgentConnection", "MaintenanceForTrackableDevicesNotAllowed", "Expired",
]
ACTION_RESULT = ["Pending", "Success", "Failed", "Cancelled", "Indeterminable", "Resolved"]
ACTION_TYPE = [
    "NoAction", "Install", "Update", "Uninstall", "Download", "Reinstall", "Downgrade", "Undetermined",
    "TaskEnforce", "TaskMonitor", "TaskAudit",
]
ACTION_STATUS = [
    "NotStarted", "Downloading", "PerformingAction", "DeterminingResult", "Complete", "WaitingForPrerequisite",
    "DeterminingAction", "Skipped", "PendingExecution",
]
DESIRED_STATE = [
    "NewerOrEqualVersion", "NotPresent", "AnyVersion", "ThisVersion", "OlderOrEqualVersion", "LatestVersion",
    "NoAction", "UpdateIfFound",
]
SCRIPT_CATEGORY = [
    "SoftwareDetection", "SoftwareVersionAction", "MaintenanceTaskSetter", "MetascriptDeploymentTarget",
    "FilterScriptDeploymentTarget", "DeviceInventory", "Function", "ImmySystem", "DynamicVersions",
    "DownloadInstaller", "Module", "Preflight", "Integration",
]
SCRIPT_LANGUAGE = ["CommandLine", "PowerShell"]
DATABASE_TYPE = ["Global", "Local"]

ENUM_FIELDS: dict[str, list[str]] = {
    "sessionStatus": SESSION_STATUS,
    "activeSessionStatus": SESSION_STATUS,
    "onboardingStageStatus": SESSION_STATUS,
    "detectionStageStatus": SESSION_STATUS,
    "executionStageStatus": SESSION_STATUS,
    "agentUpdatesStageStatus": SESSION_STATUS,
    "resolutionStageStatus": SESSION_STATUS,
    "inventoryStageStatus": SESSION_STATUS,
    "result": ACTION_RESULT,
    "actionType": ACTION_TYPE,
    "maintenanceActionStatus": ACTION_STATUS,
    "desiredSoftwareState": DESIRED_STATE,
    "scriptCategory": SCRIPT_CATEGORY,
    "scriptLanguage": SCRIPT_LANGUAGE,
    "databaseType": DATABASE_TYPE,
}

_SECRET_NAME = re.compile(r"pass|secret|token|apikey|api_key|credential|private", re.IGNORECASE)
MASK = "********"


def enum_name(value: Any, names: list[str]) -> Any:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(names):
        return names[value]
    return value


def names(data: Any) -> Any:
    """Recursively replace integer enum values of known fields with their names."""
    if isinstance(data, list):
        return [names(x) for x in data]
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            out[k] = enum_name(v, ENUM_FIELDS[k]) if k in ENUM_FIELDS else names(v)
        return out
    return data


def mask_parameters(data: Any) -> Any:
    """Mask task parameter values whose names look secret (ImmyBot returns them in clear text)."""
    if isinstance(data, list):
        return [mask_parameters(x) for x in data]
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if k in ("taskParameterValues", "parameterOverrides", "scriptParameters", "paramBlockParameters") and isinstance(v, dict):
                out[k] = {pk: (MASK if _SECRET_NAME.search(pk) and pv not in (None, "") else pv) for pk, pv in v.items()}
            else:
                out[k] = mask_parameters(v)
        return out
    return data


def compact(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def drop(record: Any, *keys: str) -> Any:
    if isinstance(record, dict):
        return {k: v for k, v in record.items() if k not in keys}
    return record


def as_list(payload: Any) -> list:
    """Plain arrays, DevExtreme {data: [...]} and paged {results: [...]} all become a list."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "results", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def dx_date(value: str) -> str:
    """ISO 8601 -> the 'MM/dd/yyyy HH:mm:ss' form DevExtreme filters expect."""
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as e:
        raise ValueError(f"Invalid date {value!r}: use ISO 8601, e.g. 2026-10-01 or 2026-10-01T08:00:00Z") from e
    return parsed.strftime("%m/%d/%Y %H:%M:%S")


def dx_params(take: int, filters: list[list[Any]] | None = None, sort_desc: str | None = None, skip: int = 0) -> dict[str, Any]:
    """Query parameters for a DevExtreme /dx grid endpoint."""
    params: dict[str, Any] = {"skip": skip, "take": take, "requireTotalCount": False}
    if filters:
        expression: list[Any] = filters[0] if len(filters) == 1 else []
        if len(filters) > 1:
            for i, f in enumerate(filters):
                if i:
                    expression.append("and")
                expression.append(f)
        params["filter"] = json.dumps(expression)
    if sort_desc:
        params["sort"] = json.dumps([{"selector": sort_desc, "desc": True}])
    return params


def sieve_value(value: str) -> str:
    """Escape the characters Sieve treats as separators inside a filter value."""
    return value.replace("\\", "\\\\").replace(",", "\\,").replace("|", "\\|")


def sieve_params(limit: int, name_contains: str | None = None, page: int = 1) -> dict[str, Any]:
    params: dict[str, Any] = {"Page": page, "PageSize": limit}
    if name_contains:
        params["Filters"] = f"name@=*{sieve_value(name_contains)}"
    return params


def listing(key: str, items: list, limit: int, **extra: Any) -> dict:
    shown = items[:limit]
    return compact({key: names(shown), "count": len(shown), "has_more": len(items) > limit} | extra)


def not_confirmed(action: str) -> dict:
    return {
        "done": False,
        "action": action,
        "message": "Not done. Describe this action to the user and call again with confirm: true only after they approve it.",
    }


def unsupported(feature: str, instead: str) -> str:
    return error_envelope(
        "invalid_argument",
        f"The ImmyBot API has no {feature}, so this tool cannot run. {instead}",
        False,
    )


def enum_value(value: Any, choices: Any) -> Any:
    """Canonical spelling of a case-insensitive match in ``choices`` (a Literal type).

    Any other value passes through unchanged, so the API decides (older callers sent free text).
    """
    if not isinstance(value, str):
        return value
    wanted = value.strip().lower()
    return next((c for c in get_args(choices) if isinstance(c, str) and c.lower() == wanted), value)


async def run_tool(
    name: str,
    client_factory: ClientFactory,
    action: Callable[[ImmyBotClient], Awaitable[Any]],
) -> str:
    """Resolve the caller's client, run ``action``, and always return a string.

    Errors never escape as exceptions: they become the standard error envelope.
    """
    client = client_factory()
    if client is None:
        return NOT_CONFIGURED
    started = time.monotonic()
    try:
        result = await action(client)
    except ImmyBotError as e:
        logger.info("tool=%s outcome=error status=%s ms=%d", name, e.status_code, _ms(started))
        return e.to_envelope()
    except ValueError as e:
        logger.info("tool=%s outcome=invalid_argument ms=%d", name, _ms(started))
        return error_envelope("invalid_argument", str(e), False)
    except Exception as e:  # noqa: BLE001 - tools must never raise
        logger.warning("tool=%s outcome=unexpected error=%s ms=%d", name, type(e).__name__, _ms(started))
        return error_envelope("upstream_error", f"Unexpected error: {type(e).__name__}", True)
    logger.info("tool=%s outcome=ok ms=%d", name, _ms(started))
    if result is None:
        result = {"done": True}
    return result if isinstance(result, str) else dump_json_capped(result)


async def get_from_catalog(
    client: ImmyBotClient, kind: str, record_id: int | str, database_type: str | None, suffix: str = ""
) -> tuple[Any, str]:
    """GET /{kind}/local|global/{id}{suffix}; without a database type try Local, then Global."""
    order = [database_type] if database_type else ["Local", "Global"]
    last: ImmyBotError | None = None
    for db in order:
        try:
            return await client.get(f"{kind}/{db.lower()}/{record_id}{suffix}"), db
        except ImmyBotError as e:
            if e.status_code != 404:
                raise
            last = e
    assert last is not None
    raise last


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
