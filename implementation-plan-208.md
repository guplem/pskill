# Plan: lock the verified PreToolUse payloads of the git block in tests (#208)

## Goal

A Claude Code change to `agent_id` or `agent_type` in the PreToolUse input breaks a test, instead of the git block failing open without a sign. Acceptance criteria (from #208):

- Two fixtures under `tests/fixtures/claude-code/`: a `pskill-read` subagent's Bash call and the main agent's Bash call, with neutral ids and paths.
- Tests feed both to `git_block_reason` and to `hook pre-tool-use --harness claude-code` with a `git commit`: the subagent is denied, the main agent gets nothing.
- The `claude_code.py` note of 2026-11-16 says the fields were verified in real sessions on 2026-11-17.

## Decisions

- **Fixture names:** `pre-tool-use-subagent.json` and `pre-tool-use-main-agent.json`. SPEC 16 already names `tests/fixtures/<harness>/` for saved harness payloads.
- **Content:** the keys of the probe payload on #208, in its order. Neutral values: ids such as `00000000-0000-0000-0000-000000000000` and `a0000000000000001`, paths such as `/home/user/project`. The command in the fixture is `git status`, as captured; each test sets its own command.
- **Loader:** one small typed function per test file, reading a path built from `Path(__file__)` with UTF-8 (the CLI tests change the working folder; CI runs on Windows).
- **No version bump, no CHANGELOG:** tests and a docstring only. A merge that keeps the version releases nothing.
- **Red:** the tests pass against today's code, so the red is shown by breaking the `agent_id` check of `git_block_reason` on purpose and restoring it.

## Approach

- `tests/fixtures/claude-code/*.json`: new.
- `tests/test_hooks.py`: two tests after the main-agent tests (around line 548), next to `bash_input`.
- `tests/test_cli_main.py`: two tests after the existing pre-tool-use tests (around line 1445), using `run_cli` like them.
- `pskill_runner/claude_code.py`: extend the 2026-11-16 note.

## Steps

1. Fixtures plus the `git_block_reason` tests (red by breaking the agent check).
2. The CLI tests through `hook pre-tool-use` (same red).
3. The docstring note (no test).

## Lists

**New cases:**
- The captured subagent payload with `git commit` is refused: `test_the_captured_subagent_payload_is_refused_a_git_commit` (test_hooks), `test_the_hook_denies_a_git_commit_in_the_captured_subagent_payload` (test_cli_main).
- The captured main-agent payload with `git commit` is allowed: `test_the_captured_main_agent_payload_is_never_refused` (test_hooks), `test_the_hook_prints_nothing_for_the_captured_main_agent_payload` (test_cli_main).
- The main agent's fixture has neither field, and the subagent's has both: asserted in the same tests, so a fixture edit cannot quietly drop them.

**Stale texts:** `pskill_runner/claude_code.py` line 31, the "Verified against the Claude Code docs on 2026-11-16" note. SPEC 9.2 and L12 already state the rule; nothing else names the verification.

**Reused code:** `run_cli` and the existing pre-tool-use test shape in `test_cli_main.py`; the assertions of `bash_input` tests in `test_hooks.py`. The fixture loader: none found (first fixture in the repository).

## Checks

`uv run dev.py fast` per step, `uv run dev.py check` before the push. CI on Linux, macOS, Windows.

## Out of scope

The block in the agent file (rejected in #208); projects with `hook_files` (#207).
