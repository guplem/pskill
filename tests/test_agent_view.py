"""Tests for pskill_runner.agent_view: the agents list and the agent screen of the viewer."""

from pathlib import Path

import pytest

from pskill_runner.agent_view import AgentEditError, agent_detail, agents_overview, save_agent
from pskill_runner.project import Project, find_project
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill
from tests.test_engine_blocks import NAMED_PARALLEL_SKILL

CHECKER_TEXT = "\nYou check one item.\n\nRules:\n- Read it in full.\n"


def make_project(tmp_path: Path) -> Project:
    skills_folder = tmp_path / ".pskill" / "skills"
    write_skill(skills_folder, "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)
    write_skill(skills_folder, "fanout", NAMED_PARALLEL_SKILL)
    agents_folder = tmp_path / ".pskill" / "agents"
    agents_folder.mkdir(parents=True)
    (agents_folder / "checker.md").write_text(CHECKER_TEXT, encoding="utf-8")
    (agents_folder / "unused.md").write_text("You are not used yet.\n", encoding="utf-8")
    return find_project(tmp_path)


def test_the_agents_list_has_every_agent_with_its_first_line_and_its_skills(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    agents = agents_overview(project)["agents"]

    assert agents == [
        {"name": "checker", "summary": "You check one item.", "used_by": ["fanout"]},
        {"name": "unused", "summary": "You are not used yet.", "used_by": []},
    ]


def test_a_project_without_an_agents_folder_has_no_agents(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)

    assert agents_overview(find_project(tmp_path)) == {"agents": []}


def test_an_agent_with_no_text_has_an_empty_summary(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project.agents_folder / "unused.md").write_text("\n  \n", encoding="utf-8")

    agents = agents_overview(project)["agents"]

    assert agents[1] == {"name": "unused", "summary": "", "used_by": []}


def test_the_agent_screen_has_the_text_and_the_blocks_that_use_it(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    detail = agent_detail(project, "checker")

    assert detail == {
        "name": "checker",
        "file": ".pskill/agents/checker.md",
        "text": CHECKER_TEXT,
        "used_by": [{"skill": "fanout", "blocks": ["check"]}],
    }


@pytest.mark.parametrize("name", ["missing", "../skills/fanout/skill", "checker.md", ""])
def test_a_name_that_is_not_an_agent_has_no_detail(tmp_path: Path, name: str) -> None:
    assert agent_detail(make_project(tmp_path), name) is None


def test_saving_an_agent_replaces_its_text(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    save_agent(project, "checker", "You check one item, twice.\n")

    assert (project.agents_folder / "checker.md").read_text(encoding="utf-8") == "You check one item, twice.\n"


def test_saving_an_agent_keeps_its_crlf_line_ends(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project.agents_folder / "checker.md").write_bytes(b"Old.\r\n")

    save_agent(project, "checker", "New.\nSecond line.\n")

    assert (project.agents_folder / "checker.md").read_bytes() == b"New.\r\nSecond line.\r\n"


def test_saving_an_unknown_agent_is_refused_and_writes_no_file(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    with pytest.raises(AgentEditError, match="no agent"):
        save_agent(project, "../skills/fanout/skill", "x")

    assert sorted(path.name for path in project.agents_folder.iterdir()) == ["checker.md", "unused.md"]
