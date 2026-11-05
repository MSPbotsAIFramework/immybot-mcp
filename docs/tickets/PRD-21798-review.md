# PRD-21798 · Code review

## Round 1 · 2026-11-05 · reviewed dev/PRD-21798 @ 095776c (base main @ 97d6961)

Verdict: changes requested

Base: `97d6961` is the default-branch sha named in the Handoff ("Default branch: `main` @ `97d6961`"); `git merge-base origin/main HEAD` returns the same sha.

### Findings

1. [must-fix] docs/tickets/PRD-21798.md:144,188 — the ticket doc adds Chinese text to the repository (`"外部 API 未知"` on line 144, `"有就跑"` on line 188). The MCP review checklist (`mcp-track.md` §4.3) requires no Chinese in the repository, and the Self-test row "Chinese-character scan" (line 186) states "no match in ... this ticket's own `PRD-21798.md`/`.ac.json`", which is false: `grep -nP '[\x{4e00}-\x{9fff}]' docs/tickets/PRD-21798.md` returns exactly these two lines. Fix: replace both phrases with English (e.g. "unknown external API" and "run it if present"), correct the Self-test scan claim with the actual command output, and record the correction in the Fixes section below (line 144 is in the design section, line 188 in the Self-test section; the doc is frozen, so record the edit and its reason explicitly rather than editing silently).
2. [suggestion] src/immybot_mcp/tools/scripts.py:70 — `_ERROR_FIELDS` is an unverified guess (`error`, `errorOutput`, `exceptionMessage`, `exception`); the instance's swagger (`https://mspbotsai.immy.bot/swagger/v1/swagger.json`) returns `401` without credentials, so review could not confirm it either. If the real key is something else (for example `errors` or `errorMessage`), `hadErrors` silently reports `false` on a failing run, which is the exact misleading outcome this ticket exists to prevent. This is not marked must-fix because the design accepted the assumption explicitly (Open questions) and hands it to TC2/TC4 against a live instance. Consider also checking a case-insensitive key match for `error`/`exception` as a fallback, and get TC2 run by someone with vendor access before BA acceptance.
3. [suggestion] src/immybot_mcp/tools/scripts.py:130 — on timeout, `_run_result(running, "Running")` returns `hadErrors: false` even though the run has not finished, so "no errors" really means "not known yet". Callers should already check `timed_out: true`, but omitting `hadErrors` (or documenting the meaning) on timed-out results would be clearer.
4. [suggestion] README.md:224-231 and src/immybot_mcp/tools/scripts.py:198 — the README's "Script runs are queued, then collected" note and the `immybot_scripts_run` docstring still describe the result as `status` and `output` only. A short mention of `hadErrors` / `errors` would help agents notice the indicator instead of reading only `output`.

### Review notes (verification performed)

- Diff scope: `git diff 97d6961...095776c` touches only `src/immybot_mcp/tools/scripts.py`, `tests/test_api_client.py` and `docs/tickets/PRD-21798.{md,ac.json}`. This matches the Tech design's Change list, with no scope creep.
- Correctness: `_run_errors` returns the first non-empty candidate (string, or a non-empty list coerced to `list[str]`); `hadErrors` is always a real bool and survives `compact()`; `errors` is dropped when empty, as AC2 requires. `status` comes from `enum_name(row.get("status"), _RUN_STATUS)` exactly as before (AC3), and no new HTTP call is added (AC4, also asserted in the new test).
- Script-body guard (PRD-21665 AC2): `scriptText` / `scriptPreview` are still never copied, and the new test asserts `SCRIPT["action"] not in json.dumps(result)`.
- Credentials / state: the diff touches no header handling, logging or persistence, and adds no shared state.
- Tests: the stub's `error` parameter and the new `test_script_run_reports_errors_from_run_record` cover TC1/TC5/TC6/TC7, and the extended clean-run assertion covers TC3. Spot-check: `uv run pytest -q tests/test_api_client.py -k script_run` → `6 passed, 65 deselected`. TC2/TC4 are correctly left `untested · needs a real vendor account`.
- Tool signatures: unchanged; the result only gains additive keys. README is untouched by this diff, so the Connector section is unaffected.
- No dependency, schema or credential-field change.
