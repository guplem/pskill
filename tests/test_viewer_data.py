"""Tests for pskill_runner.viewer_data: everything the viewer shows, built on the server side."""

from pathlib import Path
from typing import Any

from pskill_runner.engine import start_run, submit_answer
from pskill_runner.project import Project, find_project
from pskill_runner.viewer_data import run_detail, runs_overview
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill
from tests.test_engine_blocks import CHILD_SKILL, PARENT_SKILL, SCRIPT_SKILL

QUESTION = "status: question\nplan: Draft.\nquestion: Which database?\n"
FINISHED = "status: finished\nplan: Use Postgres.\n"
USER_ANSWER = "answer: Postgres.\n$answered_by: human\n"
APPROVE = "choice: approve\nrationale: Fine.\n$answered_by: human\n"


def make_project(tmp_path: Path) -> Project:
    write_skill(tmp_path / ".pskill" / "skills", "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)
    write_skill(tmp_path / ".pskill" / "skills", "scripted", SCRIPT_SKILL)
    write_skill(tmp_path / ".pskill" / "skills", "parent", PARENT_SKILL)
    write_skill(tmp_path / ".pskill" / "skills", "child", CHILD_SKILL)
    return find_project(tmp_path)


def run_to_the_end(project: Project) -> str:
    """plan-work: one question round, then an approved plan."""
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    for answer in (QUESTION, USER_ANSWER, FINISHED, APPROVE):
        submit_answer(project, run_id, answer)
    return run_id


def detail_of(project: Project, run_id: str) -> dict[str, Any]:
    detail = run_detail(project, run_id)
    assert detail is not None
    return detail


# --- the canvas ---------------------------------------------------------------------------------


def test_the_canvas_has_one_node_per_block_and_labeled_edges(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")

    canvas = detail_of(project, run_id)["canvas"]

    template = canvas["template"]
    assert template.startswith("flowchart TD\n")
    assert '  f0_create_plan["@@f0_create_plan@@"]\n' in template
    assert '  start(("start"))\n' in template
    assert "  start --> f0_create_plan\n" in template
    assert '  f0_create_plan -->|"steps.create_plan.status == #39;question#39;"| f0_ask_user\n' in template
    assert '  f0_approve_plan -->|"approve"| f0_done\n' in template
    assert '  f0_create_plan -.->|"visit cap"| f0_stopped\n' in template
    assert canvas["labels"]["f0_create_plan"] == "<b>create_plan</b><br/>task"
    assert {node["id"]: node["block"] for node in canvas["nodes"]}["f0_ask_user"] == "ask_user"
    edge_ids = [edge["id"] for edge in canvas["edges"]]
    assert "L_start_f0_create_plan_0" in edge_ids
    assert "L_f0_create_plan_f0_stopped_0" in edge_ids


def test_a_child_skill_is_a_subgraph_linked_from_its_call_block(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hello.\n")

    detail = detail_of(project, run_id)

    template = detail["canvas"]["template"]
    assert '  subgraph f1 ["child · called by child"]\n' in template
    assert '    f1_greet["@@f1_greet@@"]\n' in template
    assert "  f0_child -.-> f1_greet\n" in template
    child_row = detail["timeline"][-1]
    assert child_row["node"] == "f1_greet"
    assert child_row["edge"] == "L_f0_child_f1_greet_0"


def test_each_step_knows_its_node_and_the_edge_it_arrived_by(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = run_to_the_end(project)

    rows = detail_of(project, run_id)["timeline"]

    assert [row["node"] for row in rows] == [
        "f0_create_plan",
        "f0_ask_user",
        "f0_create_plan",
        "f0_approve_plan",
        "f0_done",
    ]
    assert [row["edge"] for row in rows] == [
        "L_start_f0_create_plan_0",
        "L_f0_create_plan_f0_ask_user_0",
        "L_f0_ask_user_f0_create_plan_0",
        "L_f0_create_plan_f0_approve_plan_0",
        "L_f0_approve_plan_f0_done_0",
    ]


def test_a_step_after_a_visit_cap_arrives_by_the_visit_cap_edge(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    for _ in range(3):
        submit_answer(project, run_id, QUESTION)
        submit_answer(project, run_id, USER_ANSWER)

    last_row = detail_of(project, run_id)["timeline"][-1]

    assert last_row["node"] == "f0_stopped"
    assert last_row["edge"] == "L_f0_create_plan_f0_stopped_0"


def test_each_step_has_the_label_of_its_node_after_the_step(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "status: maybe\n")
    for answer in (QUESTION, USER_ANSWER, FINISHED, APPROVE):
        submit_answer(project, run_id, answer)

    first_plan, _, second_plan, approve, _ = detail_of(project, run_id)["timeline"]

    assert first_plan["label"].startswith("<b>create_plan</b><br/>task · ")
    assert first_plan["label"].endswith("<br/>1 rejected")
    assert second_plan["label"].endswith("<br/>visit 2 · 1 rejected")
    assert "· approve" in approve["label"]


def test_human_steps_are_marked_and_each_step_knows_where_it_went_next(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = run_to_the_end(project)

    rows = detail_of(project, run_id)["timeline"]

    assert [row["asks_human"] for row in rows] == [False, True, False, True, False]
    assert rows[0]["left_by"] == {"to": "ask_user", "label": "steps.create_plan.status == #39;question#39;"}
    assert rows[3]["left_by"] == {"to": "done", "label": "approve"}
    assert rows[-1]["left_by"] is None


def test_the_canvas_names_the_current_step_and_its_state(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    open_run, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    submit_answer(project, open_run, QUESTION)
    finished_run = run_to_the_end(project)

    assert detail_of(project, open_run)["canvas"]["current"] == {"node": "f0_ask_user", "state": "waiting"}
    assert detail_of(project, finished_run)["canvas"]["current"] is None


# --- the runs overview and the run detail ------------------------------------------------------


def test_the_overview_lists_runs_and_one_summary_per_skill(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    open_run, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    finished_run, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")

    overview = runs_overview(project)

    assert {row["run_id"] for row in overview["runs"]} == {open_run, finished_run}
    finished_row = next(row for row in overview["runs"] if row["run_id"] == finished_run)
    assert finished_row["status"] == "succeeded"
    assert finished_row["duration_ms"] >= 0
    summaries = {summary["skill_id"]: summary for summary in overview["summaries"]}
    assert summaries["scripted"] == {
        "skill_id": "scripted",
        "runs": 1,
        "finished": 1,
        "succeeded": 1,
        "success_rate": 1.0,
        "median_duration_ms": finished_row["duration_ms"],
    }
    assert summaries["plan-work"]["success_rate"] is None


def test_the_run_detail_has_the_timeline_with_packets_submissions_and_outputs(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "plan-work", {"topic": "the login page"}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "status: maybe\n")
    submit_answer(project, run_id, QUESTION)

    detail = detail_of(project, run_id)

    first, second = detail["timeline"][:2]
    assert first["block"] == "create_plan"
    assert "Write a plan for the login page." in first["packet"]
    assert [submission["accepted"] for submission in first["submissions"]] == [False, True]
    assert first["submissions"][0]["errors"]
    assert first["output"]["question"] == "Which database?"
    assert first["decided_by"] == "agent"
    assert second["block"] == "ask_user"
    assert second["output"] is None
    assert detail["info"]["run_id"] == run_id
    assert detail["state"]["frames"][0]["current_block"] == "ask_user"
    assert detail["skill_changed"] is False


def test_the_run_detail_shows_script_results(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")

    detail = detail_of(project, run_id)

    script_row = detail["timeline"][0]
    assert script_row["block"] == "list_files"
    assert script_row["script_runs"][0]["exit_code"] == 0
    assert script_row["script_runs"][0]["argv"][0] == "python"
    assert script_row["label"].startswith("<b>list_files</b><br/>script · ")
    assert script_row["label"].endswith(" · exit 0")


def test_the_run_detail_notes_a_skill_that_changed_after_the_run_started(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    write_skill(
        project.skills_folder, "plan-work", PLAN_SKILL.replace("Plan a piece", "Plan one piece"), PLAN_SKILL_FILES
    )

    assert detail_of(project, run_id)["skill_changed"] is True


def test_an_unknown_run_has_no_detail(tmp_path: Path) -> None:
    assert run_detail(make_project(tmp_path), "r-00000000-0000-0000") is None
