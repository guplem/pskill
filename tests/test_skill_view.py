"""Tests for pskill_runner.skill_view: the skills list and the skill screen of the viewer."""

from pathlib import Path
from typing import Any

from pskill_runner.engine import start_run
from pskill_runner.project import Project, find_project
from pskill_runner.skill_view import skill_detail, skills_overview
from tests.skill_files import PER_ITEM_SKILL, PLAN_SKILL, PLAN_SKILL_FILES, write_skill
from tests.test_engine_blocks import (
    CHILD_SKILL,
    NAMED_PARALLEL_SKILL,
    PARENT_SKILL,
    PICKED_PARALLEL_SKILL,
    SCRIPT_SKILL,
)


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
        "default": None,
        "values": ["finished", "question"],
        "children": [],
    }
    assert ["visits at most", "3"] in create_plan["facts"]
    assert create_plan["type_meaning"] == "The agent does a piece of work and returns a typed answer."
    assert create_plan["notes"] == "It runs at most 3 times."
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
    assert detail["collapsed_canvas"] is None
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


def test_each_block_has_its_editable_keys_and_their_values_as_written(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    blocks = detail_of(project, "plan-work")["blocks"]

    create_plan = blocks["create_plan"]["editable"]
    assert create_plan["keys"] == ["description", "max_visits", "on_max_visits", "instruction", "next", "retries"]
    assert create_plan["values"]["max_visits"] == 3
    assert create_plan["values"]["next"] == [
        {"when": "{{ steps.create_plan.status == 'question' }}", "to": "ask_user"},
        {"to": "approve_plan"},
    ]
    assert blocks["approve_plan"]["editable"]["values"]["next"] == {"approve": "done", "stop": "stopped"}
    assert "description" not in create_plan["values"]


def test_a_parallel_block_shows_its_task_name(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "fanout", NAMED_PARALLEL_SKILL)
    detail = skill_detail(find_project(tmp_path), "fanout") or {}

    check = detail["blocks"]["check"]

    assert ["task name", "Check {{ item }}"] in check["facts"]
    assert "task_name" in check["editable"]["keys"]


def test_a_fixed_for_each_list_shows_one_card_per_item(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "picked", PICKED_PARALLEL_SKILL)
    detail = skill_detail(find_project(tmp_path), "picked") or {}

    review = detail["blocks"]["review"]

    assert ["for each", "a fixed list of 3 items, 2 with a when"] in review["facts"]
    assert review["for_each_items"][0] == {"fields": [["name", "always"]], "when": None}
    assert review["for_each_items"][1] == {
        "fields": [["name", "api"]],
        "when": "{{ inputs.paths | select('matches', '^api/') | list }}",
    }


def test_a_computed_for_each_shows_its_expression_and_no_cards(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "fanout", NAMED_PARALLEL_SKILL)
    detail = skill_detail(find_project(tmp_path), "fanout") or {}

    check = detail["blocks"]["check"]

    assert ["for each", "{{ inputs.files }}"] in check["facts"]
    assert check["for_each_items"] == []


GRAND_SKILL = """\
schema: pskill/v1
id: grand
description: Calls the parent.
goal: Run the parent.
entry: run_parent
blocks:
  run_parent:
    type: call
    skill: parent
    next: done
  done:
    type: end
    status: succeeded
"""


def test_a_call_block_is_drawn_as_the_frame_of_its_child_skill(tmp_path: Path) -> None:
    canvas = detail_of(make_project(tmp_path), "parent")["canvas"]
    template = canvas["template"]

    assert '  subgraph f1 ["@@f1@@"]\n    f1_greet["@@f1_greet@@"]\n    f1_done["@@f1_done@@"]\n  end\n' in template
    assert "f0_child[" not in template
    assert "  f0_greet --> f1\n" in template
    assert all(edge["kind"] != "call" for edge in canvas["edges"])
    leaving = [edge for edge in canvas["edges"] if edge["source"] == "f0_child"]
    assert [edge["id"] for edge in leaving] == ["L_f1_f0_done_0", "L_f1_f0_failed_0"]
    assert canvas["frames"] == [{"id": "f1", "node": "f0_child", "token": "@@f1@@"}]
    assert canvas["labels"]["f1"] == "<b>child</b><br/>call: child"
    # The main line goes through the frame, and on inside it.
    assert canvas["main_edges"] == ["L_start_f0_greet_0", "L_f0_greet_f1_0", "L_f1_f0_done_0", "L_f1_greet_f1_done_0"]


def test_the_collapsed_canvas_draws_a_call_block_as_one_node(tmp_path: Path) -> None:
    canvas = detail_of(make_project(tmp_path), "parent")["collapsed_canvas"]
    template = canvas["template"]

    assert '  f0_child["@@f0_child@@"]\n' in template
    assert canvas["labels"]["f0_child"].endswith("<b>child</b><br/>call: child")  # the node names its child skill
    assert "subgraph" not in template
    assert "  f0_greet --> f0_child\n" in template
    assert canvas["frames"] == []
    assert {node["id"] for node in canvas["nodes"]} == {"f0_greet", "f0_child", "f0_done", "f0_failed"}
    assert canvas["main_edges"] == ["L_start_f0_greet_0", "L_f0_greet_f0_child_0", "L_f0_child_f0_done_0"]


def test_a_child_that_calls_a_skill_holds_that_frame_inside_its_own(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_skill(project.skills_folder, "grand", GRAND_SKILL)

    canvas = detail_of(project, "grand")["canvas"]

    nested = '    subgraph f2 ["@@f2@@"]\n      f2_greet["@@f2_greet@@"]\n      f2_done["@@f2_done@@"]\n    end\n'
    assert '  subgraph f1 ["@@f1@@"]\n    f1_greet["@@f1_greet@@"]\n' + nested in canvas["template"]
    assert canvas["frames"][1] == {"id": "f2", "node": "f1_child", "token": "@@f2@@"}
    assert canvas["labels"]["f1"] == "<b>run_parent</b><br/>call: parent"


def test_a_block_of_a_child_skill_has_its_own_details_by_node(tmp_path: Path) -> None:
    detail = detail_of(make_project(tmp_path), "parent")

    greet = detail["child_blocks"]["f1_greet"]

    assert (greet["skill_id"], greet["called_by"], greet["node"]) == ("child", "child", "f1_greet")
    assert "Greet {{ inputs.name }}" in greet["instruction"]
    assert [exit_["to"] for exit_ in greet["exits"]] == ["done"]
    assert detail["blocks"]["greet"]["node"] == "f0_greet"


def test_a_call_to_a_skill_that_does_not_load_draws_no_frame(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project.skills_folder / "child" / "skill.yaml").write_text("schema: pskill/v1\nid: child\n", encoding="utf-8")

    detail = detail_of(project, "parent")

    assert "subgraph f1" not in detail["canvas"]["template"]
    assert detail["child_blocks"] == {}


DETAILED_SKILL = """\
schema: pskill/v1
id: detailed
description: Shows every detail of a block.
goal: Check the panel details.
invocation: manual
entry: read
blocks:
  read:
    type: script
    run: [uv, run, "{{ skill.dir }}/scripts/read.py", "{{ skill.dir }}/../outside.py"]
    parse: json
    next:
      - when: "{{ steps.read.json.count > 0 }}"
        to: plan
      - to: done
  plan:
    type: task
    instruction: Plan it.
    output:
      mode: {type: string, enum: [fast, slow], default: fast, description: "How to plan."}
      gaps:
        type: array
        description: "The open questions."
        items:
          type: object
          properties:
            name: {type: string, description: "2 to 4 words."}
            question: {type: string, optional: true, description: "The question."}
    next: done
  done:
    type: end
    status: succeeded
"""


def test_a_script_block_shows_the_skill_file_that_its_command_runs(tmp_path: Path) -> None:
    files = {"scripts/read.py": "LABELS = ['blocked']\n"}
    write_skill(tmp_path / ".pskill" / "skills", "detailed", DETAILED_SKILL, files)
    (tmp_path / ".pskill" / "skills" / "outside.py").write_text("SECRET = 1\n", encoding="utf-8")

    read = detail_of(find_project(tmp_path), "detailed")["blocks"]["read"]

    assert read["script_files"] == [{"path": "scripts/read.py", "text": "LABELS = ['blocked']\n"}]


def test_an_output_field_shows_its_default_and_its_nested_fields(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "detailed", DETAILED_SKILL)

    mode, gaps = detail_of(find_project(tmp_path), "detailed")["blocks"]["plan"]["fields"]

    assert mode["default"] == "fast"
    assert mode["children"] == []
    assert [child["name"] for child in gaps["children"]] == ["name", "question"]
    assert gaps["children"][1]["optional"] is True
    assert gaps["children"][1]["description"] == "The question."


def test_each_canvas_edge_has_its_target_condition_and_fallback(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "detailed", DETAILED_SKILL)

    edges = detail_of(find_project(tmp_path), "detailed")["canvas"]["edges"]
    read_edges = [edge for edge in edges if edge["source"] == "f0_read"]

    assert [edge["to_block"] for edge in read_edges] == ["plan", "done"]
    assert read_edges[0]["when"] == "steps.read.json.count > 0"
    assert [edge["fallback"] for edge in read_edges] == [False, True]
    assert read_edges[0]["choice"] is None


def test_a_parallel_block_names_the_agent_files_that_it_uses(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "fanout", NAMED_PARALLEL_SKILL)
    (tmp_path / ".pskill" / "agents").mkdir()
    (tmp_path / ".pskill" / "agents" / "checker.md").write_text("You check facts.\n", encoding="utf-8")
    detail = skill_detail(find_project(tmp_path), "fanout") or {}

    assert detail["blocks"]["check"]["agents"] == ["checker"]
    assert detail["blocks"]["done"]["agents"] == []


def test_a_missing_agent_file_is_not_named_as_a_link(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "fanout", NAMED_PARALLEL_SKILL)
    detail = skill_detail(find_project(tmp_path), "fanout") or {}

    assert detail["blocks"]["check"]["agents"] == []


def test_a_project_without_a_skills_folder_has_no_skills(tmp_path: Path) -> None:
    (tmp_path / ".pskill").mkdir()

    assert skills_overview(find_project(tmp_path)) == {"skills": []}


LIMITS_SKILL = """\
schema: pskill/v1
id: limits
description: A script with limits, then a fixed list of plain items.
goal: Show every limit of a block.
entry: list_files
blocks:
  list_files:
    type: script
    run: [git, status]
    timeout_s: 30
    retries: 2
    next: check
  check:
    type: parallel
    for_each: [a.md, b.md]
    instruction: "Check {{ item }}."
    output:
      ok: {type: boolean, description: "True when the file is fine."}
    next: done
  done:
    type: end
    status: succeeded
"""


def test_a_script_block_shows_its_timeout_and_its_retries(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "limits", LIMITS_SKILL)

    list_files = detail_of(find_project(tmp_path), "limits")["blocks"]["list_files"]

    assert list_files["facts"] == [["parse", "text"], ["timeout", "30 s"], ["retries", "2"]]


def test_a_fixed_list_of_plain_items_shows_one_card_per_item(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "limits", LIMITS_SKILL)

    check = detail_of(find_project(tmp_path), "limits")["blocks"]["check"]

    assert check["facts"] == [["for each", "a fixed list of 2 items"]]
    assert check["for_each_items"] == [
        {"fields": [["item", "a.md"]], "when": None},
        {"fields": [["item", "b.md"]], "when": None},
    ]
