# Plan: fix-ci waits for CI in a background script (#180)

## Goal

Close #180. Two of its criteria already shipped in #187: the `review-pr` `triage` has `context: fresh`, `tier: standard` and `tools: read`, and AUTHORING.md names the examples of `context: fresh`. This pull request covers the last one: `fix-ci` waits for CI with no agent turn, through the background `script` block of #190 / #191.

Acceptance:

- `fix-ci.wait_ci` is a `script` block with `background: true`. `pskill validate` accepts it with no warning.
- The script does on its own what `instructions/wait_ci.md` asked of the agent, and prints a final `state` of `passed`, `failed` or `closed`, with `failed_checks` and `head_sha`.
- The 5 skill test cases replay the wait as recorded script results, with the same paths and outputs.

## Decisions

1. **Block limits:** `timeout_s: 7140`, `retries: 0`. Total 7140 + 60 = 7200 s, the 2-hour limit and the default `max_wait_minutes`. A retry would halve the wait, and a CI run can take up to 2 hours.
2. **The script's own wait:** `wait_s: 6900` (115 minutes) on the block input, and `MAX_WAIT_SECONDS = 6900` in the script (the cap and the default). The 240 s left before `timeout_s` cover the last poll, so the runner never kills the script.
3. **A check still pending when the wait ends:** the state is `failed`, and each pending check is in `failed_checks` as `<name> (still running after 115 minutes): <link>`. `fix_ci` then finds out why it hangs; a hang that this pull request does not explain is `flaky` (rerun) or `unrelated`. A non-zero exit would pause the run instead, with no clue in the trace.
4. **`none` (no check exists):** the script waits at most 300 s for a first check, as today. While `mergeable` is `null`, it keeps polling past those 300 s, within the same deadline: a later read can still find a conflict, or a check that started. Then: `mergeable` false gives `failed` with `merge conflict`; `draft` true gives `failed` with `draft`; otherwise `passed`.
5. **No version bump and no CHANGELOG entry**, as #187 did for the same issue: only an example skill changes.
6. **Transient GitHub errors** stay a block failure (pause, then `resume`), as today for every script.

## Approach

- `.pskill/skills/fix-ci/scripts/read_checks.py`: keep `read_once` and `read_checks`. Add small functions:
  - `read_checks` keeps polling a `none` state while `mergeable` is `None` (no separate re-read, which could find a check just started and call it hung).
  - `final_result(result, wait_minutes)`: maps `none` and `pending` to `passed` / `failed` with the checks named; leaves `passed`, `failed`, `closed` as they are.
  - `main()` prints `final_result(...)` of the wait. Docstring updated.
  Tests follow `tests/test_skill_fix_ci.py` (`FakeClock`, `polls`, `FakeShell`, `run_main`).
- `.pskill/skills/fix-ci/skill.yaml`: `wait_ci` becomes a `script` block, copied from `checkout-pr.checkout_pr` and the AUTHORING example; edges and ends read `steps.wait_ci.json.*` (as `implement-issue` edges do).
- `.pskill/skills/fix-ci/instructions/fix_ci.md`: reads `steps.wait_ci.json.head_sha` and `.json.failed_checks`; one bullet for a check still running.
- Delete `.pskill/skills/fix-ci/instructions/wait_ci.md`.
- The 5 cases in `.pskill/skills/fix-ci/tests/`: `wait_ci` moves from `answers:` to `scripts:` as `{exit_code: 0, stdout: '<json>'}` (as `create-issue/tests/autonomous-labels.yaml`).
- Docs: SPEC 13.2 rule "Wait in the foreground" becomes "Wait in the background"; SPEC 13.3 row names `fix-ci.wait_ci`; AUTHORING.md background example uses the real script and values of `fix-ci`.

## Steps

1. Red-green: the wait cap rises to 6900 s (change the 540 tests, the `main` default).
2. Red-green: `none` with `mergeable` null keeps polling (first built as a separate re-read, folded into the loop in step 3).
3. Red-green: `final_result` for `none` (conflict, draft, no CI) and `pending` at the end of the wait; `main` prints it.
4. The skill: `wait_ci` script block, `.json` reads, `fix_ci.md`, delete `wait_ci.md`, the 5 cases. Check with `pskill validate` and `pskill test` (red first: the cases fail with the task still in place once moved to `scripts:`).
5. Docs: SPEC 13.2, 13.3, AUTHORING.md.
6. `uv run dev.py sync` (no change expected) and `uv run dev.py check`.

## Lists

### New cases

- Wait cap 6900 s whatever the input asks: `test_read_checks_waits_at_most_6900_seconds_whatever_the_input_asks`.
- `main` default wait 6900: `test_main_passes_the_pull_request_and_its_wait`.
- `none` with `mergeable` null keeps polling past 300 s: `test_read_checks_keeps_polling_while_github_computes_mergeable`.
- `none` with `mergeable` known stops at 300 s: `test_read_checks_waits_at_most_300_seconds_for_a_first_check`.
- `none` + conflict / draft / no CI (also with `mergeable` null): `test_final_result_settles_a_pull_request_with_no_check` (parametrized).
- `none` with `mergeable` null until the wait ends: `test_read_checks_stops_at_the_end_of_the_wait_while_mergeable_stays_unknown`.
- `main` settles a draft with no check: `test_main_settles_a_draft_with_no_check`.
- `pending` at the end of the wait -> failed with the pending checks named: `test_final_result_fails_the_checks_still_running_when_the_wait_ends`.
- `passed` / `failed` / `closed` unchanged: `test_final_result_keeps_a_finished_state`.
- `main` prints the final result: `test_main_prints_the_checks_of_the_pull_request` (updated).
- Skill: the 5 cases in `.pskill/skills/fix-ci/tests/` replay `wait_ci` as a script.

### Stale texts (from `git grep "wait_ci\|540\|wait_s\|Wait in the foreground\|after #180"`)

- `.pskill/skills/fix-ci/instructions/wait_ci.md` (deleted).
- `.pskill/skills/fix-ci/instructions/fix_ci.md:1,3` (`steps.wait_ci.head_sha`, `.failed_checks`).
- `.pskill/skills/fix-ci/scripts/read_checks.py:7,33` (docstring "at most 540", `MAX_WAIT_SECONDS`).
- `.pskill/skills/fix-ci/skill.yaml:28-41,69,83,99,100,104`.
- `.pskill/skills/fix-ci/tests/*.yaml` (`answers: wait_ci`).
- `tests/test_skill_fix_ci.py:138,151-157,187,233` (540).
- `AUTHORING.md:136-145` (fictional `scripts/wait_ci.py`).
- `SPEC.md:984` ("Wait in the foreground"), `SPEC.md:1027` ("after #180").
- `README.md:94` stays true.

### Reused code

- Polling, REST reads, head sha: `read_once` / `read_checks` in `read_checks.py`.
- Script block shape: `checkout-pr` `checkout_pr`; background keys: AUTHORING.md example.
- Recorded script results in cases: `create-issue/tests/autonomous-labels.yaml`.
- Test helpers: `tests/skill_scripts.py`, `FakeClock`, `polls` in `tests/test_skill_fix_ci.py`.

## Checks

- Local: `uv run pytest tests/test_skill_fix_ci.py`, `uv run pskill.py validate`, `uv run pskill.py test fix-ci`, then `uv run dev.py check` (format, lint, mypy, tests at 100% coverage, validate, skill tests).
- CI: `static` and `checks` on Linux, Windows and macOS.
- Not provable in CI: a real Claude Code run of `fix-ci` with the background wait (the open box of #191's test plan).

## Out of scope

- The `review-pr` triage and the AUTHORING `context: fresh` note (shipped in #187).
- Retrying transient GitHub errors inside the wait.
- Any runner change.
