"""Claude Code specifics: the project settings and profile agents that pskill manages, and the hook responses.

Verified against the Claude Code docs on 2026-09-28:
- Hook settings shape, Stop decision control, SessionStart stdout as context, ${CLAUDE_PROJECT_DIR}:
  https://code.claude.com/docs/en/hooks
- Permission rule syntax `Bash(<prefix> *)`: https://code.claude.com/docs/en/permissions
- Claude Code sets CLAUDECODE=1 for the commands it runs: https://code.claude.com/docs/en/env-vars
- Claude Code reads project skills from `.claude/skills/` only: https://code.claude.com/docs/en/skills

Verified on 2026-10-10, for `pskill wait`:
- The Stop hook fires when the turn ends, also while background work runs:
  https://code.claude.com/docs/en/hooks#stop-input
- A background command keeps running after the turn ends, and Claude takes another turn when it ends:
  https://code.claude.com/docs/en/tools-reference#when-a-background-command-stops
- No time limit in a local session; 30 minutes by default (up to 2 hours with `timeout`) in a cloud
  session: https://code.claude.com/docs/en/tools-reference#time-limit-for-background-commands

Verified on 2026-11-04, for background scripts (`run-script`):
- A foreground Bash call stops at 10 minutes (`BASH_MAX_TIMEOUT_MS`); a background command takes `timeout` up
  to 2 hours in a cloud session: https://code.claude.com/docs/en/tools-reference ("Timeout and output limits")
- After a background command that the main conversation started, Claude takes one more turn with the outcome:
  https://code.claude.com/docs/en/headless#background-tasks-at-exit

Verified against the Claude Code docs on 2026-10-10 (https://code.claude.com/docs/en/sub-agents):
- A project agent is `.claude/agents/<name>.md`; only `name` and `description` are required, and `name` is
  the `subagent_type` of the Agent call.
- A `tools` list gives only the tools named: no MCP tools and no Agent tool.
- With no `model` in the file, the Agent call's `model` sets the model, and otherwise the main model is used.
- Claude Code watches `.claude/agents/` only when the folder existed at session start.

Verified against the Claude Code docs on 2026-11-16, for the git block (https://code.claude.com/docs/en/hooks):
- A hook's input carries `agent_id` and `agent_type` when it fires inside a subagent. The `agent_type` of a
  custom subagent is its agent file's `name` (`pskill-read`). A session started with `--agent` also has an
  `agent_type`, so only `agent_id` tells a subagent from the main agent.
- A PreToolUse hook denies a call with `hookSpecificOutput.permissionDecision: "deny"` and a
  `permissionDecisionReason` that Claude sees, on stdout with exit code 0.

Verified in real sessions on 2026-11-17 (Claude Code 2.1.311 headless and interactive, 2.1.326 in a cloud
session; https://github.com/guplem/pskill/issues/208#issuecomment-6949416311 and #issuecomment-6949785071):
- A `pskill-read` subagent's Bash call carries `agent_id` and `agent_type: "pskill-read"`; the main agent's
  carries neither. The payloads are in `tests/fixtures/claude-code/`.
- A hook in the agent file's frontmatter gets the same payload, but it is skipped in `-p` sessions, in untrusted
  folders, and in cloud sessions, so the git block stays in `.claude/settings.json`.
"""

import json
from pathlib import Path
from typing import Any

from pskill_runner.hook_settings import (
    SettingsError,
    pskill_hooks,
    read_json_settings,
    write_if_changed,
)
from pskill_runner.stubs import GENERATED_MARKER

__all__ = [
    "AGENTS_RELATIVE_FOLDER",
    "PERMISSION_RULE",
    "SETTINGS_RELATIVE_PATH",
    "SettingsError",
    "pre_tool_use_response",
    "profile_agent_text",
    "stop_response",
    "sync_claude_permission",
]

SETTINGS_RELATIVE_PATH = Path(".claude") / "settings.json"
PERMISSION_RULE = "Bash(uv run .pskill/pskill.py *)"
AGENTS_RELATIVE_FOLDER = Path(".claude") / "agents"
# The tools of each tool profile. `Write` lets a subagent write a long answer to its answer file
# (`submit --file`), which the Bash tool on Windows cannot do with a long heredoc.
PROFILE_TOOLS = {
    "read": "Bash, Read, Grep, Glob, Write",
    "web": "Bash, Read, Grep, Glob, Write, WebFetch, WebSearch",
}
# No harness can hide an agent from automatic use, so the description asks the agent not to pick it.
PROFILE_AGENT_DESCRIPTION = "Only for pskill tasks. Never choose it on your own."
# Claude Code sets CLAUDE_PROJECT_DIR for its hooks, so a hook works from any folder of the project.
PROJECT_ROOT_CODE = "os.environ.get('CLAUDE_PROJECT_DIR', '')"
PSKILL_HOOKS: dict[str, dict[str, Any]] = pskill_hooks(PROJECT_ROOT_CODE, "claude-code", block_git=True)


def sync_claude_permission(project_root: Path, check_only: bool) -> bool:
    """Add the permission rule to `.claude/settings.json`. Return whether it changed."""
    path = project_root / SETTINGS_RELATIVE_PATH
    settings = read_json_settings(path)
    updated = json.loads(json.dumps(settings))  # a deep copy, so the input stays unchanged
    allow_rules = updated.setdefault("permissions", {}).setdefault("allow", [])
    if PERMISSION_RULE not in allow_rules:
        allow_rules.append(PERMISSION_RULE)
    return write_if_changed(path, settings, updated, check_only)


def stop_response(reason: str | None) -> tuple[str, int]:
    """The Stop hook's stdout and exit code. A reason keeps Claude working, shown as hook feedback."""
    if reason is None:
        return "", 0
    feedback = {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": reason}}
    return json.dumps(feedback), 0


def pre_tool_use_response(reason: str | None) -> tuple[str, int]:
    """The PreToolUse hook's stdout and exit code. A reason denies the tool call and shows Claude the reason.

    The denial is JSON with exit code 0: exit code 2 would also block, and a failed `uv run` exits 2.
    """
    if reason is None:
        return "", 0
    decision = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }
    return json.dumps({"hookSpecificOutput": decision}), 0


READ_PROFILE_RULE = "Do not run git commands that change the repository, such as commit, push, checkout, or reset."


def profile_agent_text(profile: str) -> str:
    """The agent file of a tool profile: its tools, and no model, so the tier still sets it.

    The skill's prompt never goes here. The `read` profile gets one fixed rule: its subagent works in the main
    checkout, so a git command that changes the repository would change the main agent's work.
    """
    rule = f"{READ_PROFILE_RULE}\n" if profile == "read" else ""
    return (
        f"---\nname: pskill-{profile}\ndescription: {PROFILE_AGENT_DESCRIPTION}\n"
        f"tools: {PROFILE_TOOLS[profile]}\n---\n{GENERATED_MARKER}\n{rule}"
    )
