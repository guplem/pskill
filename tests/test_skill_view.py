"""Tests for pskill_runner.skill_view: the skills list and the skill screen of the viewer."""

from pathlib import Path
from typing import Any

from pskill_runner.engine import start_run
from pskill_runner.project import Project, find_project
from pskill_runner.skill_view import skill_detail, skills_overview
from tests.skill_files import PER_ITEM_SKILL, PLAN_SKILL, PLAN_SKILL_FILES, write_skill
from tests.test_engine_blocks import CHILD_SKILL, PARENT_SKILL, SCRIPT_SKILL


def make_project(tmp_path: Path) -> Project:
    skills_folder = tmp_path / ".pskill" / "skills"
    write_skill(skills_folder, "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)
    write_skill(skills_folder, "parent", PARENT_SKILL)
    write_skill(skills_folder, "child", CHILD_SKILL)
    write_skill(skills_folder, "scripted", SCRIPT_SKILL)
    write_skill(skills_folder, "per-item", PER_ITEM_SKILL)
    write_skill(skills_folder, "broken", "schema: pskill/v1\nid: broken\n")
    return find_project(tmp_path)


def detail_of(project: Project, skill_id: str) -> dict[str, Any]:
    detail = skill_detail(project, skill_id)
    assert detail is not None
    return detail


# --- the skills list ----------------------------------------------------------------------------


def test_the_skills_list_has_every_skill_also_without_runs(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")

    skills = {skill["skill_id"]: skill for skill in skills_overview(project)["skills"]}

    assert list(skills) == ["broken", "child", "parent", "per-item", "plan-work", "scripted"]
    assert skills["plan-work"] == {
        "skill_id": "plan-work",
        "description": "Plan a piece of work with the user.",
        "invocation": "auto",
        "blocks": 5,
        "runs": 1,
        "error": None,
    }
    assert skills["child"]["runs"] == 0


def test_a_skill_that_fails_to_load_is_listed_with_its_error(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    broken = skills_overview(project)["skills"][0]

    assert broken["skill_id"] == "broken"
    assert broken["description"] is None
    assert broken["error"] is not None and "description" in broken["error"]


# --- the skill screen ---------------------------------------------------------------------------


def test_the_skill_screen_draws_every_block_and_edge_with_no_run_parts(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    detail = detail_of(project, "plan-work")

    canvas = detail["canvas"]
    template = canvas["template"]
    assert '  f0_approve_plan["@@f0_approve_plan@@"]\n' in template
    assert '  f0_approve_plan -->|"approve"| f0_done\n' in template
    assert '  f0_create_plan -.->|"visit cap"| f0_stopped\n' in template
    assert {node["block"]: node["type"] for node in canvas["nodes"]} == {
        "create_plan": "task",
        "ask_user": "decision",
        "approve_plan": "decision",
        "done": "end",
        "stopped": "end",
    }
    assert "current" not in canvas
    assert "timeline" not in detail
    assert detail["error"] is None
    assert detail["skill"]["goal"] == "Produce a plan that the user approved."


def test_a_block_shows_its_instruction_fields_and_exits(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    blocks = detail_of(project, "plan-work")["blocks"]

    create_plan = blocks["create_plan"]
    assert create_plan["instruction"] == "Write a plan for {{ inputs.topic }}."
    assert create_plan["instruction_file"] is None
    assert create_plan["fields"][0] == {
        "name": "status",
        "type": "string",
        "description": "finished when nothing is open.",
        "optional": False,
        "values": ["finished", "question"],
    }
    assert ["visits at most", "3"] in create_plan["facts"]
    assert [exit["to"] for exit in create_plan["exits"]] == ["ask_user", "approve_plan", "stopped"]
    approve_plan = blocks["approve_plan"]
    assert approve_plan["instruction_file"] == "instructions/approve_plan.md"
    assert approve_plan["instruction"] == "Show the plan:\n\n{{ steps.create_plan.plan }}\n"
    assert ["decider", "human"] in approve_plan["facts"]
    assert approve_plan["choices"] == [
        {"choice": "approve", "meaning": "Accept the plan."},
        {"choice": "stop", "meaning": "Stop without a plan."},
    ]
    assert approve_plan["exits"][0] == {
        "to": "done",
        "label": "approve",
        "hint": 'Taken when the decider picks "approve": Accept the plan.',
    }


def test_script_and_end_blocks_show_their_command_and_outputs(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    blocks = detail_of(project, "scripted")["blocks"]

    assert blocks["list_files"]["command"][0] == "python"
    assert ["parse", "json"] in blocks["list_files"]["facts"]
    assert ["status", "succeeded"] in blocks["done"]["facts"]
    assert blocks["done"]["outputs"] == [{"name": "count", "value": "{{ steps.list_files.json.files | length }}"}]


def test_a_call_block_leads_to_its_child_skill(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    call = detail_of(project, "parent")["blocks"]["child"]

    assert call["child_skill"] == "child"
    assert call["type"] == "call"


def test_a_choice_with_an_edge_list_shows_one_exit_per_condition(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    exits = detail_of(project, "per-item")["blocks"]["ask_finding"]["exits"]

    assert [exit["to"] for exit in exits] == ["ask_finding", "done", "done"]
    assert exits[0]["label"].startswith("fix: (history.ask_finding")


def test_the_skill_screen_reads_the_project_skill_not_a_run_copy(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    skill_file = project.skills_folder / "plan-work" / "skill.yaml"
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace("Write a plan for", "Draft a plan for"), encoding="utf-8"
    )

    blocks = detail_of(project, "plan-work")["blocks"]

    assert blocks["create_plan"]["instruction"] == "Draft a plan for {{ inputs.topic }}."


def test_a_skill_that_fails_to_load_shows_its_error_instead_of_a_graph(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    detail = detail_of(project, "broken")

    assert detail["canvas"] is None
    assert detail["blocks"] == {}
    assert any("description" in problem for problem in detail["error"])


def test_the_skill_screen_lists_the_validation_problems(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    uncapped = PLAN_SKILL.replace("    max_visits: 3\n    on_max_visits: stopped\n", "")
    write_skill(project.skills_folder, "plan-work", uncapped, PLAN_SKILL_FILES)

    problems = detail_of(project, "plan-work")["problems"]

    assert [problem["level"] for problem in problems] == ["warning"]
    assert "has no block with max_visits" in problems[0]["message"]


def test_an_unknown_skill_has_no_detail(tmp_path: Path) -> None:
    assert skill_detail(make_project(tmp_path), "missing") is None


def test_a_missing_instruction_file_is_named_instead_of_failing(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project.skills_folder / "plan-work" / "instructions" / "approve_plan.md").unlink()

    detail = detail_of(project, "plan-work")

    approve_plan = detail["blocks"]["approve_plan"]
    assert approve_plan["instruction"] is None
    assert approve_plan["instruction_file"] == "instructions/approve_plan.md"
    assert any("approve_plan.md" in problem["message"] for problem in detail["problems"])


def test_an_id_that_is_not_a_skill_id_has_no_detail(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_skill(tmp_path / "outside", "evil", PLAN_SKILL.replace("id: plan-work", "id: evil"), PLAN_SKILL_FILES)

    assert skill_detail(project, "../../outside/evil") is None
