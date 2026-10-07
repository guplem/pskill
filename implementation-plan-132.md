# Plan: `submit --file` for long answers (#132)

## Goal

Long answers can reach the runner on Windows in Claude Code. A heredoc command over about 7.3 KB with an apostrophe fails before the runner starts.

Acceptance criteria:

- `submit <run> [--task <n>] --file <path>` records the same answer as the same YAML on stdin: validation errors, `$answered_by`, and `$cannot_complete` included.
- Every agent packet and every task prompt names its answer path and the full `--file` command, in the bash and the PowerShell form.
- A 20 KB answer with apostrophes, backslashes, and `$` submits through `--file`.
- A short answer still submits with one heredoc command.
- `SPEC.md` D16 and section 18 describe `--file` and the reason for it.

## Decisions

- **Approval:** issue #132 records that the user agreed to reverse the `--file` ban of section 18. Only `--file` leaves section 18. `outbox/`, JSON-only answers, and `--inputs-file` stay banned.
- **Default stays:** the heredoc (bash) and the here-string (PowerShell) stay the default, so a block still takes one tool call.
- **When to use the file:** the packet says to use it for an answer over about 5 KB.
- **Answer path:** `.pskill/runs/<run>/answers/<block>.yaml`, and `<block>-task-<n>.yaml` for a parallel task. Parallel subagents never write the same file. The path is relative to the project root, with forward slashes. Block ids are safe file names (`^[a-z0-9_]{1,64}$`).
- **The folder exists:** the runner creates `answers/` when it builds a packet, so a shell redirect into it works.
- **Reading the file:** UTF-8 with an optional BOM (`utf-8-sig`). A missing or empty file is an `AnswerInputError`: exit code 1 with a clear message. With `--file`, the runner does not read stdin.
- **Same command in both shells:** the `--file` command has no stdin, so its text is the same in bash and PowerShell.
- **Release:** a new option, so version 0.31.0.

## Approach

- `pskill_runner/answer_input.py`: add `read_answer_file(path)` next to `read_answer`, with the same error class.
- `pskill_runner/cli.py`: add `--file` to the `submit` parser; pick the reader in `run_command`.
- `pskill_runner/packets.py`: add `answers_folder` to `AgentPacket`. Add one helper, `answer_file_line`, that both `return_section` and `task_prompt_text` call, after the submit command.
- `pskill_runner/engine.py` `base_packet`: set `answers_folder` and create the folder.
- `SPEC.md`: D16, section 7.3, section 8 (packet example), section 10.2 (the run folder), section 15 (CLI table), section 18. Check the Codex limitation L7 text.
- `pskill_runner/__init__.py`, `pyproject.toml`, `uv.lock`, `CHANGELOG.md`: the release.

## Steps

1. Red-green: `read_answer_file` (tests in `tests/test_answer_input.py`: text, BOM, missing, empty).
2. Red-green: `submit --file` in the CLI (tests in `tests/test_cli_main.py`: a block, `--task`, a missing file, a 20 KB answer with `'`, `\`, and `$`).
3. Red-green: the packet line in the Return section and the task prompt, bash and PowerShell (tests in `tests/test_packets.py`), and the folder and path from the engine (`tests/test_engine.py`).
4. Docs: `SPEC.md`.
5. Release 0.31.0.

## Checks

- Local: the touched test files, then the full CI command from `AGENTS.md`.
- CI: the checks on Windows, macOS, and Linux.

## Out of scope

- `--file` for `start --inputs`.
- Deleting answer files after a submit.
