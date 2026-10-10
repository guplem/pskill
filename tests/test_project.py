"""Tests for pskill_runner.project."""

from pathlib import Path

import pytest

from pskill_runner.adapters import TierRow
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


def test_the_autonomous_visit_ceiling_defaults_to_150_and_can_be_set(tmp_path: Path) -> None:
    assert Config().autonomous_max_visits == 150
    assert find_project(make_project(tmp_path, "autonomous_max_visits: 40\n")).config.autonomous_max_visits == 40


def test_the_wait_settings_default_to_20_and_120_minutes_and_can_be_set(tmp_path: Path) -> None:
    assert (Config().wait_minutes, Config().max_wait_minutes) == (20, 120)
    config = find_project(make_project(tmp_path, "wait_minutes: 5\nmax_wait_minutes: 30\n")).config
    assert (config.wait_minutes, config.max_wait_minutes) == (5, 30)


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


def test_a_config_that_is_not_a_mapping_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="must be a mapping of settings"):
        find_project(make_project(tmp_path, "- retries: 2\n"))


def test_known_apps_in_permissions_are_kept(tmp_path: Path) -> None:
    config = find_project(make_project(tmp_path, "permissions: [codex, claude-code]\n")).config

    assert config.permissions == ["codex", "claude-code"]


def test_the_project_tier_rows_are_read_per_harness_and_tier(tmp_path: Path) -> None:
    config_yaml = (
        "tiers:\n"
        "  codex:\n"
        "    fast: {model: gpt-6-luna, effort: low}\n"
        "  claude-code:\n"
        "    deep: {effort: max}\n"
        "    standard: {}\n"
    )

    config = find_project(make_project(tmp_path, config_yaml)).config

    assert config.tiers == {
        "codex": {"fast": TierRow(model="gpt-6-luna", effort="low")},
        "claude-code": {"deep": TierRow(effort="max"), "standard": TierRow()},
    }


def test_no_tiers_and_an_empty_tiers_setting_keep_the_default_rows(tmp_path: Path) -> None:
    assert find_project(make_project(tmp_path)).config.tiers == {}
    assert find_project(make_project(tmp_path / "empty", "tiers:\n")).config.tiers == {}


@pytest.mark.parametrize(
    ("tiers_yaml", "message"),
    [
        ("[codex]", r"'tiers' must be a mapping of harnesses"),
        ("{generic: {}}", r"unknown harness 'generic' in tiers \(known harnesses: claude-code, codex\)"),
        ("{codex: [fast]}", r"'tiers\.codex' must be a mapping of tiers"),
        ("{codex: {quick: {}}}", r"unknown tier 'quick' in tiers\.codex \(known tiers: fast, standard, deep\)"),
        ("{codex: {fast: low}}", r"'tiers\.codex\.fast' must be a mapping"),
        ("{codex: {fast: {reasoning_effort: low}}}", r"unknown key 'reasoning_effort' in tiers\.codex\.fast"),
        ("{codex: {fast: {model: ''}}}", r"'tiers\.codex\.fast\.model' must be a non-empty text"),
        ("{codex: {fast: {model: '  '}}}", r"'tiers\.codex\.fast\.model' must be a non-empty text"),
        ("{codex: {fast: {effort: 3}}}", r"'tiers\.codex\.fast\.effort' must be a non-empty text"),
    ],
)
def test_a_wrong_tiers_setting_is_an_error(tmp_path: Path, tiers_yaml: str, message: str) -> None:
    with pytest.raises(ProjectError, match=message):
        find_project(make_project(tmp_path, f"tiers: {tiers_yaml}\n"))
