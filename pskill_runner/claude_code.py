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

Verified against the Claude Code docs on 2026-10-10 (https://code.claude.com/docs/en/sub-agents):
- A project agent is `.claude/agents/<name>.md`; only `name` and `description` are required, and `name` is
  the `subagent_type` of the Agent call.
- A `tools` list gives only the tools named: no MCP tools and no Agent tool.
- With no `model` in the file, the Agent call's `model` sets the model, and otherwise the main model is used.
- Claude Code watches `.claude/agents/` only when the folder existed at session start.
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
PSKILL_HOOKS: dict[str, dict[str, Any]] = pskill_hooks(PROJECT_ROOT_CODE, "claude-code")


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


def profile_agent_text(profile: str) -> str:
    """The agent file of a tool profile: tools only. No prompt, and no model, so the tier still sets it."""
    return (
        f"---\nname: pskill-{profile}\ndescription: {PROFILE_AGENT_DESCRIPTION}\n"
        f"tools: {PROFILE_TOOLS[profile]}\n---\n{GENERATED_MARKER}\n"
    )
