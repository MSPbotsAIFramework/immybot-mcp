# PRD-21587 · Code review

Status: frozen @ 5fc3124

## Round 1 · 2026-10-31 · reviewed dev/PRD-21587 @ 5fc3124 (base main @ cfc9181)

Verdict: approved

### Scope

`git diff cfc9181...5fc3124`: `src/immybot_mcp/tools/scripts.py`, `src/immybot_mcp/tools/navigation.py`, `tests/test_api_client.py`, `tests/test_tools.py`, `tests/contract_types.json`, `README.md`, `docs/tickets/PRD-21587.md`, `docs/tickets/PRD-21587.ac.json`. No changes outside this ticket's scope.

### Verification performed

- Re-ran the repo's own gate independently (not trusting the dev leg's report): `uv sync && uv run pytest -q` on `5fc3124` → `500 passed, 11 skipped`, 0 failed — matches the Self-test section's claim (baseline 477/11 on pristine `cfc9181`).
- `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .` → one pre-existing hit in `docs/tickets/PRD-21665.md:175` (a quoted Chinese phrase inside a frozen doc from a prior ticket, not touched by this diff). No Chinese text introduced by this ticket.
- README "MSPbots Connector" section (lines 18-87) diffed against `vendor-mcp-development/reference/readme-connector-section.md`: has pre-existing drift (missing the `<div align="center">` wrapper, one extra blank line), but this section is not touched by this diff (`git diff` only touches lines 120, 185, 222+) — out of this ticket's review scope, not a regression introduced here.
- Confirmed commit authorship on all 4 commits (`89ebeb4`, `18a0df4`, `0976a71`, `5fc3124`) is `Dev01.MBAgent <dev01.mbagent@mspbots.ai>` for both author and committer.
- Confirmed `main` has not moved since the design/dev legs read it (`origin/main` still `cfc9181` at review time) — no base re-sync needed before merge.
- Read `docs/tickets/PRD-21587.md` (product design, tech design, Self-test, Handoff) and `docs/tickets/PRD-21587.ac.json` in full; cross-checked each TC's cited test name exists and is part of the 500 passing.

### Findings

No must-fix.

1. [suggestion] `src/immybot_mcp/tools/scripts.py:117` (ticket description) vs the implementation: the reporter's own payload listed `script.scriptType` (1) and `tenantId` as possible fields; neither is sent by `immybot_scripts_run_adhoc`. This mirrors the existing `immybot_scripts_run`'s `_RUN_FIELDS` (`scripts.py:54-57`), which also omits `scriptType`, and the tech design explicitly scopes out `tenantId` as a non-goal with a stated reason (no evidence of a tenant-wide ad-hoc endpoint). Not a must-fix: it is a documented, consistent extension of an already-shipped contract, not a new unverified assumption introduced by this diff.
2. [suggestion] `docs/tickets/PRD-21587.md` Open questions section already flags that the id-less `body` shape is inferred, not spec-confirmed against a live instance (no vendor OpenAPI spec available, TC10 deferred as "needs a real vendor account"). This is correctly surfaced as a non-blocking assumption per `mcp-track.md` §2.5/§3 and does not need any change before merge; noting it here only so the reviewer's reasoning is traceable.

### Conclusion

Implementation matches the tech design precisely (reuses `ValidateLanguage`, `enum_value()`, `not_confirmed()`, `ComputerId`/`Confirm`, `_RUN_READ_TIMEOUT`, the `runAs`→`scriptExecutionContext` mapping, and `run_tool()`'s error envelope — all unchanged). Confirm-gate, structured errors, no credential/script-content logging, and README/tool-count/contract-pin updates are all present and internally consistent. Test evidence in `.ac.json` is independently reproducible (re-ran the full suite myself). TC10 is the only non-automated case and is correctly deferred per policy (missing vendor account does not block `6b`). No scope creep, no new dependency, no schema/migration (none in this repo). Approved for merge into `main`, INT publish, and connector wiki check.
