"""Tests for pskill_runner.project."""

from pathlib import Path

import pytest

from pskill_runner.project import Config, ProjectError, find_project


def make_project(root: Path, config_yaml: str | None = None) -> Path:
    (root / ".pskill" / "skills").mkdir(parents=True)
    if config_yaml is not None:
        (root / ".pskill" / "config.yaml").write_text(config_yaml, encoding="utf-8")
    return root


def test_find_project_walks_up_to_the_folder_with_dot_pskill(tmp_path: Path) -> None:
    make_project(tmp_path)
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)

    project = find_project(nested)

    assert project.root == tmp_path
    assert project.skills_folder == tmp_path / ".pskill" / "skills"
    assert project.runs_folder == tmp_path / ".pskill" / "runs"


def test_find_project_fails_outside_a_project(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match=r"No .pskill folder"):
        find_project(tmp_path)


def test_config_defaults_apply_without_a_config_file(tmp_path: Path) -> None:
    assert find_project(make_project(tmp_path)).config == Config()


def test_config_values_override_the_defaults(tmp_path: Path) -> None:
    project = find_project(make_project(tmp_path, "retries: 5\ndefault_mode: autonomous\n"))

    assert project.config.retries == 5
    assert project.config.default_mode == "autonomous"
    assert project.config.script_timeout_s == 300


def test_an_unknown_config_key_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="unknown setting 'retry'"):
        find_project(make_project(tmp_path, "retry: 5\n"))


def test_by_default_both_apps_get_the_hooks_in_their_own_files_and_the_permission_rules(tmp_path: Path) -> None:
    config = find_project(make_project(tmp_path)).config

    assert config.permissions == ["claude-code", "codex"]
    assert config.hook_files == [".claude/settings.json", ".codex/hooks.json"]


def test_the_old_harnesses_setting_names_its_replacements(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match=r"'harnesses' is now 'permissions'.*'hook_files'"):
        find_project(make_project(tmp_path, "harnesses: [codex]\n"))


def test_an_unknown_app_in_permissions_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="unknown app 'vim' in permissions"):
        find_project(make_project(tmp_path, "permissions: [vim]\n"))
