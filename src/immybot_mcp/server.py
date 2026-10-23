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
"""FastMCP factory and the per-request credential middleware."""

import contextvars
import re
import uuid
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ._arguments import EnvelopeFastMCP
from .api_client import ImmyBotClient, ImmyBotCredentials
from .config import INSTANCE_DOMAIN, Settings

HEADER_SUBDOMAIN = "X-Immybot-Instance-Subdomain"
HEADER_TENANT_ID = "X-Immybot-Tenant-Id"
HEADER_CLIENT_ID = "X-Immybot-Client-Id"
HEADER_CLIENT_SECRET = "X-Immybot-Client-Secret"
REQUIRED_HEADERS = [HEADER_SUBDOMAIN, HEADER_TENANT_ID, HEADER_CLIENT_ID, HEADER_CLIENT_SECRET]

_PLACEHOLDER = re.compile(r"^\$\{.*\}$")
_SUBDOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_TENANT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,253}[A-Za-z0-9])?$")

# Per-request isolation: the middleware sets these for the duration of one
# HTTP request and resets them in `finally`. Nothing credential-related is
# ever stored at module level (the token cache is keyed by a hash of the full
# credential set).
_credentials_var: contextvars.ContextVar[ImmyBotCredentials | None] = contextvars.ContextVar(
    "immybot_credentials", default=None
)
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("immybot_request_id", default="-")

INSTRUCTIONS = (
    "ImmyBot automates Windows endpoint setup and software maintenance for MSPs. "
    "Tenants are the MSP's clients; computers belong to tenants; deployments "
    "(target assignments) say which software or maintenance task should be in "
    "which state on which targets; maintenance sessions apply them on a "
    "computer and record per-item actions and logs.\n"
    "Usage:\n"
    "- Find a machine: immybot_computers_search(query) -> immybot_computers_get.\n"
    "- What failed: immybot_maintenance_sessions_list(status='Failed') -> "
    "immybot_maintenance_sessions_results / _logs.\n"
    "- Client health: immybot_tenants_compliance, immybot_tenants_stats.\n"
    "- Scripts and software have separate Global and Local catalogs whose ids "
    "can collide; pass databaseType / softwareType when you know it.\n"
    "Starting maintenance, installing software, running scripts and running a "
    "deployment change endpoints: they need confirm: true after the user "
    "approved that exact action. Other writes (create deployment, cancel / "
    "resume a session, re-inventory) only when the user explicitly asks.\n"
    "The immybot_tasks_* tools and a few others have no ImmyBot API behind "
    "them; they return an error naming the tool to use instead."
)


def get_client_from_context() -> ImmyBotClient | None:
    """The client for the current request, or None outside a request."""
    credentials = _credentials_var.get()
    if credentials is None:
        return None
    return ImmyBotClient(credentials)


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or _PLACEHOLDER.match(text):
        return None
    return text


def normalize_subdomain(value: str) -> str | None:
    """'examplemsp', 'examplemsp.immy.bot' or 'https://examplemsp.immy.bot/' -> 'examplemsp'; None when invalid."""
    text = value.strip().lower()
    text = re.sub(r"^https?://", "", text).split("/", 1)[0]
    suffix = "." + INSTANCE_DOMAIN
    if text.endswith(suffix):
        text = text[: -len(suffix)]
    return text if _SUBDOMAIN.match(text) else None


def _error(scope: Scope, receive: Receive, send: Send, status: int, error: str, message: str):
    return JSONResponse({"error": error, "message": message, "required_headers": REQUIRED_HEADERS}, status_code=status)(
        scope, receive, send
    )


class GatewayCredentialsMiddleware:
    """Reads the ImmyBot / Entra credentials on /mcp requests into the request context."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        values = {h: _clean(request.headers.get(h)) for h in REQUIRED_HEADERS}
        missing = [h for h, v in values.items() if not v]
        if missing:
            await _error(scope, receive, send, 401, "Missing credentials", f"Missing header(s): {', '.join(missing)}")
            return
        subdomain = normalize_subdomain(values[HEADER_SUBDOMAIN])
        if subdomain is None:
            await _error(scope, receive, send, 400, "Invalid credentials", f"{HEADER_SUBDOMAIN} must be the instance name, e.g. examplemsp")
            return
        if not _TENANT.match(values[HEADER_TENANT_ID]):
            await _error(scope, receive, send, 400, "Invalid credentials", f"{HEADER_TENANT_ID} must be an Entra tenant id or domain")
            return

        request_id = (request.headers.get("x-request-id") or "").strip()[:64] or uuid.uuid4().hex[:12]
        credentials = ImmyBotCredentials(subdomain, values[HEADER_TENANT_ID], values[HEADER_CLIENT_ID], values[HEADER_CLIENT_SECRET])
        creds_token = _credentials_var.set(credentials)
        rid_token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _credentials_var.reset(creds_token)
            request_id_var.reset(rid_token)


def create_mcp_server(settings: Settings | None = None) -> FastMCP:
    """Build the FastMCP server and register every tool."""
    mcp = EnvelopeFastMCP(
        name="immybot-mcp",
        instructions=INSTRUCTIONS,
        # The service sits behind the gateway, so Host is never localhost;
        # DNS-rebinding protection would reject those requests with 421.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
    )

    client_factory: Callable[[], ImmyBotClient | None] = get_client_from_context

    from .tools import computers, deployments, maintenance_sessions, navigation, scripts, software, tasks, tenants

    for module in (navigation, computers, deployments, maintenance_sessions, scripts, software, tasks, tenants):
        module.register(mcp, client_factory)

    return mcp
