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
"""Async client for the ImmyBot REST API (v1) with Microsoft Entra client-credentials auth."""

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any

import httpx

from ._json import error_envelope
from .config import INSTANCE_DOMAIN, TOKEN_URL

logger = logging.getLogger("immybot_mcp.api")

_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_MAX_RETRIES = 2
_MAX_BACKOFF_SECONDS = 20.0
# Whole-call budget including retries; the gateway times a tool call out at 120s.
_CALL_BUDGET_SECONDS = 100.0
_TOKEN_REFRESH_MARGIN_SECONDS = 120.0

# One connection pool for the process. It never holds credentials: the
# Authorization header is built per request from the caller's own token, so
# sharing the pool across tenants is safe.
_shared_http_client: httpx.AsyncClient | None = None

# Access tokens keyed by a SHA-256 of the full credential set (secret included),
# so a token is only ever reused by a caller holding the exact same credentials.
_token_cache: dict[str, tuple[str, float]] = {}


class _RejectAllCookies(DefaultCookiePolicy):
    """Never store or send a cookie: the HTTP client is shared by every tenant."""

    def set_ok(self, cookie, request) -> bool:  # noqa: ANN001 - stdlib signature
        return False

    def return_ok(self, cookie, request) -> bool:  # noqa: ANN001 - stdlib signature
        return False


def _no_cookies() -> CookieJar:
    # A plain CookieJar: httpx uses it as is (an httpx.Cookies would be copied into a default jar).
    return CookieJar(policy=_RejectAllCookies())


def _get_shared_http_client() -> httpx.AsyncClient:
    global _shared_http_client
    if _shared_http_client is None:
        _shared_http_client = httpx.AsyncClient(cookies=_no_cookies(), timeout=_TIMEOUT)
    return _shared_http_client


# status_code -> (error code, retryable). 0 means no HTTP response at all
# (connection error or timeout).
_STATUS_TO_CODE: dict[int, tuple[str, bool]] = {
    0: ("upstream_error", True),
    400: ("invalid_argument", False),
    401: ("unauthorized", False),
    403: ("unauthorized", False),
    404: ("not_found", False),
    405: ("invalid_argument", False),
    409: ("invalid_argument", False),
    422: ("invalid_argument", False),
    429: ("rate_limited", True),
}


def classify_status(status_code: int) -> tuple[str, bool]:
    if status_code in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status_code]
    if status_code >= 500:
        return "upstream_error", True
    if status_code >= 400:
        return "invalid_argument", False
    return "upstream_error", True


class ImmyBotError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"ImmyBot API error {status_code}: {message}")

    def to_envelope(self) -> str:
        code, retryable = classify_status(self.status_code)
        return error_envelope(code, self.message, retryable)


@dataclass(frozen=True)
class ImmyBotCredentials:
    subdomain: str
    tenant_id: str
    client_id: str
    client_secret: str

    def __repr__(self) -> str:  # never leak the secret into logs or tracebacks
        return f"ImmyBotCredentials(subdomain={self.subdomain!r}, secret=<redacted>)"

    @property
    def instance_url(self) -> str:
        return f"https://{self.subdomain}.{INSTANCE_DOMAIN}"

    def cache_key(self) -> str:
        raw = "\n".join((self.subdomain, self.tenant_id, self.client_id, self.client_secret))
        return hashlib.sha256(raw.encode()).hexdigest()


class ImmyBotClient:
    """Thin wrapper over the ImmyBot API for one caller's credentials."""

    def __init__(self, credentials: ImmyBotCredentials, http_client: httpx.AsyncClient | None = None):
        self._credentials = credentials
        self._http = http_client
        self.instance_url = credentials.instance_url
        self.base_url = f"{credentials.instance_url}/api/v1"

    # ---- auth -----------------------------------------------------------------

    async def _access_token(self, force_refresh: bool = False) -> str:
        key = self._credentials.cache_key()
        cached = _token_cache.get(key)
        if cached and not force_refresh and cached[1] - _TOKEN_REFRESH_MARGIN_SECONDS > time.monotonic():
            return cached[0]
        creds = self._credentials
        http = self._http or _get_shared_http_client()
        form = {
            "grant_type": "client_credentials",
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            # ImmyBot's Entra application uses the instance URL as its App ID URI.
            "scope": f"{creds.instance_url}/.default",
        }
        try:
            resp = await http.post(TOKEN_URL.format(tenant_id=creds.tenant_id), data=form)
        except httpx.TimeoutException as e:
            raise ImmyBotError(0, "Timed out requesting an access token from Microsoft Entra") from e
        except httpx.RequestError as e:
            raise ImmyBotError(0, f"Network error requesting an access token from Microsoft Entra: {type(e).__name__}") from e
        logger.info("entra_token status=%s", resp.status_code)
        if resp.status_code >= 400:
            raise ImmyBotError(401 if resp.status_code < 500 else resp.status_code, _token_error(resp))
        try:
            payload = resp.json()
            token = payload["access_token"]
            expires_in = float(payload.get("expires_in") or 3600)
        except (ValueError, KeyError, TypeError) as e:
            raise ImmyBotError(502, "Microsoft Entra returned an unexpected token response") from e
        _token_cache[key] = (token, time.monotonic() + expires_in)
        return token

    # ---- requests ---------------------------------------------------------------

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, body: Any = None, params: dict[str, Any] | None = None, read_timeout: float | None = None) -> Any:
        return await self.request("POST", path, params=params, body=body, read_timeout=read_timeout)

    async def put(self, path: str, body: Any = None) -> Any:
        return await self.request("PUT", path, body=body)

    async def patch(self, path: str, body: Any = None) -> Any:
        return await self.request("PATCH", path, body=body)

    async def delete(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request("DELETE", path, params=params)

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: Any = None,
        read_timeout: float | None = None,
    ) -> Any:
        http = self._http or _get_shared_http_client()
        url = f"{self.base_url}/{path.lstrip('/')}"
        query = {k: _param_value(v) for k, v in (params or {}).items() if v is not None}
        timeout = httpx.Timeout(connect=5.0, read=read_timeout, write=10.0, pool=5.0) if read_timeout else None
        token = await self._access_token()
        refreshed = False
        started = time.monotonic()
        attempt = 0
        while True:
            t0 = time.monotonic()
            resp: httpx.Response | None = None
            error: ImmyBotError | None = None
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            try:
                kwargs: dict[str, Any] = {"params": query, "headers": headers}
                if body is not None:
                    kwargs["json"] = body
                if timeout is not None:
                    kwargs["timeout"] = timeout
                resp = await http.request(method, url, **kwargs)
                status = resp.status_code
            except httpx.TimeoutException:
                status, error = 0, ImmyBotError(0, f"Timed out calling ImmyBot ({method} {path})")
            except httpx.RequestError as e:
                status, error = 0, ImmyBotError(0, f"Network error calling ImmyBot ({method} {path}): {type(e).__name__}")

            logger.info(
                "immybot_api method=%s path=%s status=%s ms=%d attempt=%d",
                method, path, status, (time.monotonic() - t0) * 1000, attempt,
            )

            # A cached token can be revoked or the app re-permissioned: fetch a fresh one once.
            if status == 401 and not refreshed:
                refreshed = True
                token = await self._access_token(force_refresh=True)
                continue

            # 429 is refused before processing, so any method may retry it; other
            # failures are retried only for reads, so a write never runs twice.
            retryable = status == 429 or (method == "GET" and (status == 0 or status >= 500))
            if retryable and attempt < _MAX_RETRIES:
                delay = _retry_delay(resp, attempt)
                if time.monotonic() - started + delay < _CALL_BUDGET_SECONDS:
                    attempt += 1
                    await asyncio.sleep(delay)
                    continue
            if error is not None:
                raise error
            assert resp is not None
            if resp.status_code >= 400:
                raise ImmyBotError(resp.status_code, _error_message(resp, path))
            return _parse(resp, path)


def _parse(resp: httpx.Response, path: str) -> Any:
    text = resp.text
    if not text or not text.strip():
        return None
    content_type = resp.headers.get("content-type", "")
    if "html" in content_type or text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        # Unknown routes fall through to the web app, which answers 200 with its HTML shell.
        raise ImmyBotError(404, f"ImmyBot has no API route {path} (it returned the web app page)")
    try:
        return resp.json()
    except ValueError:
        return {"output": text[:20000]}


def _param_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), _MAX_BACKOFF_SECONDS))
            except ValueError:
                pass
    return min(float(2**attempt), _MAX_BACKOFF_SECONDS)


def _token_error(resp: httpx.Response) -> str:
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    code = payload.get("error") if isinstance(payload, dict) else None
    description = payload.get("error_description") if isinstance(payload, dict) else None
    # Entra appends trace / correlation ids and a timestamp; keep only the explanation.
    first_line = re.split(r"\s*Trace ID:", str(description).splitlines()[0])[0][:300] if description else ""
    detail = ": ".join(x for x in (code, first_line) if x)
    return f"Microsoft Entra rejected the client credentials (HTTP {resp.status_code})" + (f": {detail}" if detail else "")


def _error_message(resp: httpx.Response, path: str) -> str:
    fallback = f"ImmyBot returned HTTP {resp.status_code} for {path}"
    try:
        payload = resp.json()
    except ValueError:
        text = resp.text.strip()
        if text.lower().startswith("<"):
            return fallback  # an HTML error page, not useful to the agent
        return f"{fallback}: {text[:300]}" if text else fallback
    message: Any = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code")
        else:
            message = error or payload.get("message") or payload.get("detail") or payload.get("title")
        errors = payload.get("errors")
        if isinstance(errors, dict) and errors:
            details = "; ".join(f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}" for k, v in errors.items())
            message = f"{message}: {details}" if message else details
    elif isinstance(payload, str):
        message = payload
    if message:
        return f"{fallback}: {str(message)[:500]}"
    return fallback
