"""Tests for the Claude Code adapter: detection, settings merge, and hook responses."""

import json
from pathlib import Path

import pytest

from pskill_runner.adapters import adapter_for, detect_harness
from pskill_runner.claude_code import (
    PERMISSION_RULE,
    PROJECT_ROOT_CODE,
    PSKILL_HOOKS,
    SettingsError,
    stop_response,
    sync_claude_permission,
)
from pskill_runner.hook_settings import hook_command, sync_hook_file

SETTINGS_PATH = Path(".claude") / "settings.json"
STOP_COMMAND = hook_command(PROJECT_ROOT_CODE, "stop", "claude-code")
SESSION_START_COMMAND = hook_command(PROJECT_ROOT_CODE, "session-start", "claude-code")


def sync_claude_settings(root: Path, check_only: bool) -> bool:
    """What the default sync does for Claude Code: its hooks and its permission rule, in one file."""
    hooks_changed = sync_hook_file(root / SETTINGS_PATH, PSKILL_HOOKS, check_only)
    return sync_claude_permission(root, check_only) or hooks_changed


def read_settings(root: Path) -> dict[str, object]:
    return dict(json.loads((root / SETTINGS_PATH).read_text(encoding="utf-8")))


def hook_commands(settings: dict[str, object], event: str) -> list[str]:
    hooks = settings["hooks"]
    assert isinstance(hooks, dict)
    return [handler["command"] for group in hooks.get(event, []) for handler in group["hooks"]]


def test_claude_code_is_detected_from_its_environment_variable() -> None:
    assert detect_harness({"CLAUDECODE": "1"}) == "claude-code"
    assert detect_harness({}) == "generic"


def test_the_claude_code_adapter_names_its_own_tools() -> None:
    adapter = adapter_for("claude-code")

    assert "AskUserQuestion" in adapter.question_wording
    assert adapter.can_spawn_subagents is True
    assert "general-purpose" in adapter.subagent_wording


def test_sync_adds_the_two_hooks_and_the_permission_rule(tmp_path: Path) -> None:
    changed = sync_claude_settings(tmp_path, check_only=False)

    settings = read_settings(tmp_path)
    assert changed is True
    assert hook_commands(settings, "Stop") == [STOP_COMMAND]
    assert hook_commands(settings, "SessionStart") == [SESSION_START_COMMAND]
    permissions = settings["permissions"]
    assert isinstance(permissions, dict)
    assert permissions["allow"] == [PERMISSION_RULE]


def test_sync_is_idempotent(tmp_path: Path) -> None:
    sync_claude_settings(tmp_path, check_only=False)
    before = (tmp_path / SETTINGS_PATH).read_text(encoding="utf-8")

    assert sync_claude_settings(tmp_path, check_only=False) is False
    assert (tmp_path / SETTINGS_PATH).read_text(encoding="utf-8") == before


def test_sync_keeps_foreign_hooks_rules_and_keys(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    foreign = {
        "model": "opus",
        "permissions": {"allow": ["Bash(npm test)"], "deny": ["Read(.env)"]},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "./notify.sh"}]}]},
    }
    (tmp_path / SETTINGS_PATH).write_text(json.dumps(foreign), encoding="utf-8")

    sync_claude_settings(tmp_path, check_only=False)

    settings = read_settings(tmp_path)
    assert settings["model"] == "opus"
    assert settings["permissions"] == {"allow": ["Bash(npm test)", PERMISSION_RULE], "deny": ["Read(.env)"]}
    assert hook_commands(settings, "Stop")[0] == "./notify.sh"
    assert len(hook_commands(settings, "Stop")) == 2


def test_sync_replaces_an_old_pskill_hook_instead_of_adding_a_second_one(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    old_command = 'uv run "${CLAUDE_PROJECT_DIR}/.pskill/pskill.py" hook stop --harness claude-code'
    old = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": old_command}]}]}}
    (tmp_path / SETTINGS_PATH).write_text(json.dumps(old), encoding="utf-8")

    sync_claude_settings(tmp_path, check_only=False)

    assert hook_commands(read_settings(tmp_path), "Stop") == [STOP_COMMAND]


def test_check_only_reports_without_writing(tmp_path: Path) -> None:
    assert sync_claude_settings(tmp_path, check_only=True) is True
    assert not (tmp_path / SETTINGS_PATH).exists()


def test_a_settings_file_that_does_not_parse_is_never_overwritten(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / SETTINGS_PATH).write_text("{ broken", encoding="utf-8")

    with pytest.raises(SettingsError, match="not valid JSON"):
        sync_claude_settings(tmp_path, check_only=False)

    assert (tmp_path / SETTINGS_PATH).read_text(encoding="utf-8") == "{ broken"


def test_a_blocking_stop_response_gives_claude_the_reason_as_feedback() -> None:
    stdout, exit_code = stop_response("Continue the run.")

    assert exit_code == 0
    assert json.loads(stdout) == {
        "hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": "Continue the run."}
    }


def test_an_allowing_stop_response_prints_nothing() -> None:
    assert stop_response(None) == ("", 0)
