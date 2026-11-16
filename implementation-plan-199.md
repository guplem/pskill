# Plan: a run key keeps task subagents out of the main agent's commands (#199)

## Goal

A task subagent cannot drive its parent run after its submit. Acceptance criteria (from #199):

- `current`, `resume`, `pause`, and a `submit` without `--task`, without the run's key, are refused. The run's block, status, session, harness, and events do not change.
- With the key, they work as before, also while fresh tasks are open.
- The main agent's packets and commands carry the key; task prompts and subagent replies do not.
- `pskill runs` shows each run's key.
- The task prompt and the reply to an accepted task submit tell the subagent to end its turn.
- The read-only profile agent says not to run git commands that change the repository.
- Tests cover each refused command and each command with the key.

## Decisions

- **Key:** `secrets.token_hex(3)` (6 hex characters), made in `start_run`, stored as `key` in `run.json`. A child skill shares its run's key (one run).
- **Old runs:** a run with no `key` (before 1.3.0) needs none. An upgrade never strands an open run.
- **Where the check runs:** in `cli.run_command`, before the command, like `check_run_is_here`: one engine function `check_run_key(project, run_id, key)` reads `run.json` (the key never changes, so no lock is needed). The engine functions stay unchanged, so engine tests, skill tests (`pskill test`), and the viewer need no key.
- **Refusal:** a `RunError`, so stderr and exit code 1, like other refusals. It runs before the command, so nothing is written, logged, or uploaded. One text, without the key, for a missing or wrong key: "This command is the main agent's and needs the run's key: `--key <key>`. If you are a task subagent, your work ended with your submit: end your turn now. The main agent finds the key in its last step, and a human in `pskill runs`." No refused command takes `--task` (`submit --task` is never checked), so the runner cannot name the caller's task: the text speaks to any task subagent instead.
- **Commands with the key:** `current` (with or without a run id: the resolved run), `submit` without `--task`, `pause`, `resume`. `cancel`, `delete`, `wait`, `run-script`, `task`, and `submit --task` take no key.
- **Texts with the key** (main agent only): the submit command and its `--file` line when there is no `--task`; the rules sections' pause line; the subagent packet's "When every subagent has finished, run ... current"; the pause packet's resume and current lines; `paused_card`'s resume; the background script texts (pause, resume, current); `run_waits.py` texts; the Stop hook reason.
- **Texts without the key** (a subagent reads them): the one-line subagent prompt, `pskill task`'s prompt, `task_reply`, `accept_job`'s subagent lines, `record_task_while_paused`, `task_not_recorded`, the `task_text` error. `task_reply` and the `task_text` error lose their `current` command: they tell the subagent to end its turn and to tell the main agent.
- **Stop text:** the task prompt's first line becomes "You are a subagent of a pskill run. Do only this task, then submit its answer. Your work ends with an accepted submit: then end your turn, and run no other pskill command." The reply to an accepted fresh task adds: "Your work is done: end your turn now."
- **Read profile line:** `claude_code.profile_agent_text` adds, for the `read` profile only: "Do not run git commands that change the repository, such as commit, push, checkout, or reset." This makes every existing `pskill-read.md` stale until `sync`, which `update` runs: say so in CHANGELOG.
- **Stubs:** step 5 becomes "run: `<runner> pause <run-id> --key <key>`. Each step names its run id and key." The `pskill` stub's current, resume, and pause lines get `--key <key>`, plus one line: "`runs` shows each run's key."
- **Version:** 1.3.0.

## Approach

- `run_records.py`: `key: str | None  # absent in runs before 1.3.0` in `RunInfo` (copies `session_id`).
- `run_store.py`: `new_run_key()` next to `new_run_id` (copies its `secrets` use).
- `engine.py`: set `key` in `start_run`; `check_run_key`; `key_option(info)` helper returning `" --key <k>"` or `""`; use it in every main-agent text listed above.
- `packets.py`: `run_key: str | None = None` field on `AgentPacket` and `BackgroundScriptPacket` (copies `can_wait`), filled in `Run.base_packet` and `background_script_packet`; `plain_submit_command` adds the key only when `task_index is None` (copies its `--task` suffix); `render_pause_packet` takes the key.
- `cli.py`: `--key` on `current`, `submit`, `pause`, `resume` (split pause and resume out of the shared loop); call `check_run_key` in `run_command`; a `key` column in `runs_table` (`-` when none).
- `hooks.py`, `run_waits.py`: add the key from `info.get("key")`.
- `stubs.py`, `claude_code.py`, `profile_agents.py` docstring: texts above; then `uv run dev.py sync`.
- Docs: SPEC 3 (new D30, notes on D13 and L3), 6.1, 7.3, 7.6, 8, 9.2, 9.3, 10.2, 15, 18 row; README lines 70, 74, 170, 171; CHANGELOG 1.3.0; version in `pskill_runner/__init__.py` and `pyproject.toml`.

## Steps (one red-green cycle each)

1. A new run has a key in `run.json`.
2. `check_run_key`: refuses a missing or wrong key, accepts the right one, accepts any call on a run with no key.
3. CLI: `--key` on the four commands; `run_command` calls the check before the command; a refused command changes no file (events, run.json).
4. `runs` shows the key column.
5. Packets: the main submit command, `--file` line, rules pause line, subagent packet's current line, and pause packet carry the key; task prompts and the one-line subagent prompt do not.
6. Engine texts: background script texts, `paused_card`, run-script texts carry the key; `task_reply` and the `task_text` error drop `current` and say end your turn.
7. Stop text in the task prompt and the accepted fresh task reply.
8. `run_waits.py` and `hooks.py` texts carry the key.
9. Stubs and the read profile line; `dev.py sync`.
10. Docs, CHANGELOG, version.

## New cases

- New run gets a key: `test_a_new_run_records_a_key`.
- Each command without a key is refused: `test_the_runs_key_passes_the_key_check`, `test_current_without_the_key_is_refused`, `test_current_without_a_run_id_needs_the_key_of_the_newest_run`, `test_submit_without_task_and_key_is_refused`, `test_pause_without_the_key_is_refused`, `test_resume_without_the_key_is_refused`.
- Wrong key refused: `test_a_missing_or_wrong_key_is_refused`.
- Refusal changes nothing: `test_a_refused_command_changes_no_run_file`.
- The refusal tells a task subagent to end its turn and never shows the key: `test_a_missing_or_wrong_key_is_refused`.
- Unknown run: `test_the_key_check_of_an_unknown_run_says_there_is_no_such_run`.
- `submit --task` needs no key: `test_submit_with_task_needs_no_key`.
- With the key, works while fresh tasks are open: `test_current_with_the_key_works_while_subagents_run`.
- Old run needs no key: `test_a_run_from_before_the_key_needs_none`.
- `runs` shows the key, and `-` for an old run: `test_runs_shows_each_runs_key`.
- Packets with and without the key: `test_the_main_submit_command_carries_the_key`, `test_a_task_prompt_never_carries_the_key`, `test_the_pause_packet_carries_the_key_except_for_cancel`, `test_a_packet_of_a_run_without_a_key_has_no_key_option`.
- Subagent replies: `test_an_accepted_fresh_task_tells_the_subagent_to_end_its_turn`, `test_a_paused_task_reply_names_no_command`.
- Hooks and waits: `test_the_stop_hook_reason_carries_the_key`, wait texts in `test_run_waits.py`.
- Read profile line: `test_the_read_profile_agent_forbids_changing_git_commands`, and the web profile does not have it.

## Stale texts (from `git grep`)

- README.md:70, 74, 170, 171.
- SPEC.md:321-322 (6.1 profile agent "no prompt"), 484 (`--file` form), 491 (task reply), 516 (resume), 588 (subagent packet), 702 (stub step 5), 1179-1180 (CLI rows), 1280 (section 18 row); 3 (D13, L3), 7.6, 8 examples, 9.2 hook reason quotes, 9.3 pskill-read example, 10.2 field list.
- pskill_runner/claude_code.py:90 docstring; profile_agents.py:3 docstring.
- engine.py:1034, 1122, 1147, 1459, 1580, 1646; hooks.py:49-50; packets.py:118, 167, 221, 282, 505, 507; run_waits.py:46, 79, 96, 114; stubs.py:88, 105, 106, 110.
- Tests that assert these texts (found when each step goes red).
- Generated: `.claude/skills/*/SKILL.md`, `.agents/skills/*/SKILL.md`, `.claude/agents/pskill-read.md` (by `dev.py sync`).

## Reused code

- `key` field: `RunInfo.session_id`. Key making: `run_store.new_run_id`. Check before the command: `worktrees.check_run_is_here` in `cli.run_command`. Option suffix: `plain_submit_command`'s `--task`. Packet field: `AgentPacket.can_wait`. Old-run test: `test_engine.py:293`. No-change test: `test_engine.py:611`. Runs column: `runs_table`'s `current_block or '-'`.

## Checks

- Local: `uv run dev.py fast` per step; `uv run dev.py check` before the push (format, lint, mypy, tests with 100% coverage, validate, skill tests).
- CI: `static`, `checks` on Ubuntu, Windows, macOS.

## Out of scope

- Blocking a subagent's git commands for real (a Claude Code hook): a later issue.
- A key on `cancel`, `delete`, `wait`, `run-script`, `task`.
- Hiding the key from the viewer, `events.jsonl`, or the Galtea upload.
