# PRD-21591 · Code review

Status: frozen @ b27cbff

## Round 1 · 2026-10-31 · reviewed dev/PRD-21591 @ b27cbff (base main @ 945f547)

Verdict: approved

### Findings

No must-fix, no suggestions.

### Notes

- Scope: single file `src/immybot_mcp/tools/computers.py` (+ `navigation.py` tool-discovery list, `README.md` tool table row, `tests/test_tools.py` contract table, new `tests/test_computers_delete.py`). Matches the Tech design's Change list exactly, with one addition (`navigation.py`) that the design itself flagged in Self-test as missed-then-caught-by-its-own-gate.
- Implementation mirrors the two existing confirm-gated destructive tools (`immybot_deployments_trigger`, `immybot_software_install`) and reuses `ImmyBotClient.post()`, `DESTRUCTIVE` annotation, `Confirm` type, `not_confirmed()`, `run_tool()`, `MAX_PAGE_LIMIT` — no new dependency, no new mechanism.
- AC1-AC8 (ac.json TC-ICD-001/003-008) verified independently: `uv sync && uv run pytest -q` on `dev/PRD-21591@b27cbff` → 518 passed, 11 pre-existing skipped, 0 failed, matching the Self-test section exactly. TC-ICD-002 correctly deferred as `manual`/`blocked` (needs a real ImmyBot tenant; not a gate per `mcp-track.md` §2.5/§3).
- Credential handling: unchanged — `client_factory()` reads per-request headers, no new logging, no secret ever enters the confirm-gate error text (only ids).
- Merge commit `3c38602` (sync with `main` after PRD-21587/PRD-21589 landed): reviewed the conflict resolution directly in `computers.py`, `navigation.py`, `README.md`, `tests/test_tools.py` — both upstream tool additions and this ticket's tool are all present, no side's change was dropped, tool count correctly bumped to 71. Resolution matches the account given in the Self-test section.
- No Chinese in code/tests/README (scan re-run, clean). README Connector section untouched by this diff.
- No DB/migration in this repo (stateless connector) — not applicable.
- No parameter stacking, no dead code introduced; nothing in `computers.py`/`navigation.py`/`tests/test_tools.py` left unclean.

Reviewed by: dev01 (independent code review, no design/dev context reused beyond the frozen ticket doc).
