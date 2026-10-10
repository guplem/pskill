# Plan: `pskill wait` (issue #150)

## 1. Goal

An agent that waits on background work runs `pskill wait <run> --reason "<text>"` in the background, then ends its turn. While the wait runs, the Stop hook allows the stop with no message and no count. The run pauses only when the waits of one block pass `max_wait_minutes` with nothing new.

Acceptance criteria (from the issue):
- [ ] With a wait running, a stop gives no message and no count, and the run stays active.
- [ ] A task result ends the wait at once.
- [ ] A wait with nothing new ends after `wait_minutes` with its one-line text.
- [ ] After `max_wait_minutes` with nothing new, the wait refuses to start, and the run pauses with the wait reason.
- [ ] With no wait, the Stop hook behaves as before.
- [ ] In a Claude Code cloud session, a background wait of 25 minutes wakes the agent when it ends. (Human check: this pull request cannot test it.)

## 2. Decisions

- **No lock while it sleeps (SPEC 7.7).** `wait` takes the run lock only to record the wait (or refuse it), and to clear it at the alarm. It polls `run.json` with no lock. `run.json` is written with `os.replace`, so a read never sees half a file.
- **"The run changed"** means: `updated_at` differs from the value saved by the wait itself, or the status is no longer `active`. Every task result, submit, pause, and cancel goes through `Run.save()`.
- **run.json fields** (optional, "absent in runs before 0.35.0", read with `.get`):
  - `wait_reason`: the text of the last wait.
  - `wait_started_at`: the start of the current wait.
  - `wait_until`: the alarm time. The hook allows a stop only before it, so a killed wait process never holds the hook for more than `wait_minutes`.
  - `waits_since`: the start of the first wait since the last task result or submit. It measures `max_wait_minutes`.
- **Resets:** the four fields clear where `stop_blocks` resets (`Run.submit`, `Run.resume`). A task answer while the run is paused needs no reset: no wait runs on a paused run, and `resume` clears the fields.
- **Change check:** the wait ends when the status, `updated_at`, or `wait_until` differs from what it saved. A submit clears `wait_until`, so a save in the same millisecond still counts.
- **Refusal:** when `now - waits_since >= max_wait_minutes`, `wait` raises `RunError` (exit 1) with: the waits passed N minutes with nothing new, continue the run or end the turn. The fields stay, so the next stops count as today, and `register_stop_attempt` puts "The last wait was on: <reason>." in the `agent_stopped` pause error.
- **No new hook, no new event type, no schema bump** (SPEC 9.2, 18, 10.3).
- **`wait` does not change the run owner** (SPEC 7.6, L4): it calls neither `use_harness` nor `use_session`.
- **Status:** `wait` needs an `active` run. A run that waits for a human does not need it (the hook ignores that status).
- **Codex:** its docs do not say that a background command wakes the agent. The wait still works there (the hook allows the stop), but nothing wakes the agent. README known limit says so. The hook does not use Claude Code's new `background_tasks` Stop input (out of scope; mention in the pull request).

## 3. Approach

| File | Change | Copies |
|---|---|---|
| `pskill_runner/run_waits.py` (new) | `start_wait`, `wait_for_run_change` (injected `sleep` and `clock`), `is_waiting(info, now)`, the end texts. | `pause_run` shape in `engine.py`; `read_checks` loop in `.pskill/skills/fix-ci/scripts/read_checks.py` |
| `pskill_runner/project.py` | `wait_minutes: int = 20`, `max_wait_minutes: int = 120`. | `autonomous_max_visits` |
| `pskill_runner/run_records.py`, `engine.py` | The four `RunInfo` fields, None in `start_run`; resets; the wait reason in the `agent_stopped` error. | `session_id` |
| `pskill_runner/hooks.py` | Allow a stop of a waiting run with no count; add the wait line to the message. | `holds_session` |
| `pskill_runner/cli.py` | `wait <run> --reason`; `runs_table` adds `waiting on <reason> since <time>`. | `pause` parser |
| `pskill_runner/stubs.py` | One stub line for `wait`; run `sync`. | the other lines |
| `claude_code.py`, `codex.py` | Doc comments: background commands and wake-up, with URLs. | existing comments |
| Docs | SPEC 7.7, 9.2 (real message + wait), 9.3, 10.1, 10.2, 15; README (hooks line, command table, known limit); AGENTS.md map row; CHANGELOG 0.35.0; version bump. | |

## 4. Steps (one red-green cycle each)

1. Config defaults `wait_minutes` and `max_wait_minutes`.
2. `RunInfo` fields, None at start; `start_wait` records them (and keeps `waits_since`).
3. `start_wait` refuses past `max_wait_minutes`; refuses a run that is not active.
4. `wait_for_run_change`: ends at once on a change (submit, task result, pause, cancel) with its line; ends at the alarm with the one-line text and clears `wait_until`.
5. Resets in `submit` and `resume`.
6. Hook: a waiting run allows the stop with no count; an expired wait counts again; the message has the wait line; the pause error names the wait reason.
7. CLI `wait` command and `runs --open` column text.
8. Stub line, `sync`, docs, version, CHANGELOG.

## 5. Checks

- Tests: `tests/test_run_waits.py` (new, fake clock), plus additions in `test_project.py`, `test_hooks.py`, `test_engine_*.py`, `test_cli_main.py`, `test_stubs.py`.
- Local: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest --cov && uv run pskill.py validate && uv run pskill.py test`.
- CI on Windows, macOS, Linux.

## 6. Out of scope

- Using Claude Code's `background_tasks` Stop input to allow stops with no `wait`.
- Changing the parallel-block packet wording (`run_in_background: false`).
- Viewer changes.
