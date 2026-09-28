"""Tests for pskill_runner.viewer_data: everything the viewer shows, built on the server side."""

from pathlib import Path

from pskill_runner.engine import start_run, submit_answer
from pskill_runner.project import Project, find_project
from pskill_runner.skill_loader import load_skill
from pskill_runner.viewer_data import run_detail, runs_overview, skill_mermaid
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill
from tests.test_engine_blocks import SCRIPT_SKILL


def make_project(tmp_path: Path) -> Project:
    write_skill(tmp_path / ".pskill" / "skills", "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)
    write_skill(tmp_path / ".pskill" / "skills", "scripted", SCRIPT_SKILL)
    return find_project(tmp_path)


def test_the_graph_has_a_node_per_block_and_labeled_edges(tmp_path: Path) -> None:
    skill = load_skill(make_project(tmp_path).skills_folder / "plan-work")

    graph = skill_mermaid(skill, visits={}, current_block=None, failed=False)

    assert graph.startswith("flowchart TD\n")
    assert '  start(("start")) --> create_plan\n' in graph
    assert '  create_plan["create_plan<br/>task"]\n' in graph
    assert '  create_plan -->|"steps.create_plan.status == #39;question#39;"| ask_user\n' in graph
    assert '  approve_plan -->|"approve"| done\n' in graph
    assert '  create_plan -.->|"visit cap"| stopped\n' in graph


def test_the_graph_marks_visits_and_the_current_block(tmp_path: Path) -> None:
    skill = load_skill(make_project(tmp_path).skills_folder / "plan-work")

    graph = skill_mermaid(skill, visits={"create_plan": 2, "ask_user": 1}, current_block="ask_user", failed=False)

    assert '  create_plan["create_plan<br/>task · 2 visits"]\n' in graph
    assert "  class create_plan visited\n" in graph
    assert "  class ask_user current\n" in graph
    assert "  class done visited" not in graph


def test_a_failed_current_block_is_marked_failed(tmp_path: Path) -> None:
    skill = load_skill(make_project(tmp_path).skills_folder / "plan-work")

    graph = skill_mermaid(skill, visits={"create_plan": 1}, current_block="create_plan", failed=True)

    assert "  class create_plan failed\n" in graph


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
    submit_answer(project, run_id, "status: question\nplan: Draft.\nquestion: Which database?\n")

    detail = run_detail(project, run_id)

    assert detail is not None
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
    [graph] = detail["graphs"]
    assert graph["skill_id"] == "plan-work"
    assert "class ask_user current" in graph["mermaid"]


def test_the_run_detail_shows_script_results(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")

    detail = run_detail(project, run_id)

    assert detail is not None
    script_row = detail["timeline"][0]
    assert script_row["block"] == "list_files"
    assert script_row["script_runs"][0]["exit_code"] == 0
    assert script_row["script_runs"][0]["argv"][0] == "python"


def test_the_run_detail_notes_a_skill_that_changed_after_the_run_started(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    write_skill(
        project.skills_folder, "plan-work", PLAN_SKILL.replace("Plan a piece", "Plan one piece"), PLAN_SKILL_FILES
    )

    detail = run_detail(project, run_id)

    assert detail is not None and detail["skill_changed"] is True


def test_an_unknown_run_has_no_detail(tmp_path: Path) -> None:
    assert run_detail(make_project(tmp_path), "r-00000000-0000-0000") is None
