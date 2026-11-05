# PRD-21588 · Code review

## Round 1 · 2026-11-05 · reviewed dev/PRD-21588 @ fd30dce (base a5abd1c)

Status: frozen @ fd30dce

Verdict: approved

### Findings
1. [suggestion] src/immybot_mcp/tools/computers.py:33 — the new `PersonId` import is inserted between `PageLimit` and `OptionalTenantId`, breaking this block's existing alphabetical order (`O` should sort before `P`). Cosmetic only, no behavior change; not worth a round-trip.

### Notes

- Scope: single repo (`MSPbotsAIFramework/immybot-mcp`), one new tool `immybot_computers_set_primary_user` in `computers.py`, a supporting `PersonId` type in `_common.py`, a `navigation.py` domain-list entry, README table/count update, and matching tests. No cross-repo dependency, `Release order: any`.
- Correctness: body construction (`{"primaryPersonId", "providerLinkUpdates": []} | compact({...})`) correctly omits `onboardingStatus`/`additionalPersonIds` when absent (AC4) and includes them when given (AC2/AC3), verified against `tests/test_api_client.py`'s four new tests. Error path reuses the existing `run_tool`/`ImmyBotError` → structured envelope mechanism unchanged (AC5).
- Reuse: calls the already-implemented `ImmyBotClient.put()` (first caller); reuses `compact`/`names`/`drop`/`run_tool` helpers already imported in this file. No new dependency.
- Tests: TC1-TC7 automated and passing (`uv run pytest -q`: 528 passed, 11 skipped, 0 failed, same skip count as pre-existing baseline on `main`). TC8 is correctly marked `manual`/`untested` with a stated reason (needs a real ImmyBot tenant/credentials) per `mcp-track.md` §2.5/§3 — does not block.
- Merge conflict (PRD-21587/21589/21591 landed on `main` concurrently, all three appending to the same `computers.py` insertion point): resolved as a pure textual collision — both sides' tools kept unchanged, no `--ours`/`--theirs` shortcut, tool count correctly reconciled to 72. Verified by re-running the full suite on the merged tree (528 passed, 11 skipped) and a local smoke test confirming all 72 tool names present. Per-block rationale is documented in `docs/tickets/PRD-21588.md` "Self-test" section.
- Baseline freshness: `[DEV]` stub claims sync with `main @ a5abd1c`; `origin/main` HEAD is independently confirmed at `a5abd1c` at review time — no staleness, no refetch needed before merge.
- MCP standards (`mcp-track.md` §4.3): credential handling unaffected (no new header reads, no shared/cached state); tool name/params/return/errors match tech design; README Connector section diff is confined to the Computers table row and tool-count bullet (template section untouched); no Chinese introduced by this ticket's commits (`grep` over `src/`, `tests/`, `README.md` is clean — the two Chinese fragments present are quoted verbatim from the ticket's own Chinese requirement text inside `docs/tickets/PRD-21588.md`, the same quoting pattern already used in this repo's prior ticket doc `PRD-21665.md`, not new content introduced here).
- No schema/migration, no `mspack publish`, no direct push to a release/INT branch, no dependency additions without justification — none of REVIEW.md §2's BLOCKER conditions apply.

No must-fix found. Proceeding to merge into `main`, INT publish, and the connector wiki check per `mcp-track.md` §4.4.
