"""The part of harness settings files that Claude Code and Codex share: JSON hooks with the same shape.

Both harnesses use `{"hooks": {"<Event>": [{"matcher": ..., "hooks": [{"type": "command", ...}]}]}}`.
pskill changes only its own hook handlers (the ones that run `.pskill/pskill.py hook`) and leaves every
other key, hook, and group as it is.
"""

import json
from pathlib import Path
from typing import Any


class SettingsError(Exception):
    """A harness settings file cannot be updated safely."""


def read_json_settings(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SettingsError(f"{path} is not valid JSON ({error}). Fix it, then run `pskill sync` again.") from error
    if not isinstance(settings, dict):
        raise SettingsError(f"{path} must hold a JSON object.")
    return settings


def is_pskill_hook(command: str) -> bool:
    """A hook command that runs pskill's `hook` subcommand, however its path is written or quoted."""
    return ".pskill/pskill.py" in command and " hook " in command


def with_pskill_hooks(settings: dict[str, Any], pskill_hooks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A copy of the settings where each event ends with pskill's hook group, and no older pskill handler."""
    updated: dict[str, Any] = json.loads(json.dumps(settings))  # a deep copy, so the input stays unchanged
    hooks = updated.setdefault("hooks", {})
    for event, pskill_group in pskill_hooks.items():
        groups = [without_pskill_handlers(group) for group in hooks.get(event, [])]
        hooks[event] = [group for group in groups if group["hooks"]] + [pskill_group]
    return updated


def without_pskill_handlers(group: dict[str, Any]) -> dict[str, Any]:
    handlers = [handler for handler in group.get("hooks", []) if not is_pskill_hook(handler.get("command", ""))]
    return {**group, "hooks": handlers}


def write_if_changed(path: Path, current: dict[str, Any], updated: dict[str, Any], check_only: bool) -> bool:
    """Write the updated settings when they differ. Return whether they differ."""
    if updated == current:
        return False
    if not check_only:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8", newline="\n")
    return True
