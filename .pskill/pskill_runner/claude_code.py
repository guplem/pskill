"""Claude Code specifics: the project settings that pskill manages, and the hook responses.

Verified against the Claude Code docs on 2026-09-28:
- Hook settings shape, Stop decision control, SessionStart stdout as context, ${CLAUDE_PROJECT_DIR}:
  https://code.claude.com/docs/en/hooks
- Permission rule syntax `Bash(<prefix> *)`: https://code.claude.com/docs/en/permissions
- Claude Code sets CLAUDECODE=1 for the commands it runs: https://code.claude.com/docs/en/env-vars
"""

import json
from pathlib import Path
from typing import Any

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


class SettingsError(Exception):
    """A harness settings file cannot be updated safely."""


def sync_claude_settings(project_root: Path, check_only: bool) -> bool:
    """Add the pskill hooks and the permission rule to `.claude/settings.json`. Return whether it changed.

    Only pskill's own entries change: hook handlers that run `.pskill/pskill.py hook`, and
    PERMISSION_RULE. Every other key, hook, and rule stays as it is.
    """
    path = project_root / SETTINGS_RELATIVE_PATH
    settings = read_settings(path)
    updated = with_pskill_entries(settings)
    if updated == settings:
        return False
    if not check_only:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8", newline="\n")
    return True


def read_settings(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SettingsError(f"{path} is not valid JSON ({error}). Fix it, then run `pskill sync` again.") from error
    if not isinstance(settings, dict):
        raise SettingsError(f"{path} must hold a JSON object.")
    return settings


def with_pskill_entries(settings: dict[str, Any]) -> dict[str, Any]:
    """A copy of the settings with pskill's hooks and permission rule in place."""
    updated = json.loads(json.dumps(settings))  # a deep copy, so the input stays unchanged
    hooks = updated.setdefault("hooks", {})
    for event, pskill_group in PSKILL_HOOKS.items():
        groups = [without_pskill_handlers(group) for group in hooks.get(event, [])]
        hooks[event] = [group for group in groups if group["hooks"]] + [pskill_group]
    allow_rules = updated.setdefault("permissions", {}).setdefault("allow", [])
    if PERMISSION_RULE not in allow_rules:
        allow_rules.append(PERMISSION_RULE)
    return dict(updated)


def is_pskill_hook(command: str) -> bool:
    """A hook command that runs pskill's `hook` subcommand, quoted or not."""
    return ".pskill/pskill.py" in command and " hook " in command


def without_pskill_handlers(group: dict[str, Any]) -> dict[str, Any]:
    handlers = [handler for handler in group.get("hooks", []) if not is_pskill_hook(handler.get("command", ""))]
    return {**group, "hooks": handlers}


def stop_response(reason: str | None) -> tuple[str, int]:
    """The Stop hook's stdout and exit code. A reason keeps Claude working, shown as hook feedback."""
    if reason is None:
        return "", 0
    feedback = {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": reason}}
    return json.dumps(feedback), 0
