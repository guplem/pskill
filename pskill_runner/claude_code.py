"""Claude Code specifics: the project settings that pskill manages, and the hook responses.

Verified against the Claude Code docs on 2026-09-28:
- Hook settings shape, Stop decision control, SessionStart stdout as context, ${CLAUDE_PROJECT_DIR}:
  https://code.claude.com/docs/en/hooks
- Permission rule syntax `Bash(<prefix> *)`: https://code.claude.com/docs/en/permissions
- Claude Code sets CLAUDECODE=1 for the commands it runs: https://code.claude.com/docs/en/env-vars
- Claude Code reads project skills from `.claude/skills/` only: https://code.claude.com/docs/en/skills
"""

import json
from pathlib import Path
from typing import Any

from pskill_runner.hook_settings import SettingsError, read_json_settings, with_pskill_hooks, write_if_changed

__all__ = ["PERMISSION_RULE", "SETTINGS_RELATIVE_PATH", "SettingsError", "stop_response", "sync_claude_settings"]

SETTINGS_RELATIVE_PATH = Path(".claude") / "settings.json"
PERMISSION_RULE = "Bash(uv run .pskill/pskill.py *)"
# ${CLAUDE_PROJECT_DIR} is a placeholder that Claude Code fills in, so the hook works from any folder.
RUNNER_FOR_HOOKS = 'uv run "${CLAUDE_PROJECT_DIR}/.pskill/pskill.py"'
PSKILL_HOOKS: dict[str, dict[str, Any]] = {
    "Stop": {
        "hooks": [{"type": "command", "command": f"{RUNNER_FOR_HOOKS} hook stop --harness claude-code"}],
    },
    "SessionStart": {
        "matcher": "startup|resume|clear|compact",
        "hooks": [{"type": "command", "command": f"{RUNNER_FOR_HOOKS} hook session-start --harness claude-code"}],
    },
}


def sync_claude_settings(project_root: Path, check_only: bool) -> bool:
    """Add the pskill hooks and the permission rule to `.claude/settings.json`. Return whether it changed."""
    path = project_root / SETTINGS_RELATIVE_PATH
    settings = read_json_settings(path)
    updated = with_pskill_hooks(settings, PSKILL_HOOKS)
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
