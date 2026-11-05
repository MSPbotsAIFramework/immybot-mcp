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

### Fixes (round 1)

Only the must-fix item above was changed; no other behavior touched.

1. **`src/immybot_mcp/tools/persons.py:34-40`** (`fcc49e8`'s parent, `8d868e7`) — `action()` now keeps the raw vendor rows (`raw_rows`) separate from the client-side tenant-filtered `rows`, and derives `has_more` from the vendor's `totalCount` (`total > limit`) instead of relying on `listing()`'s default `len(items) > limit`, which can never fire once the request caps the response at `take=<limit>`. Falls back to `len(raw_rows) >= limit` when `totalCount` is absent, mirroring `immybot_maintenance_sessions_list` (`maintenance_sessions.py:110`).
2. **`tests/test_api_client.py`** (same commit) — `test_persons_list_caps_at_limit_and_sets_has_more`'s stub now honors `take` (returns `rows[:take]` with the real `totalCount`), matching the real vendor's DevExtreme `/dx` contract instead of returning more rows than requested. Added `test_persons_list_no_more_when_total_within_limit` (totalCount == rows returned ⇒ `has_more` False) so the fix is checked both ways, not just flipped to always-True.
3. **Re-sync required**: `origin/main` had moved from `a5abd1c` (this round's reviewed base) to `445a57a` (PRD-21588's `immybot_computers_set_primary_user` merged in the meantime). Merged clean (`a8db521`), per `mcp-track.md` §3.2 step 6.
4. **Unplanned fix found by re-running gates after the sync** (`fcc49e8`): the clean, non-conflicting auto-merge of `tests/test_tools.py` and `README.md` left a stale tool-count assertion (`72`) against the actual merged, registered count (`73` — PRD-21588's tool + this ticket's `immybot_persons_list`). `uv run pytest -q` caught it (`test_tool_names_are_stable` failed `73 == 72`); corrected both the assertion and the README "Tool count" line to `73`. Not a must-fix item, but required to keep gates green on the synced code (same discipline the design doc's "unplanned fix" note already documents for the 70→72 case).

**Retest** (`TESTED=fcc49e8`, synced with `main@445a57a`):

| Command | Result |
|---|---|
| `uv run pytest -q` | 537 passed, 11 skipped, 0 failed |
| `uv run pytest -q -k persons -v` | 10 passed (TC1–TC5 incl. the new TC4 case, plus `test_tool_names_are_stable`, `test_required_params[immybot_persons_list]`, `test_navigate_lists_every_tool`) |
| Local smoke: `uv run python -m immybot_mcp` (port 19590), `GET /health` | `200` |
| Local smoke: `POST /mcp` `initialize` → `tools/list` with placeholder ImmyBot headers | tool count **73**; `immybot_persons_list` present, `required == ["tenantId"]` |
| Local smoke: same request, headers omitted | `401` |
| Chinese-character scan (`src/ tests/ README.md`) | no output (clean) |
| README Connector section vs `vendor-mcp-development/reference/readme-connector-section.md` | untouched by this fix; still identical (verified round 1) |
| `gitleaks detect` | not installed in this sandbox; skipped |

`docs/tickets/PRD-21590.ac.json` TC4 and TC6 evidence updated to point at `fcc49e8` and the new test. Main ticket doc (`docs/tickets/PRD-21590.md`, frozen @ `959ac83`) is not edited, per `legs/dev.md` S1.

## Round 2 · 2026-11-05 · reviewed dev/PRD-21590 @ 8869d0f (base main @ 445a57a)

Status: frozen @ 8869d0f

Verdict: approved

Scope: the two non-merge commits since round 1 (`8d868e7`, `fcc49e8`) plus the docs commit (`8869d0f`); `a8db521` is a clean merge of `origin/main` (PRD-21588's `immybot_computers_set_primary_user`) carrying no PRD-21590 changes, so its content (`navigation.py`, `_common.py`, `computers.py`, PRD-21588 docs) is out of scope for this review.

### Round 1 fixes verified
1. `src/immybot_mcp/tools/persons.py:34-40` (`8d868e7`) — `has_more` is now `total > limit if isinstance(total, int) else len(raw_rows) >= limit`, overriding `listing()`'s default via the trailing `| {"has_more": has_more}` merge. Matches the `immybot_maintenance_sessions_list` (`maintenance_sessions.py:110`) pattern the must-fix pointed at. Checked the arithmetic against both new tests: `total=3, limit=2` → `has_more=True` (`test_persons_list_caps_at_limit_and_sets_has_more`); `total=2, limit=2` → `has_more=False` (`test_persons_list_no_more_when_total_within_limit`) — the fix is exercised both ways, not just flipped to always-`True`.
2. `tests/test_api_client.py` (`8d868e7`) — `test_persons_list_caps_at_limit_and_sets_has_more`'s stub now honors `take` (`reply()` returns `rows[:take]` with the real `totalCount`), so it exercises the real vendor shape instead of the impossible always-3-rows response round 1 flagged.
3. Unplanned fix (`fcc49e8`) is legitimate, not scope creep: it repairs a silent tool-count collision (`72` vs the actual merged `73`) that the required main re-sync (step above) introduced; `uv run pytest -q` caught it before gates, consistent with `mcp-track.md` §3.2 step 7 discipline.

### Findings
None (no new must-fix; round 1's suggestion #2 on `docs/tickets/PRD-21590.md:232` stands as a repo-wide follow-up, not blocking here).

### Checked, no finding
- Credentials, multi-tenant isolation, error envelope, tool registration/navigation, Tech design conformance, reuse: unchanged since round 1 (the fix only touches the `has_more` derivation), still hold.
- `docs/tickets/PRD-21590.ac.json` ledger validates (`ticket_store.py validate`: 6 cases OK); TC4/TC6 evidence updated to `fcc49e8`/`main@445a57a` and matches the retest table above.
- Chinese-character scan (`src/ tests/ README.md`): clean.
- README Connector section: untouched by round 1 fixes, still identical to `vendor-mcp-development/reference/readme-connector-section.md`.
- No SOP §14 item regressed by this round's changes (no new dependency, no new credential path, no cross-repo header change).

Not re-run: the retest table in "Fixes (round 1)" above (`TESTED=fcc49e8`, 537 passed / 11 skipped / 0 failed) already covers this exact code; nothing changed between `fcc49e8` and `8869d0f` (docs-only commit).
