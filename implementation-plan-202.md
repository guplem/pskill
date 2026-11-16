# Plan: block a `read` profile subagent's repository-changing git commands (#202)

## 1. Goal and acceptance criteria
- On Claude Code, a `pskill-read` subagent's `git commit`/`push`/etc. is refused before it runs, with a reason that tells it to end its turn.
- The main agent's git commands are never refused.
- SPEC says Claude Code blocks; Codex and generic only ask.

## 2. Decisions
- Subagent test: `agent_id` present AND `agent_type == "pskill-read"` (a `--agent` main session also sets `agent_type`). Missing fields, bad input, or an unparsable command: allow.
- Deny: JSON on stdout, exit 0 (`hookSpecificOutput.permissionDecision: deny` + `permissionDecisionReason`). Never exit 2.
- Claude-only: added to `claude_code.PSKILL_HOOKS` only. Codex and `SHARED_HOOKS` unchanged (principle 4).
- Blocked git subcommands: commit, push, checkout, switch, reset, branch, merge, rebase, tag. Simple rule, no read-form exceptions: all of them are refused. status/diff/log/show stay allowed.
- Matching on tokens (shlex-style split), skipping git options (`-C x`, `-c k=v`, `--git-dir=...`), across `&&`, `;`, `|`, `||` chains. Best effort, documented as a limitation (SPEC 3.1).
- Reason: short, tells the subagent to end its turn; prints no command or run key.
- No new permission rule (D28). `general-purpose` fallback is not covered (documented).
- Version 1.4.0.

## 3. Approach
- `hooks.py`: pure `git_block_reason(hook_input: dict) -> str | None` plus small helpers, constant `BLOCKED_GIT_SUBCOMMANDS`. Copies `stop_hook_reason` style.
- `claude_code.py`: `pre_tool_use_response(reason)` next to `stop_response`; docstring "Verified on <date>" block with the hooks doc URL; `PSKILL_HOOKS` gets the `PreToolUse` group.
- `hook_settings.py`: `PRE_TOOL_USE_TIMEOUT_S = 10`; `pskill_hooks(..., block_git: bool = False)` adds `{"matcher": "Bash", ...}` via `hook_command(root, "pre-tool-use", harness)`.
- `cli.py`: add `pre-tool-use` choice and one branch calling hooks + claude_code.

## 4. Steps (each red-green)
1. `git_block_reason` logic tests + code (subagent vs main, each subcommand, options, chains, allowed commands, malformed input).
2. `claude_code.pre_tool_use_response` test + code.
3. `pskill_hooks(block_git=True)` group (matcher, timeout), Claude-only; update `test_every_hook_has_a_timeout` and hook-command tests.
4. `cli` `hook pre-tool-use` with stdin JSON (deny, allow, non-Claude harness prints nothing, errors swallowed).
5. Sync: `.claude/settings.json` via `uv run dev.py sync`; sync tests for the merged group.
6. Docs, version bump, CHANGELOG.

## 5. Lists
**New cases (test):** subagent + each of 9 subcommands refused (test_hooks); main agent (no agent_id) allowed; other agent_type allowed; `git status/diff/log` allowed; `git -C x commit`, `git -c a=b push` refused; chain `a && git push` refused; non-Bash/no command/invalid input allowed; non-claude harness silent (test_cli); group has matcher Bash and timeout (test_hook_settings, test_claude_code); Codex and shared hooks have no PreToolUse (test_hook_commands, test_codex); sync adds/idempotent (test_sync).

**Stale texts (git grep):** `.pskill/config.yaml:3`, `pskill_runner/install.py:43` ("the two hooks"); README.md:51 "Two hooks" and the `read` agent "only asks" line (~55); SPEC.md:113 (`hook stop|session-start`), 645 (heading "two only"), 789, 1281 (section 18 row "Two hooks"), 9.1 capability table, hook-timeout bullet (~643), section 15 `hook` row, 3.1 limitations; `.claude/settings.json` (generated).

**Reused code:** `hook_command`, `with_pskill_hooks`, `is_pskill_hook`, `read_hook_input`, the Stop hook chain pattern; no existing git parsing found (new).

## 6. Checks
`uv run dev.py sync`, `uv run dev.py fast` while building, `uv run dev.py check` before push; CI on all three OSes.

## 7. Out of scope
Worktree-per-job; blocking on Codex/generic; other tools (Write); covering the `general-purpose` fallback; a live-session payload fixture beyond a saved sample if reachable.
