"""Tests for pskill_runner.sync: where sync writes the hooks and the permission rules."""

import json
from pathlib import Path
from typing import Any

from pskill_runner import claude_code, codex
from pskill_runner.hook_settings import SHARED_HOOKS
from pskill_runner.project import Project, find_project
from pskill_runner.sync import sync_project

CLAUDE_SETTINGS = Path(".claude") / "settings.json"
CODEX_HOOKS = Path(".codex") / "hooks.json"
CODEX_RULES = Path(".codex") / "rules" / "pskill.rules"
SHARED_SOURCE = Path(".agents") / "hooks" / "hooks.json"


def make_project(root: Path, config_yaml: str = "") -> Project:
    (root / ".pskill" / "skills").mkdir(parents=True, exist_ok=True)
    (root / ".pskill" / "config.yaml").write_text(config_yaml, encoding="utf-8")
    return find_project(root)


def read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def hook_commands(settings: dict[str, Any], event: str) -> list[str]:
    return [handler["command"] for group in settings.get("hooks", {}).get(event, []) for handler in group["hooks"]]


def first_command(hooks: dict[str, dict[str, Any]], event: str) -> str:
    return str(hooks[event]["hooks"][0]["command"])


def test_by_default_each_app_file_gets_its_own_hooks_and_permission_rule(tmp_path: Path) -> None:
    sync_project(make_project(tmp_path), check_only=False)

    claude_settings = read_json(tmp_path / CLAUDE_SETTINGS)
    assert hook_commands(claude_settings, "Stop") == [first_command(claude_code.PSKILL_HOOKS, "Stop")]
    assert claude_code.PERMISSION_RULE in claude_settings["permissions"]["allow"]
    assert hook_commands(read_json(tmp_path / CODEX_HOOKS), "Stop") == [first_command(codex.PSKILL_HOOKS, "Stop")]
    assert (tmp_path / CODEX_RULES).is_file()


def test_a_listed_hook_file_gets_the_shared_hooks_and_the_app_files_lose_theirs(tmp_path: Path) -> None:
    sync_project(make_project(tmp_path), check_only=False)
    project = make_project(tmp_path, "hook_files: [.agents/hooks/hooks.json]\n")

    lines = sync_project(project, check_only=False)

    shared = read_json(tmp_path / SHARED_SOURCE)
    assert hook_commands(shared, "Stop") == [first_command(SHARED_HOOKS, "Stop")]
    assert hook_commands(shared, "SessionStart") == [first_command(SHARED_HOOKS, "SessionStart")]
    assert "'--harness', 'auto'" in first_command(SHARED_HOOKS, "Stop")
    claude_settings = read_json(tmp_path / CLAUDE_SETTINGS)
    assert hook_commands(claude_settings, "Stop") == []
    assert claude_code.PERMISSION_RULE in claude_settings["permissions"]["allow"]
    assert hook_commands(read_json(tmp_path / CODEX_HOOKS), "Stop") == []
    assert (tmp_path / CODEX_RULES).is_file()
    assert ".agents/hooks/hooks.json was updated" in lines
    assert sync_project(project, check_only=False) == []


def test_a_listed_hook_file_keeps_its_own_hooks(tmp_path: Path) -> None:
    (tmp_path / SHARED_SOURCE).parent.mkdir(parents=True)
    foreign = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "./notify.sh"}]}]}}
    (tmp_path / SHARED_SOURCE).write_text(json.dumps(foreign), encoding="utf-8")

    sync_project(make_project(tmp_path, "hook_files: [.agents/hooks/hooks.json]\n"), check_only=False)

    assert hook_commands(read_json(tmp_path / SHARED_SOURCE), "Stop") == [
        "./notify.sh",
        first_command(SHARED_HOOKS, "Stop"),
    ]


def test_permissions_decide_only_the_permission_rules(tmp_path: Path) -> None:
    sync_project(make_project(tmp_path, "permissions: []\n"), check_only=False)

    claude_settings = read_json(tmp_path / CLAUDE_SETTINGS)
    assert "permissions" not in claude_settings
    assert hook_commands(claude_settings, "Stop") == [first_command(claude_code.PSKILL_HOOKS, "Stop")]
    assert not (tmp_path / CODEX_RULES).exists()
    assert hook_commands(read_json(tmp_path / CODEX_HOOKS), "Stop") == [first_command(codex.PSKILL_HOOKS, "Stop")]
