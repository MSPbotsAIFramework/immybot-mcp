# PRD-21665 · Code review

## Round 1 · 2026-10-29 · reviewed dev/PRD-21665 @ 4abb413 (base main @ b61a439)

Verdict: approved

### Findings

No must-fix found.

1. [suggestion] src/immybot_mcp/tools/scripts.py:146-150 — `payload` still includes the stored script's `id` field (via `_RUN_FIELDS`) inside the `body` object sent to ImmyBot. This is unchanged pre-existing behavior (not introduced by this diff) and the vendor's own error text only complained about the top-level key name, not this field, so it is not a must-fix. Worth a follow-up only if a future live call surfaces a new vendor complaint about it.
2. [suggestion] tests/test_api_client.py:424-434 — `test_script_run_executes_global_script` and `test_script_run_cancellation_id_is_unique_per_call` duplicate the `Recorder` setup from the adjacent test almost verbatim (same `SCRIPT` stub, same scriptId/computerId). A small shared fixture would reduce repetition, but the duplication is local to one test file and doesn't affect correctness.

### Review notes (verification performed)

- Diff scope confirmed: `git diff b61a439...HEAD` touches only `src/immybot_mcp/tools/scripts.py`, `tests/test_api_client.py`, and the two `docs/tickets/PRD-21665.*` files — matches the Tech design's Change list exactly, no scope creep.
- Correctness: the two-line fix (`"script"` → `"body"` top-level key, `f"mcp-{scriptId}-{computerId}"` → `str(uuid.uuid4())`) directly matches both literal vendor error strings quoted in the ticket and in the design's "Current state" section. Verified by reading `scripts.py:114-156` in full, not just the diff hunk.
- AC2 (no script body leakage): confirmed `not_confirmed()` (`_common.py`) and the new assertions (`SCRIPT["action"] not in json.dumps(preview/result)`) are unchanged / correctly cover this; re-read `_common.py:210-215` to confirm the preview path was never touched by this diff.
- AC5 docstring change: in scope per the Tech design and Product design (explicitly called out, not an unrelated drive-by edit); wording keeps `confirm: true` unchanged and only adds the optional-review sentence — matches TC7's evidence.
- Credentials: `api_client.py` builds the `Authorization` header per request from the caller's own credentials (`api_client.py:39-42,206`); this ticket's diff does not touch credential handling, logging, or persistence. No regression.
- Independently re-ran the gate on `dev/PRD-21665 @ 4abb413` in a fresh worktree: `uv sync` (clean, no dependency change) then `uv run pytest -q` → **477 passed, 11 skipped**, 0 failed — matches the Self-test section exactly.
- README Connector section: extracted the section from `README.md` and diffed byte-for-byte against `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md` — identical (diff exit 0). Untouched by this ticket, as expected.
- Chinese-character scan (`grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .`): clean, no hits.
- `mcppub`/vendor-registration surface, tool parameter signature (`scriptId, computerId, parameters, timeout, runAs, databaseType, confirm`), and error-envelope path (`_common.py:237-264`) are all unchanged — confirmed by reading the full function, not inferring from the diff.
- Test coverage: TC1/TC3/TC4/TC5/TC6 are automated and independently re-run (pass); TC2/TC8 are correctly left `untested · needs a real vendor account` per `mcp-track.md` §2.5/§3, which does not block merge/INT publish.
- No schema/migration, no new dependency, no new credential field — matches Tech design and Reuse & cleanup section.

### Status: frozen @ 4abb413
