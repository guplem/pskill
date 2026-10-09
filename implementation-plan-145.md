# Plan: a visit cap asks before it moves on, and every loop must have a cap (#145)

## Goal

At a visit cap, the run asks "N more rounds, or move on?" instead of jumping silently. In autonomous mode the agent answers, under a hidden ceiling. Every loop must have a cap.

Acceptance criteria (issue #145):

- `pskill validate` reports an error for a loop where no block has `max_visits`.
- Interactive: at a cap, the human is asked "more" (with a number of rounds) or "move on".
- "More" runs N more visits of that block in this run, then asks again.
- "Move on" goes to `on_max_visits`.
- A block with `ask_on_max_visits: false` moves on with no question, in both modes.
- Autonomous: the agent answers the question; the question asks for few extra rounds and never shows the ceiling.
- Autonomous: at the ceiling (per block, or the `config.yaml` default), the run moves on with no question.
- Interactive: the human can go past the ceiling.
- SPEC.md, AUTHORING.md, and the viewer's field help describe the new keys and behavior.

## Decisions

- **Key names.** `ask_on_max_visits` (true or false, default true) and `autonomous_max_visits` (the ceiling, a whole number). The config default uses the same name, `autonomous_max_visits: 150` in `.pskill/config.yaml`, as `retries` does: the block key wins over the config value. One name for one meaning (SPEC section 2).
- **`on_max_visits` is required with `max_visits`.** "Move on", the opt-out, and the ceiling all need a target. Today a cap with no target pauses the run on the block before it, and `resume` hits the same cap again: a dead end. The validator gives an error. create-issue's two caps without a target get one.
- **The other cap keys need `max_visits`.** `on_max_visits`, `ask_on_max_visits`, and `autonomous_max_visits` without `max_visits` are validator errors. `autonomous_max_visits` must be at least `max_visits`; equal is allowed and means "ask the human, but never let the agent extend".
- **A loop with no cap is an error** (D11 changes, with a "Changed in" note; the user approved it in #145).
- **The cap question is runner state, not a block.** The frame gets `visit_cap_question` (the capped block's id, or none) and `extra_visits` (block id to extra rounds). While the question is open, `current_block()` returns a decision that the runner builds: decider human, choices `more` and `move_on`, an optional integer `rounds`. So the existing decision flow works as it is: the `waiting_for_human` status in interactive mode, `$answered_by`, rejects and retries, pause and resume, `decided_by` (`agent_autonomous` in autonomous mode), and the Stop hook. `{{ }}` cannot read this state (SPEC section 18 stays true). The answer does not go into `steps` or `history`.
- **When the cap applies.** The block's limit is `max_visits` plus its extra rounds. In autonomous mode, the ceiling also stops it. At the limit: the opt-out or the autonomous ceiling moves on with no question; otherwise the run asks. "More" with `rounds` below 1 is rejected. Visits and extra rounds count per frame, as visits do today.
- **The question text** names the block, its visits, and that the user prefers few extra rounds. It never names the ceiling or the `on_max_visits` target (D8: no future blocks).
- **Events.** The question logs `block_started` and `block_completed` with `block_type: visit_cap` on the capped block's id. The viewer shows it as a row; the test path skips it, so existing expected paths stay the same. The "move on" arrival reason keeps its text `visit cap of <block> (<n>)`, which the viewer reads.
- **Skill tests answer it with a new case key `caps`:** `{<block>: [answers...]}`, used while a cap question is open. A case that reaches a question with no `caps` entry fails with a clear message.
- **Example skills.** The safety-net caps opt out: implement-issue `review` and `final_review`, review-pr `review`. The test cases that reach a cap (fix-ci `capped.yaml`, review-doubt `question-cap.yaml`) answer `move_on`.
- **Release 0.33.0** (new keys and behavior).

## Approach

- `skill_model.py`, `skill_schema.py`, `skill_loader.py`: the two new keys on `Block`.
- `project.py` (`Config`), `install.py` (`DEFAULT_CONFIG`): `autonomous_max_visits`.
- `validator.py`: the new errors; `loop_warnings` becomes an error.
- `engine.py`: `go_to`, `current_block`, `accept` (a new `answer_visit_cap`), `log_block_started`; `run_records.py`: the two frame keys, read with `.get` for old runs.
- `packets.py`: the question's instruction text.
- `skill_tests.py`: the `caps` key and the path filter.
- Viewer: `viewer_data.py`, `skill_view.py`, `viewer/app.js`, `viewer/field_help.js`, `skill_editor.py` (`COMMON_KEYS`), `skill_export.py` (the cap text).
- Copy `retries_of` for the ceiling lookup, and commits a752898 and b9bad34 for a new block key end to end.

## Steps

1. **Keys and config.** The two keys load into the model and pass the schema; `config.yaml` takes `autonomous_max_visits` (default 150).
2. **Validator rules.** `on_max_visits` is required with `max_visits`; the cap keys need `max_visits`; the ceiling is at least `max_visits`; a loop with no cap is an error. Fix the test fixtures and give create-issue's caps a target.
3. **Interactive question.** At a cap, the run asks the human (`waiting_for_human`). `move_on` goes to `on_max_visits`. `more` with `rounds` raises the cap and asks again at the new limit; `rounds` below 1 is rejected.
4. **Opt-out.** `ask_on_max_visits: false` moves on with no question, in both modes.
5. **Autonomous.** The agent answers (`agent_autonomous`); the packet never shows the ceiling; at the ceiling the run moves on with no question; in interactive mode the human goes past it.
6. **Question on a runner block, and re-entry.** A cap on a script or call block in a loop asks too; `current` and `resume` show the open question again.
7. **Skill tests.** The `caps` case key and the path filter; the example skills' safety-net caps opt out; fix-ci and review-doubt cases answer the question.
8. **Viewer and export.** Timeline row label, field help, the editor keys, the skill screen facts, and the exported Markdown text.
9. **Docs and release.** SPEC.md (D11, 5.5, 7.2, 7.4, 7.5, 10.1, 11, 12, 13.3, 14), AUTHORING.md, CHANGELOG.md 0.33.0, and the version.

## Checks

- Tests per step in `tests/test_skill_model.py` or `test_skill_loader.py`, `test_project.py`, `test_validator.py`, `test_engine.py`, `test_skill_tests.py`, `test_viewer_data.py`, `test_skill_view.py`, `test_skill_editor.py`, `test_skill_export.py`; the viewer field-help test covers the new keys.
- Local: `uv run pytest --cov` (100%), `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pskill.py validate`, `uv run pskill.py test`.
- CI on Windows, macOS, and Linux.

## Out of scope

- Reporting skipped work in the pull request (PR #144, then the monorepo's skills).
- Changes to the monorepo's skills.
