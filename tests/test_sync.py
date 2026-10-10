"""Tests for pskill_runner.sync: where sync writes the hooks and the permission rules."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pskill_runner import claude_code, codex, sync
from pskill_runner.hook_settings import SHARED_HOOKS
from pskill_runner.project import Project, find_project
from pskill_runner.sync import sync_project
from tests.skill_files import PROFILED_SKILL, write_skill

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


def test_the_shared_hooks_that_a_generator_copies_into_the_app_files_stay(tmp_path: Path) -> None:
    project = make_project(tmp_path, "hook_files: [.agents/hooks/hooks.json]\n")
    sync_project(project, check_only=False)
    source_hooks = read_json(tmp_path / SHARED_SOURCE)["hooks"]
    for app_file in (CLAUDE_SETTINGS, CODEX_HOOKS):  # what the project's own generator does: it replaces `hooks`
        settings = read_json(tmp_path / app_file) if (tmp_path / app_file).is_file() else {}
        (tmp_path / app_file).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / app_file).write_text(json.dumps({**settings, "hooks": source_hooks}), encoding="utf-8")

    assert sync_project(project, check_only=True) == []
    sync_project(project, check_only=False)

    for app_file in (CLAUDE_SETTINGS, CODEX_HOOKS):
        assert hook_commands(read_json(tmp_path / app_file), "Stop") == [first_command(SHARED_HOOKS, "Stop")]


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


def fake_sync_process(
    monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str, stderr: str = ""
) -> list[list[str]]:
    """Replace the `uv run` process with a recorded result. Return the list that collects each command."""
    commands: list[list[str]] = []

    def run_recorded(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", run_recorded)
    return commands


def test_the_sync_after_an_update_runs_the_installed_runner_and_returns_its_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_project(tmp_path)
    commands = fake_sync_process(monkeypatch, 0, ".claude/settings.json was updated\n\nEverything is up to date.\n")

    lines, worked = sync.sync_with_the_installed_runner(project)

    assert commands == [["uv", "run", str(tmp_path / ".pskill" / "pskill.py"), "sync"]]
    assert lines == [".claude/settings.json was updated"]
    assert worked


def test_a_failed_sync_after_an_update_tells_how_to_run_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_sync_process(monkeypatch, 1, "", stderr="ModuleNotFoundError: jinja2\n")

    lines, worked = sync.sync_with_the_installed_runner(make_project(tmp_path))

    assert lines == [
        "The sync after the update failed. Run `uv run .pskill/pskill.py sync`. ModuleNotFoundError: jinja2"
    ]
    assert not worked


def test_sync_writes_the_profile_agent_that_a_skill_uses_and_check_reports_it_stale(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_skill(project.skills_folder, "fanout", PROFILED_SKILL)

    assert ".claude/agents/pskill-read.md is out of date" in sync_project(project, check_only=True)
    assert ".claude/agents/pskill-read.md was created" in sync_project(project, check_only=False)
    assert sync_project(project, check_only=True) == []
