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


def hook_command(root_code: str, subcommand: str, harness: str) -> str:
    """A hook command that runs `pskill.py hook <subcommand>` only when the runner file exists.

    Without the file, the command exits 0 with no output. A failed `uv run` exits 2, and exit code 2
    tells Claude Code and Codex to block the stop. `root_code` is the Python expression for the project
    root. The command is one `python -c` call through uv, so bash, PowerShell, and cmd read it the same:
    its double quotes hold no `$`, backslash, or percent sign, only single quotes.
    """
    code = "; ".join(
        [
            "import os, subprocess, sys",
            f"root = {root_code}",
            "runner = root + '/.pskill/pskill.py'",
            f"arguments = ['uv', 'run', runner, 'hook', '{subcommand}', '--harness', '{harness}']",
            "sys.exit(subprocess.call(arguments) if os.path.isfile(runner) else 0)",
        ]
    )
    return f'uv run --no-project python -c "{code}"'


# The project root for a hook in a file that several apps read: the git root of the session's folder.
GIT_ROOT_CODE = "subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip()"


def pskill_hooks(root_code: str, harness: str) -> dict[str, dict[str, Any]]:
    """pskill's two hook groups, as they appear in a hooks file."""
    return {
        "Stop": {"hooks": [{"type": "command", "command": hook_command(root_code, "stop", harness)}]},
        "SessionStart": {
            "matcher": "startup|resume|clear|compact",
            "hooks": [{"type": "command", "command": hook_command(root_code, "session-start", harness)}],
        },
    }


# For a file that no single app owns, such as a project's own source of hooks: the runner detects the app.
SHARED_HOOKS = pskill_hooks(GIT_ROOT_CODE, "auto")
SHARED_COMMANDS = frozenset(handler["command"] for group in SHARED_HOOKS.values() for handler in group["hooks"])


def is_pskill_hook(command: str) -> bool:
    """A hook command that runs pskill's `hook` subcommand, however its path is written or quoted."""
    return ".pskill/pskill.py" in command and (" hook " in command or "'hook'" in command)


def with_pskill_hooks(settings: dict[str, Any], pskill_hooks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A copy of the settings where each event ends with pskill's hook group, and no older pskill handler."""
    updated: dict[str, Any] = json.loads(json.dumps(settings))  # a deep copy, so the input stays unchanged
    hooks = updated.setdefault("hooks", {})
    for event, pskill_group in pskill_hooks.items():
        groups = [without_pskill_handlers(group) for group in hooks.get(event, [])]
        hooks[event] = [group for group in groups if group["hooks"]] + [pskill_group]
    return updated


def without_pskill_hooks(settings: dict[str, Any], keep: frozenset[str] = frozenset()) -> dict[str, Any]:
    """A copy of the settings with every pskill handler removed (except the `keep` commands), and the groups that
    it leaves empty."""
    updated: dict[str, Any] = json.loads(json.dumps(settings))
    hooks = updated.get("hooks", {})
    for event in list(hooks):
        hooks[event] = [
            group for group in (without_pskill_handlers(group, keep) for group in hooks[event]) if group["hooks"]
        ]
        if not hooks[event]:
            del hooks[event]
    return updated


def sync_hook_file(path: Path, pskill_hooks: dict[str, dict[str, Any]], check_only: bool) -> bool:
    """Put pskill's hooks into one hooks file. Return whether it changed."""
    settings = read_json_settings(path)
    return write_if_changed(path, settings, with_pskill_hooks(settings, pskill_hooks), check_only)


def remove_pskill_hooks(path: Path, check_only: bool) -> bool:
    """Take the app's own pskill hooks out of an app file that is not in `hook_files`. Return whether it changed.

    The shared hooks stay: only a project's own generator puts them there, when it copies a listed hooks source.
    """
    if not path.is_file():
        return False
    settings = read_json_settings(path)
    return write_if_changed(path, settings, without_pskill_hooks(settings, keep=SHARED_COMMANDS), check_only)


def without_pskill_handlers(group: dict[str, Any], keep: frozenset[str] = frozenset()) -> dict[str, Any]:
    handlers = [
        handler
        for handler in group.get("hooks", [])
        if not is_pskill_hook(handler.get("command", "")) or handler.get("command") in keep
    ]
    return {**group, "hooks": handlers}


def write_if_changed(path: Path, current: dict[str, Any], updated: dict[str, Any], check_only: bool) -> bool:
    """Write the updated settings when they differ. Return whether they differ."""
    if updated == current:
        return False
    if not check_only:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8", newline="\n")
    return True
