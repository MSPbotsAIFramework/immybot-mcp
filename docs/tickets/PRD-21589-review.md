# PRD-21589 · Code review

Status: frozen @ 26cc36a

## Round 1 · 2026-10-31 · reviewed dev/PRD-21589 @ 26cc36a (base cfc9181)

Verdict: approved

### Findings

No must-fix found.

1. [suggestion] `tests/test_api_client.py:238-260` — `test_set_needs_onboarding_invalid_computer` carries a long inline comment explaining the TC2/AC2 discrepancy. That's fine to keep as a permanent note, but it duplicates the explanation already written in `docs/tickets/PRD-21589.md` ("Self-test" section) almost verbatim; a one-line pointer back to the doc would read just as well and avoid having two copies to keep in sync if the status-code mapping ever changes. Not blocking — the duplication is harmless and the dev leg's choice to document the discrepancy in both places (code comment for future maintainers, ticket doc for the requester) is reasonable for a shared-contract connector.

### Verification performed

- Ran `uv run pytest -q` on `dev/PRD-21589 @ 26cc36a`: 484 passed, 11 skipped, 0 failed — matches the Self-test section's claimed numbers exactly.
- Confirmed the TC2/AC2 discrepancy write-up against the actual code: `src/immybot_mcp/api_client.py:73-83` (`_STATUS_TO_CODE`) maps `404 -> not_found` and `400 -> invalid_argument`; the dev leg's documented reasoning for testing against 400 instead of the design draft's 404 is accurate, not a cover for a bug.
- Diffed `README.md`'s `## MSPbots Connector` ... `---` section (lines 16-86) byte-for-byte against `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md`: exact match.
- `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv src/ tests/ README.md`: no output.
- Diff scope `cfc9181...26cc36a` touches exactly the files the tech design's change list names (`src/immybot_mcp/tools/computers.py`, `src/immybot_mcp/tools/navigation.py`, `README.md`, `tests/test_tools.py`, `tests/contract_types.json`, `tests/test_api_client.py`) plus the ticket's own `docs/tickets/PRD-21589.{md,ac.json}` — no scope creep.

### Checklist against `legs/review.md` R3 / `mcp-track.md` 4.3

- Credentials: new tool adds no credential-handling code path; reuses `client_factory` / `run_tool` unchanged — per-request isolation inherited, not reimplemented.
- Contract: tool name, parameter (`computerId: ComputerId`), response envelope (`{done, computer_id, result}`) and error envelope match the tech design and the `trigger_checkin` sibling exactly.
- Tests: `EXPECTED_TOOLS`, `WRITE_TOOLS`, `test_tool_names_are_stable` (68->69), `contract_types.json` and two new `test_api_client.py` cases all updated; generic parametrized tests (`test_required_params`, `test_annotations_match_side_effects`, `test_write_tools_say_when_to_use_them`, `test_description_budget`) cover the new entry automatically.
- README Connector section: unchanged, verified verbatim (see above).
- Cross-repo compatibility (1.2): not applicable — single repo, no new headers/fields crossing a boundary.
- SOP §14 checklist: not affected by this change (no new dependency, no new credential path, no schema/DB, stateless).

### Fixes

n/a — no must-fix raised in Round 1.
