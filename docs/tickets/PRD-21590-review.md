# PRD-21590 · Code review

## Round 1 · 2026-11-05 · reviewed dev/PRD-21590 @ 7d481c0 (base main @ a5abd1c)

Verdict: changes requested

Base taken from the Handoff ("Default branch: `main` @ `a5abd1c`"); `origin/main` is still at `a5abd1c`, so no re-sync is needed. Diff reviewed: `a5abd1c..7d481c0` (`src/immybot_mcp/tools/persons.py` new, `server.py`, `navigation.py`, `README.md`, `tests/test_api_client.py`, `tests/test_tools.py`, ticket docs).

### Findings

1. [must-fix] src/immybot_mcp/tools/persons.py:34-40 — AC4 ("returns at most 50 persons and signals that more exist") cannot be met against the real vendor. The request sends `take=<limit>` (`dx_params(limit, ...)`), so a DevExtreme endpoint that honors `take` returns at most `limit` rows, and `listing()` (`_common.py:205-207`) only sets `has_more` when `len(items) > limit`. With a real ImmyBot instance, `has_more` is therefore always `false`, even though the tool asked for `requireTotalCount` and has `totalCount` in hand. The sibling `/dx` tool already handles this: `immybot_maintenance_sessions_list` overrides it with `| {"has_more": len(rows) >= limit}` (`maintenance_sessions.py:110`). TC4 (`tests/test_api_client.py:384-389`) passes only because its stub ignores `take` and returns 3 rows for `take=2`. Reproduced with a stub that honors `take` (scratch test, run on `7d481c0`: `PYTHONPATH=. uv run pytest -c pyproject.toml scratch/PRD-21590/test_has_more_repro.py -s`):
   `RESULT {'persons': [{'id': 1, ...}, {'id': 2, ...}], 'count': 2, 'has_more': False, 'total': 3}` → `assert False is True` FAILED.
   Fix: derive `has_more` from the vendor's total when present (e.g. `total > len(rows_before_refilter)` / `total > limit`), falling back to `len(rows) >= limit` like `maintenance_sessions.py:110`; and make TC4's stub honor `take` (return `rows[:take]` with `totalCount: 3`) so the test checks the real vendor behavior instead of an impossible response.
2. [suggestion] docs/tickets/PRD-21590.md:232 — the ticket doc quotes the original Chinese ticket text. The MCP rule is "no Chinese in the repo"; the same pattern already exists on `main` (`docs/tickets/PRD-21589.md`, `PRD-21591.md`, `PRD-21665.md`), and code, tests and README are clean, so it is not blocking here. A repo-wide decision (translate quotes in ticket docs) is better handled once, outside this ticket.

### Checked, no finding

- Credentials: unchanged per-request header path through `run_tool()`/`client_factory`; no new logging, no state shared across requests.
- Multi-tenant isolation (AC5): the client-side `tenantId` re-filter (`persons.py:38`) mirrors `computers.py:75`; covered by `test_persons_list_filters_out_other_tenants_defensively`.
- Errors (AC3): vendor 404 goes through `run_tool()` into the standard envelope; covered by `test_persons_list_vendor_error_returns_envelope`.
- Registration/navigation (TC6): `server.py` import + tuple, `navigation.py` `DOMAINS["persons"]` + `Domain` Literal, `EXPECTED_TOOLS` + count 72. The README tool-count 70 → 72 correction is explained in Self-test (a stale value already on `main`).
- Tool name, parameters (`tenantId` required, `limit` 1–500 default 50), `READ_ONLY` annotation and returned fields match the Tech design.
- Reuse: only existing `_common.py` helpers; no new dependency.
