# Plan: run a script block in the background (#190)

## 1. Goal and acceptance criteria

A `script` block can set `background: true`. On a harness that wakes the agent after a background command
(Claude Code), the agent starts one runner command in the background and ends its turn. The runner runs the
script, records its result, and prints the next packet, so the agent wakes once. A long wait, such as CI,
then costs no agent turn per poll.

- [ ] A `script` block can set `background: true`, with a `timeout_s` above 600, up to `max_wait_minutes` * 60.
- [ ] Claude Code: the packet gives one command (`uv run .pskill/pskill.py run-script <run>`) to start in the
      background. The runner runs the script and records its result itself.
- [ ] Claude Code: the agent ends its turn, and the Stop hook stays quiet until the script ends (the wait fields).
- [ ] Claude Code: the agent wakes once with the next packet, and the run goes on.
- [ ] Codex and generic: the block runs in the foreground, inside `advance()`, as today. SPEC names the shell
      limit.
- [ ] `pskill test` replays a background script like any other script, with no change to case files.
- [ ] SPEC (3 D7 note, 4, 6.3, 9.1, 9.2, 10.1, 10.3, 11, 13.3, 15), AUTHORING.md, README.md, and CHANGELOG.md
      describe it. Version 1.1.0 (a minor release).

## 2. Decisions

- **The command:** a new subcommand, `run-script <run>`. It runs the current block's script and records the
  result, then prints the next packet, as `submit` does (D16: it is the block's one call).
- **Lock:** `run-script` takes the run lock to mark the start, releases it while the script runs (any
  other command breaks a lock that is older than 60 s), and takes it again to record the result.
- **A changed run drops the result:** the frame records `background_script: {state, since}`. Recording
  needs the run to be `active`, on the same block, with the same `since`. Otherwise the output says that
  the result was dropped and how to continue.
- **States:** `issued` (packet printed) → `running` (`run-script` started) → cleared on record. A second
  `run-script` while `running` is refused. `resume` clears the marker and prints the packet again, which
  recovers a script process that died.
- **Stop hook:** the packet sets the wait fields, so `hooks.py` needs no change: `wait_reason` = "the
  background script <id>", `wait_until` = now + the Bash timeout, `waits_since` = now, and `stop_blocks` = 0.
  Recording clears them (`clear_wait`).
- **`pskill wait` during a background script** is refused: "The script <id> runs in the background: end
  your turn, its end wakes you." This keeps a 20-minute alarm from replacing the longer one.
- **Bash timeout in the packet:** `min(timeout_s + 60, 7200)` s, written in ms. Claude Code's background cap
  in a cloud session is 2 h (https://code.claude.com/docs/en/tools-reference, read 2026-11-04). The runner's
  own subprocess timeout fires first whenever the margin fits.
- **Timeout of a background block:** its `timeout_s`, or else `script_timeout_s`. The validator gives an
  error above `max_wait_minutes` * 60, so `validate_skill` takes the config limit (callers: `cli.py`,
  `engine.load_valid_skill`, `skill_view.py`). It also gives a warning for a foreground `timeout_s` above 600:
  "Claude Code stops a shell call at 10 minutes: set `background: true`".
- **Codex and generic:** foreground. SPEC says that Codex sets no hard limit (its `exec_command` returns
  after at most 30 s, and the agent polls with `write_stdin`, up to 5 minutes per poll: openai/codex
  b9099a1), and that Claude Code stops a foreground call at 10 minutes.
- **`pskill test`** runs with `harness="generic"`, so it replays the block inline through `RecordedExecutor`.
- **Schema version 9:** a background script's `block_started` now carries a packet, and the frame has a new
  field.
- **`submit` on a script block** is refused with a RunError that names the script (this replaces a pragma).

## 3. Approach (files, and the code that each change copies)

- `skill_schema.py`, `skill_model.py`: `background: boolean`, next to `timeout_s`.
- `validator.py`: two small checks, like the existing per-block checks; plus a `max_wait_minutes` parameter.
- `engine.py`: split `run_script` into prepare / attempt / record. `advance()` stops at a background block
  when `adapter.wakes_after_background_command`. The new `run_background_script()` follows
  `run_waits.start_wait` for the lock pattern. The `current_text`, `submit`, and `resume` paths change too.
- `packets.py`: `render_background_script_packet`, using the wording of `background_subagent_line`.
- `run_waits.py`: refuse a wait while a background script runs.
- `cli.py`: the `run-script` parser, `RUN_ID_COMMANDS`, dispatch, and `print_and_upload`, as `wait` has.
- `run_records.py`: `SCHEMA_VERSION = 9`, and the frame field.
- `skill_editor.py`, `viewer_data.py`, `skill_view.py`, `skill_export.py`: the `background` key.
- `stubs.py`: list `run-script` in the pskill stub's command list, if it lists the commands.
- `claude_code.py`: the doc URLs for the shell limits.

## 4. Steps (one red-green cycle each)

1. Schema and model: `background` loads, defaults to false, and rejects a non-boolean.
2. Validator: an error above `max_wait_minutes`, a warning for a foreground block above 600 s; the callers
   pass the config.
3. Engine: on Claude Code, `advance()` stops at a background block, prints the packet, marks `issued`, and
   sets the wait fields. On generic and Codex, it runs the block inline.
4. `run_background_script` and the `run-script` CLI: run with no lock, record (`script_ran`,
   `complete_block`), advance, and print the next packet; retries, then `block_failed`; a refused
   second start; a dropped result after a pause, cancel, or resume.
5. `current` while issued or running; `submit` refused; `resume` prints the packet again; `wait` refused.
6. `pskill test` replays a background block (a fixture skill and case file).
7. Viewer, editor, export: show and keep `background`; schema version 9.
8. Docs and release: SPEC, AUTHORING.md, README.md, CHANGELOG 1.1.0, both version numbers, `dev.py sync`.

## 5. Lists

Tests:
- [ ] test_skill_loader / test_skill_schema: `background`
- [ ] test_validator: timeout error, foreground warning
- [ ] test_engine: the background packet, the wait fields, the foreground fallback
- [ ] test_engine: run_background_script success, failure and retries, dropped result, double start
- [ ] test_engine: current, submit, and resume during a background script
- [ ] test_run_waits: wait refused during a background script
- [ ] test_hooks: quiet stop during a background script
- [ ] test_cli: the run-script command
- [ ] test_skill_tests: replay
- [ ] test_skill_editor / test_viewer_data / test_skill_view / test_skill_export: the key

Docs:
- [ ] SPEC 3 D7 (Changed in 1.1.0), 4 step 5, 6.3, 9.1, 9.2, 10.1, 10.3, 11, 13.3, 15
- [ ] AUTHORING.md `timeout_s` / `background`
- [ ] README.md command table and the limitation note
- [ ] CHANGELOG.md 1.1.0; `__version__` and pyproject `version`

## 6. Checks

- Local: `uv run dev.py fast` while building; `uv run dev.py check` before each push (format, lint, mypy,
  tests with 100% coverage, validate, skill tests).
- CI: `static`, and `checks` on ubuntu, windows, and macos (the lock and process behavior on Windows).

## 7. Out of scope

- Using `background` in `fix-ci` or any example skill (#180).
- Changing the lock behavior of foreground scripts that run over 60 s.
