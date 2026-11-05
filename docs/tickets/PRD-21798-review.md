# PRD-21798 · Code review

Status: frozen @ a02bb77

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

## Fixes (round 1)

Only finding 1 (must-fix) required a change; findings 2-4 are suggestions, not acted on in this round.

- **docs/tickets/PRD-21798.md:144** — replaced the quoted Chinese phrase `"外部 API 未知"` with `"unknown external API"` (English equivalent from `references/templates-design.md:213`'s Story Point considerations list, which this line is quoting). No change in meaning: the sentence still says this is the between-tier consideration that pushed the Story Point from 0.5 to 1.
- **docs/tickets/PRD-21798.md:188** — replaced the quoted Chinese phrase `"有就跑"` with `"run it if present"`, which was already given as the English gloss in the same cell; removed the now-redundant duplicate English parenthetical.
- **docs/tickets/PRD-21798.md:186** (Self-test, Chinese-character scan row) — the row's claim of "no match ... in this ticket's own `PRD-21798.md`/`.ac.json`" was false at freeze time (it missed the two lines above, which the reviewer's own `grep` command confirmed). Rewrote the row to: record the correction and the reviewer's finding; show the re-scan command's actual current output (`grep -nP '[\x{4e00}-\x{9fff}]' docs/tickets/PRD-21798.md` and the `.ac.json` equivalent both now return no output, exit 1); and note that the repo-wide scan still matches only pre-existing other-ticket docs and this review doc itself (which necessarily quotes the two offending phrases verbatim to document finding 1 — not new Chinese text introduced by this ticket's own code or product docs).
- The frozen main doc's `Status:` line (line 6) got one explicit note pointing at this Fixes section, per the finding's own instruction to "record the edit and its reason explicitly rather than editing silently" rather than leaving the frozen doc's known-false claim uncorrected. No other line in the main doc changed.
- **Retest**: `uv run pytest -q` → `538 passed, 11 skipped, 0 failed` (unchanged from the pre-fix baseline recorded in the Self-test section — this round's change is docs-only, no `src/`/`tests/` edits). Full repo Chinese-character scan rerun: `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .` — no longer matches `PRD-21798.md` or `PRD-21798.ac.json`; remaining matches are the pre-existing other-ticket docs already listed in the Self-test row and this review doc's own finding-1 text.
- Commit: see `Handoff`-equivalent below — `dev/PRD-21798` fix commit sha recorded in the `[DEV]` stub (`Review fixes round 1:` conclusion) once pushed.

## Round 2 · 2026-11-05 · reviewed dev/PRD-21798 @ a02bb77 (base main @ 97d6961)

Verdict: approved

### Findings

None. Checked round-1 Fixes against `git diff 095776c...a02bb77` (docs-only: `docs/tickets/PRD-21798.md`, `docs/tickets/PRD-21798-review.md`):

- Finding 1 (must-fix) is resolved: line 144 now reads "unknown external API", line 188 reads "run it if present"; the Self-test "Chinese-character scan" row was corrected to document the round-1 finding and the re-scan output instead of repeating the false "no match" claim.
- `grep -nP '[\x{4e00}-\x{9fff}]' docs/tickets/PRD-21798.md docs/tickets/PRD-21798.ac.json` (run directly during this round): the only remaining match is the Self-test row itself quoting the two original Chinese phrases verbatim to document the round-1 finding, as the Fixes note states — not new Chinese content introduced by this ticket's design, code, or tests. `.ac.json` has no match.
- Findings 2-4 (suggestions) were correctly left unactioned; nothing in round 2 required them to be addressed, and none of them is reclassified as must-fix.
- No `src/` or `tests/` changes in this round, so round 1's correctness/credentials/tests/tool-signature/README verification still holds unchanged; gates (`uv run pytest -q: 538 passed, 11 skipped, 0 failed`) are unaffected (docs-only diff).

Round 2 is approved with 3 open suggestions (2-4 from round 1, unresolved, non-blocking).
