"""Tests for pskill_runner.profile_agents: the harness agents of the tool profiles that skills use."""

from pathlib import Path

import pytest

from pskill_runner.claude_code import profile_agent_text
from pskill_runner.profile_agents import sync_profile_agents, used_profiles
from pskill_runner.project import Project, find_project
from pskill_runner.skill_loader import load_catalog
from pskill_runner.stubs import GENERATED_MARKER, StubError
from tests.skill_files import PROFILED_SKILL, write_skill

READ_AGENT = Path(".claude") / "agents" / "pskill-read.md"
WEB_AGENT = Path(".claude") / "agents" / "pskill-web.md"


def make_project(root: Path, tools_line: str = "    tools: read\n", config_yaml: str = "") -> Project:
    write_skill(root / ".pskill" / "skills", "fanout", PROFILED_SKILL.replace("    tools: read\n", tools_line))
    (root / ".pskill" / "config.yaml").write_text(config_yaml, encoding="utf-8")
    return find_project(root)


def sync(project: Project, check_only: bool = False) -> list[tuple[str, str]]:
    catalog = load_catalog(project.skills_folder, project.agents_folder)
    changes = sync_profile_agents(project, catalog, check_only)
    return [(change.path.relative_to(project.root).as_posix(), change.action) for change in changes]


def test_a_written_profile_is_used_and_a_computed_one_uses_every_profile(tmp_path: Path) -> None:
    written = make_project(tmp_path / "a")
    computed = make_project(tmp_path / "b", '    tools: "{{ item }}"\n')
    none = make_project(tmp_path / "c", "")

    assert used_profiles(load_catalog(written.skills_folder, written.agents_folder)) == ["read"]
    assert used_profiles(load_catalog(computed.skills_folder, computed.agents_folder)) == ["read", "web"]
    assert used_profiles(load_catalog(none.skills_folder, none.agents_folder)) == []


def test_sync_writes_the_agent_of_each_used_profile_only(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    assert sync(project) == [(READ_AGENT.as_posix(), "created")]
    assert (tmp_path / READ_AGENT).read_text(encoding="utf-8") == profile_agent_text("read")
    assert not (tmp_path / WEB_AGENT).exists()


def test_sync_is_idempotent(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    sync(project)

    assert sync(project) == []


def test_check_only_reports_changes_without_writing(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    assert sync(project, check_only=True) == [(READ_AGENT.as_posix(), "created")]
    assert not (tmp_path / ".claude").exists()


def test_a_stale_agent_is_updated(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    sync(project)
    (tmp_path / READ_AGENT).write_text(f"---\nname: pskill-read\n---\n{GENERATED_MARKER}\nOld.\n", encoding="utf-8")

    assert sync(project) == [(READ_AGENT.as_posix(), "updated")]
    assert (tmp_path / READ_AGENT).read_text(encoding="utf-8") == profile_agent_text("read")


def test_the_agent_of_a_profile_that_no_skill_uses_is_deleted(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    sync(project)
    make_project(tmp_path, "")

    assert sync(project) == [(READ_AGENT.as_posix(), "deleted")]
    assert not (tmp_path / READ_AGENT).exists()


def test_a_hand_written_agent_with_the_same_name_stops_sync(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    hand_written = tmp_path / READ_AGENT
    hand_written.parent.mkdir(parents=True)
    hand_written.write_text("---\nname: pskill-read\n---\nMine.\n", encoding="utf-8")

    with pytest.raises(StubError, match="hand-written"):
        sync(project)

    assert hand_written.read_text(encoding="utf-8").endswith("Mine.\n")


def test_other_hand_written_agents_are_left_alone(tmp_path: Path) -> None:
    project = make_project(tmp_path, "")
    other = tmp_path / ".claude" / "agents" / "pskill-mine.md"
    other.parent.mkdir(parents=True)
    other.write_text("---\nname: pskill-mine\n---\nMine.\n", encoding="utf-8")

    assert sync(project) == []
    assert other.is_file()


def test_no_agent_is_written_when_claude_code_is_not_in_permissions(tmp_path: Path) -> None:
    project = make_project(tmp_path, config_yaml="permissions: [codex]\n")

    assert sync(project) == []


def test_agents_are_written_with_lf_line_endings(tmp_path: Path) -> None:
    sync(make_project(tmp_path))

    assert b"\r\n" not in (tmp_path / READ_AGENT).read_bytes()
