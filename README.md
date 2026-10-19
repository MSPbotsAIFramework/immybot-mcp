# ImmyBot MCP Server

An [MCP](https://modelcontextprotocol.io) server for the [ImmyBot](https://www.immy.bot) API (v1),
the endpoint setup and software maintenance automation platform MSPs use for Windows
fleets. It lets an AI agent read tenants, computers and their inventory, deployments (target
assignments) and their compliance, maintenance sessions with per-item results and logs, scripts
and the software catalogs and, on explicit request with confirmation, start maintenance, install
software, run a deployment or run a script on a computer.

- Transport: MCP Streamable HTTP at `POST /mcp`, health probe at `GET /health`
- Stateless and multi-tenant: credentials arrive on every request as HTTP headers and are
  never stored; every tool is listed from the first `tools/list`
- Python 3.12, [uv](https://docs.astral.sh/uv/), FastMCP, httpx
- License: Apache-2.0, Copyright 2026 MSPbots.ai

## Authentication headers

| Header | Required | Type | Default | Allowed values | Description | Example |
|---|---|---|---|---|---|---|
| `X-Immybot-Instance-Subdomain` | Yes | string | none | instance name (a full `https://<name>.immy.bot` URL is accepted) | The `examplemsp` in `https://examplemsp.immy.bot` | `examplemsp` |
| `X-Immybot-Tenant-Id` | Yes | string | none | GUID or Entra domain | Microsoft Entra directory (tenant) id of the app registration, not an ImmyBot tenant id | `00000000-0000-0000-0000-000000000000` |
| `X-Immybot-Client-Id` | Yes | string | none | GUID | Application (client) id of the Entra app registration | `00000000-0000-0000-0000-000000000000` |
| `X-Immybot-Client-Secret` | Yes | string | none | - | Client secret value of that app registration | `your-client-secret` |

Where to get them (per ImmyBot's API documentation): register an app in Microsoft Entra ID,
create a client secret (copy its value), then in ImmyBot add the app's enterprise application
object id as a person ("AD External ID") and make that user an admin.

How they are used: the server requests a token from
`https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token` with the client-credentials grant
and scope `https://{subdomain}.immy.bot/.default`, then calls
`https://{subdomain}.immy.bot/api/v1/...` with `Authorization: Bearer`. Tokens are cached in
memory, keyed by a SHA-256 of the full credential set, and refreshed once on a 401.

A request to `/mcp` without all four headers gets HTTP 401 naming the missing ones; an invalid
subdomain or tenant value gets HTTP 400.

## Tools

All tools return a JSON string. **write** marks tools that change data; **confirm** marks tools
that change endpoints and also need `confirm: true`; **n/a** marks tools kept for compatibility
that have no ImmyBot API behind them (they return an `invalid_argument` error naming the tool
to use instead).

| Area | Tools |
|---|---|
| Overview | `immybot_navigate` (**domain**), `immybot_back`, `immybot_status` |
| Computers | `immybot_computers_list` (tenantId, isOnline, operatingSystem, search, skip, limit), `immybot_computers_get` (**computerId**), `immybot_computers_search` (**query**), `immybot_computers_inventory` (**computerId**), `immybot_computers_deployments` (**computerId**); **write**: `immybot_computers_trigger_checkin` (**computerId**; re-inventory); **n/a**: `immybot_computers_create` |
| Deployments | `immybot_deployments_list` (targetType, targetId, softwareId, desiredState), `immybot_deployments_get` (**deploymentId**), `immybot_deployments_compliance` (**deploymentId**), `immybot_deployments_for_computer` (**computerId**), `immybot_deployments_for_software` (**softwareId**); **write**: `immybot_deployments_create` (**name**, **softwareId**, **targetType**, **targetId**, **desiredState**); **confirm**: `immybot_deployments_trigger` (**deploymentId**) |
| Maintenance sessions | `immybot_maintenance_sessions_list` (computerId, tenantId, status, startDate, endDate), `_get` (**sessionId**), `_logs` (**sessionId**), `_results` (**sessionId**), `_active`, `_summary` (tenantId, startDate, endDate); **write**: `_cancel` (**sessionId**), `_resume` (**sessionId**); **confirm**: `_start` (computerId or tenantId, detectionOnly); **n/a**: `_pause` |
| Scripts | `immybot_scripts_list` (category, isGlobal, search, language), `_get` (**scriptId**, databaseType), `_search` (**query**), `_categories`, `_validate` (**content**); **confirm**: `_run` (**scriptId**, **computerId**, parameters, timeout, runAs); **n/a**: `_execution_history`, `_execution_result` |
| Software | `immybot_software_list_global`, `_list` (isGlobal, search), `_get` (**softwareId**, softwareType), `_search` (**query**), `_versions`, `_latest_version`, `_stats` (**softwareId**); **confirm**: `_install` (**softwareId**, computerIds or tenantId); **n/a**: `_categories`, `_publishers` |
| Tenants | `immybot_tenants_list` (search, status), `_get`, `_search` (**query**), `_stats`, `_computers`, `_deployments`, `_compliance`, `_software_inventory` (all **tenantId**) |
| Tasks | **n/a**: all 15 `immybot_tasks_*` tools (ImmyBot has no task queue; use maintenance sessions) |

Errors come back as a JSON envelope instead of an exception:

```json
{"error": {"code": "unauthorized", "message": "Microsoft Entra rejected the client credentials (HTTP 401): invalid_client: AADSTS7000215: Invalid client secret provided.", "retryable": false}}
```

`code` is one of `not_configured`, `unauthorized`, `not_found`, `invalid_argument`,
`rate_limited`, `upstream_error`. Reads are retried with backoff on 429, 5xx and network
errors; writes only on 429.

## Run locally

```bash
uv sync
uv run python -m immybot_mcp          # listens on 0.0.0.0:8080
```

or with Docker:

```bash
docker build --platform linux/amd64 -t immybot-mcp:dev .
docker run --rm -p 8080:8080 immybot-mcp:dev
```

Configuration (environment variables, all optional): `MCP_HTTP_HOST` (default `0.0.0.0`),
`MCP_HTTP_PORT` (default `8080`), `LOG_LEVEL` (default `INFO`). Credentials are never read
from the environment.

## Testing example

```bash
# list tools
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Immybot-Instance-Subdomain: examplemsp" \
  -H "X-Immybot-Tenant-Id: 00000000-0000-0000-0000-000000000000" \
  -H "X-Immybot-Client-Id: 00000000-0000-0000-0000-000000000000" \
  -H "X-Immybot-Client-Secret: your-client-secret" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# failed maintenance sessions
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Immybot-Instance-Subdomain: examplemsp" \
  -H "X-Immybot-Tenant-Id: 00000000-0000-0000-0000-000000000000" \
  -H "X-Immybot-Client-Id: 00000000-0000-0000-0000-000000000000" \
  -H "X-Immybot-Client-Secret: your-client-secret" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"immybot_maintenance_sessions_list","arguments":{"status":"Failed","limit":10}}}'
```

Unit tests (no network access needed):

```bash
uv run pytest
```

## Delivery notes

- **Tool count (68).** Kept as is because the tool names are an existing contract.
- **Token scope fixed.** ImmyBot's Entra application uses the instance URL as its App ID URI,
  so the token scope is `https://{subdomain}.immy.bot/.default`. Older versions requested
  `api://{client_id}/.default`, a token ImmyBot does not accept.
- **Routes follow the ImmyBot API.** Deployments are `/target-assignments`; sessions are
  listed through the `/maintenance-sessions/dx` grid and their items through
  `/maintenance-actions/dx`; maintenance starts through `/run-immy-service`; scripts run through
  `/scripts/run`; scripts and software have separate `local` and `global` catalogs (ids can
  collide, so `databaseType` / `softwareType` can be passed; otherwise Local is tried, then
  Global). Older versions called many routes that do not exist.
- **No API, kept for compatibility (21 tools).** ImmyBot has no task queue (all 15
  `immybot_tasks_*`), no API to create computers (agents register them), no pause for sessions,
  no stored script runs (`_execution_history` / `_execution_result`; `immybot_scripts_run`
  returns the output) and no software categories or publishers. These tools return an
  `invalid_argument` error that names the tool to use.
- **Compliance and stats from real data.** `immybot_deployments_compliance` reads the latest
  action per computer for the deployment, `immybot_tenants_compliance` the tenant's
  non-compliant actions, `immybot_software_stats` the success / failure counts per version.
- **Parameters the API cannot honour were removed**: `status` on computers / deployments /
  scripts lists, `category` / `publisher` / `status` on software lists and search, `autoUpdate`
  on install. New optional parameters: `search` / `skip` on computers, `databaseType` /
  `softwareType`, `detectionOnly` on maintenance start, `allowReboot` on install.
- **Confirmation for endpoint changes.** Starting maintenance, installing software, running a
  deployment and running a script take `confirm: true` and otherwise return a "not done"
  result describing the action.
- **Secrets stay out of results.** ImmyBot returns task parameter values in clear text;
  parameters whose names look secret (password, secret, token, API key ...) are masked, session
  job arguments are left out of `immybot_maintenance_sessions_get`, and logs omit script bodies
  and parameters.
- **Script runs** are synchronous; the wait is capped at 95 seconds (script `timeout` max 90)
  to stay inside the gateway's tool-call limit.

## License

Apache License 2.0 - see [LICENSE](LICENSE) and [NOTICE](NOTICE).
