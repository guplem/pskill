"""Tests for pskill_runner.viewer_data: everything the viewer shows, built on the server side."""

import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from pskill_runner.engine import start_run, submit_answer
from pskill_runner.project import Project, find_project
from pskill_runner.skill_model import ScriptBlock
from pskill_runner.viewer_data import (
    node_hint,
    run_detail,
    runs_overview,
    split_choice_reason,
    task_row_sizes,
    timeline_rows,
)
from tests.skill_files import PER_ITEM_SKILL, PLAN_SKILL, PLAN_SKILL_FILES, write_skill
from tests.test_engine_blocks import (
    CHILD_SKILL,
    PARALLEL_SKILL,
    PARENT_SKILL,
    SCRIPT_SKILL,
    adapter_with_subagents,  # noqa: F401 (an autouse fixture: the harness "subagents-for-tests")
)

QUESTION = "status: question\nplan: Draft.\nquestion: Which database?\n"
FINISHED = "status: finished\nplan: Use Postgres.\n"
USER_ANSWER = "answer: Postgres.\n$answered_by: human\n"
APPROVE = "choice: approve\nrationale: Fine.\n$answered_by: human\n"

TWO_ROADS_SKILL = """\
schema: pskill/v1
id: two-roads
description: Two choices lead to one block.
goal: Pick a road.
entry: pick
blocks:
  pick:
    type: decision
    decider: agent
    instruction: "Pick a road."
    choices:
      left: Go left.
      right: Go right.
      back: Go back.
    next: {left: done, right: done, back: done}
  done:
    type: end
    status: succeeded
"""

LOOP_PARENT_SKILL = """\
schema: pskill/v1
id: loop-parent
description: Calls a child twice.
goal: Get two greetings.
entry: child
blocks:
  child:
    type: call
    skill: child
    inputs: {name: Ada}
    next:
      - when: "{{ (history.child | length) < 2 }}"
        to: child
      - to: done
  done:
    type: end
    status: succeeded
"""

FAILING_SKILL = """\
schema: pskill/v1
id: failing
description: Runs a script that fails.
goal: Fail.
entry: break_it
blocks:
  break_it:
    type: script
    run: [python, -c, "import sys; sys.exit(1)"]
    next: done
  done:
    type: end
    status: succeeded
"""


LONG_CONDITION_SKILL = """\
schema: pskill/v1
id: long-condition
description: Has a condition too long for its edge label.
goal: Check the hints.
entry: work
blocks:
  work:
    type: task
    description: Does the one piece of work.
    instruction: "Work."
    output:
      status: {type: string, description: "How it went."}
    next:
      - when: "{{ steps.work.status == 'a very long status name that does not fit on the edge label' }}"
        to: done
      - to: done
  done:
    type: end
    status: succeeded
"""


FANOUT_TWICE_SKILL = """\
schema: pskill/v1
id: fanout-twice
description: Checks the documents, then the first two again.
goal: Check twice.
inputs:
  files: {type: array, items: {type: string}, description: "The documents."}
entry: check
blocks:
  check:
    type: parallel
    for_each: "{{ inputs.files if (history.check | default([]) | length) == 0 else inputs.files[:2] }}"
    instruction: "Check {{ item }}."
    output:
      wrong: {type: array, items: {type: string}, description: "The wrong claims."}
    next:
      - when: "{{ (history.check | length) < 2 }}"
        to: check
      - to: done
  done:
    type: end
    status: succeeded
"""

FANOUT_CALLER_SKILL = """\
schema: pskill/v1
id: fanout-caller
description: Calls the fanout skill twice, with other documents.
goal: Check two sets of documents.
entry: fan
blocks:
  fan:
    type: call
    skill: fanout
    inputs:
      files: "{{ ['a.md', 'b.md', 'c.md'] if (history.fan | default([]) | length) == 0 else ['x.md'] }}"
    next:
      - when: "{{ (history.fan | length) < 2 }}"
        to: fan
      - to: done
  done:
    type: end
    status: succeeded
"""


HEADING_TASK_SKILL = """\
schema: pskill/v1
id: heading-task
description: A parallel block whose instruction has a task heading of its own.
goal: Check the documents.
inputs:
  files: {type: array, items: {type: string}, description: "The documents."}
entry: check
blocks:
  check:
    type: parallel
    for_each: "{{ inputs.files }}"
    instruction: |
      Check {{ item }}.

      #### Task 1
      #### Task 5
      This heading is part of the instruction, not a task.
    output:
      wrong: {type: array, items: {type: string}, description: "The wrong claims."}
    next: check_tasks
  check_tasks:
    type: end
    status: succeeded
"""


def make_project(tmp_path: Path) -> Project:
    write_skill(tmp_path / ".pskill" / "skills", "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)
    write_skill(tmp_path / ".pskill" / "skills", "scripted", SCRIPT_SKILL)
    write_skill(tmp_path / ".pskill" / "skills", "parent", PARENT_SKILL)
    write_skill(tmp_path / ".pskill" / "skills", "child", CHILD_SKILL)
    write_skill(tmp_path / ".pskill" / "skills", "two-roads", TWO_ROADS_SKILL)
    write_skill(tmp_path / ".pskill" / "skills", "failing", FAILING_SKILL)
    write_skill(tmp_path / ".pskill" / "skills", "loop-parent", LOOP_PARENT_SKILL)
    write_skill(tmp_path / ".pskill" / "skills", "fanout", PARALLEL_SKILL)
    write_skill(tmp_path / ".pskill" / "skills", "long-condition", LONG_CONDITION_SKILL)
    write_skill(tmp_path / ".pskill" / "skills", "fanout-twice", FANOUT_TWICE_SKILL)
    write_skill(tmp_path / ".pskill" / "skills", "fanout-caller", FANOUT_CALLER_SKILL)
    write_skill(tmp_path / ".pskill" / "skills", "heading-task", HEADING_TASK_SKILL)
    (tmp_path / ".pskill" / "agents").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".pskill" / "agents" / "checker.md").write_text("You check facts.", encoding="utf-8")
    return find_project(tmp_path)


def run_parent_to_the_end(project: Project) -> str:
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hello.\n")
    submit_answer(project, run_id, "text: Hi Ada.\n")
    return run_id


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
    assert (
        canvas["labels"]["f0_create_plan"] == "<span class='block-icon'>\u00a0</span><br/><b>create_plan</b><br/>task"
    )
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


def test_each_node_has_a_hint_that_explains_its_block(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    plan_run, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    long_run, _ = start_run(project, "long-condition", {}, mode="interactive", harness="generic")

    plan_hints = {node["block"]: node["hint"] for node in detail_of(project, plan_run)["canvas"]["nodes"]}
    long_hints = {node["block"]: node["hint"] for node in detail_of(project, long_run)["canvas"]["nodes"]}

    assert plan_hints["create_plan"] == (
        "The agent does a piece of work and returns a typed answer.\nIt runs at most 3 times."
    )
    assert plan_hints["ask_user"] == (
        "One choice is picked from a list, or a question gets an answer.\n"
        "The user decides in an interactive run. The agent decides in an autonomous run."
    )
    assert plan_hints["done"] == "The skill finishes here with a status and outputs.\nStatus: succeeded."
    assert long_hints["work"].startswith("Does the one piece of work.\nThe agent does ")


def test_each_edge_has_a_hint_with_its_whole_condition(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    plan_run, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    long_run, _ = start_run(project, "long-condition", {}, mode="interactive", harness="generic")
    parent_run = run_parent_to_the_end(project)

    def hints(run_id: str) -> dict[str, str]:
        return {edge["id"]: edge["hint"] for edge in detail_of(project, run_id)["canvas"]["edges"]}

    plan = hints(plan_run)
    assert plan["L_start_f0_create_plan_0"] == "The run starts here."
    assert plan["L_f0_create_plan_f0_ask_user_0"] == "Taken when steps.create_plan.status == 'question'."
    assert plan["L_f0_create_plan_f0_approve_plan_0"] == "Taken when no condition above matches."
    assert plan["L_f0_ask_user_f0_create_plan_0"] == "Always taken."
    assert plan["L_f0_approve_plan_f0_done_0"] == 'Taken when the decider picks "approve": Accept the plan.'
    assert plan["L_f0_create_plan_f0_stopped_0"] == (
        "Taken instead when the run tries to enter create_plan after its 3 visits (the visit cap)."
    )
    long_condition = "steps.work.status == 'a very long status name that does not fit on the edge label'"
    assert hints(long_run)["L_f0_work_f0_done_0"] == f"Taken when {long_condition}."
    assert hints(parent_run)["L_f0_child_f1_greet_0"] == "The call block child runs the skill child, which starts here."


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

    rows = detail_of(project, run_id)["timeline"]

    assert rows[-1]["node"] == "f0_stopped"
    assert rows[-1]["edge"] == "L_f0_create_plan_f0_stopped_0"
    assert rows[-2]["left_by"] == {"to": "stopped", "label": "visit cap of create_plan"}
    assert rows[-1]["arrival"] == "create_plan (visit cap of create_plan (3))"


def test_each_step_has_the_label_of_its_node_after_the_step(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "status: maybe\n")
    for answer in (QUESTION, USER_ANSWER, FINISHED, APPROVE):
        submit_answer(project, run_id, answer)

    first_plan, _, second_plan, approve, _ = detail_of(project, run_id)["timeline"]

    assert first_plan["label"].startswith("<span class='block-icon'>\u00a0</span><br/><b>create_plan</b><br/>task · ")
    assert first_plan["label"].endswith("<br/>1 rejected")
    assert second_plan["label"].endswith("<br/>visit 2 · 1 rejected")
    assert "· approve" in approve["label"]


def test_human_steps_are_marked_and_each_step_knows_where_it_went_next(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = run_to_the_end(project)

    rows = detail_of(project, run_id)["timeline"]

    assert [row["asks_human"] for row in rows] == [False, True, False, True, False]
    assert rows[0]["left_by"] == {"to": "ask_user", "label": "steps.create_plan.status == 'question'"}
    assert rows[3]["left_by"] == {"to": "done", "label": "approve"}
    assert rows[-1]["left_by"] is None


def test_the_canvas_names_the_current_step_and_its_state(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    open_run, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    submit_answer(project, open_run, QUESTION)
    finished_run = run_to_the_end(project)

    assert detail_of(project, open_run)["canvas"]["current"] == {"node": "f0_ask_user", "state": "waiting"}
    assert detail_of(project, finished_run)["canvas"]["current"] is None


def test_repeated_edges_between_two_nodes_are_numbered_like_mermaid(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "two-roads", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "choice: right\nrationale: Shorter.\n")

    detail = detail_of(project, run_id)

    edge_ids = [edge["id"] for edge in detail["canvas"]["edges"]]
    assert "L_f0_pick_f0_done_0" in edge_ids
    assert "L_f0_pick_f0_done_2" in edge_ids
    assert "L_f0_pick_f0_done_3" in edge_ids
    assert detail["timeline"][-1]["edge"] == "L_f0_pick_f0_done_2"
    assert detail["timeline"][-1]["arrival"] == "pick (choice right)"


def test_a_call_block_leaves_by_the_edge_after_its_child_returned(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = run_parent_to_the_end(project)

    rows = detail_of(project, run_id)["timeline"]

    assert [row["node"] for row in rows] == ["f0_greet", "f0_child", "f1_greet", "f1_done", "f0_done"]
    call_row = rows[1]
    assert call_row["left_by"] == {"to": "done", "label": "steps.child.status == 'succeeded'"}
    assert call_row["label"].endswith(" · succeeded")
    assert rows[-1]["edge"] == "L_f0_child_f0_done_0"
    assert rows[2]["arrival"] == "child (call)"


def test_a_child_end_block_leaves_by_nothing_when_its_call_block_runs_again(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "loop-parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hi.\n")
    submit_answer(project, run_id, "text: Hi again.\n")

    rows = detail_of(project, run_id)["timeline"]

    assert [row["node"] for row in rows] == [
        "f0_child",
        "f1_greet",
        "f1_done",
        "f0_child",
        "f1_greet",
        "f1_done",
        "f0_done",
    ]
    assert rows[2]["left_by"] is None


def test_a_child_without_its_skill_copy_gets_no_node(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "text: Hello.\n")
    shutil.rmtree(project.runs_folder / run_id / "skills" / "child")

    detail = detail_of(project, run_id)

    child_row = detail["timeline"][-1]
    assert child_row["node"] is None
    assert child_row["edge"] is None
    assert child_row["arrival"] == "parent (call)"
    assert "f1_greet" not in detail["canvas"]["template"]
    assert detail["canvas"]["current"] is None


def test_rows_get_their_texts_even_without_a_canvas(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    submit_answer(project, run_id, QUESTION)
    shutil.rmtree(project.runs_folder / run_id / "skills" / "plan-work")

    detail = detail_of(project, run_id)

    assert detail["canvas"] is None
    first, second = detail["timeline"]
    assert first["node"] is None
    assert first["arrival"] == "the start"
    assert first["summary"].startswith("task · ")
    assert second["arrival"] == "create_plan (steps.create_plan.status == 'question')"


def test_an_autonomous_run_never_waits_for_the_user(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="autonomous", harness="generic")
    submit_answer(project, run_id, QUESTION)

    detail = detail_of(project, run_id)

    assert detail["timeline"][-1]["asks_human"] is False
    assert detail["canvas"]["current"] == {"node": "f0_ask_user", "state": "now"}


def test_the_current_step_is_now_for_the_agent_and_failed_after_a_failed_script(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    agent_run, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")
    failed_run, _ = start_run(project, "failing", {}, mode="interactive", harness="generic")
    child_run, _ = start_run(project, "parent", {}, mode="interactive", harness="generic")
    submit_answer(project, child_run, "text: Hello.\n")

    assert detail_of(project, agent_run)["canvas"]["current"] == {"node": "f0_create_plan", "state": "now"}
    assert detail_of(project, failed_run)["canvas"]["current"] == {"node": "f0_break_it", "state": "failed"}
    assert detail_of(project, child_run)["canvas"]["current"] == {"node": "f1_greet", "state": "now"}


def test_a_one_by_one_parallel_block_keeps_its_final_output(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "wrong: []\n", task=0)
    submit_answer(project, run_id, "wrong: [x]\n", task=1)

    check_rows = [row for row in detail_of(project, run_id)["timeline"] if row["block"] == "check"]

    assert [row["task"] for row in check_rows] == [0, 1]
    assert check_rows[-1]["output"] == {"results": [{"wrong": []}, {"wrong": ["x"]}]}
    assert check_rows[-1]["label"].endswith(" · 2 tasks")
    assert [len(row["submissions"]) for row in check_rows] == [1, 1]
    assert check_rows[0]["left_by"] == {"to": "done", "label": None}


def parallel_events(visit: int, tasks: int, first_seq: int) -> list[dict[str, Any]]:
    """The events of one one-by-one parallel visit: one start and one answer per task, then the final result."""
    base = {"frame": "fanout", "block": "check", "block_type": "parallel", "visit": visit, "ts": "2026-01-01T00:00:00Z"}
    events: list[dict[str, Any]] = []
    for task in range(tasks):
        events.append({**base, "type": "block_started", "seq": first_seq + 2 * task, "task": task})
        events.append(
            {
                **base,
                "type": "block_completed",
                "seq": first_seq + 2 * task + 1,
                "task": task,
                "output": {"wrong": []},
                "decided_by": "agent",
                "duration_ms": 1,
            }
        )
    final: dict[str, Any] = {"results": [{"wrong": []}] * tasks}
    events.append(
        {
            **base,
            "type": "block_completed",
            "seq": first_seq + 2 * tasks,
            "output": final,
            "decided_by": "runner",
            "duration_ms": 2,
        }
    )
    return events


def test_the_final_result_of_a_repeated_parallel_block_lands_on_its_own_visit() -> None:
    rows = timeline_rows(
        parallel_events(visit=1, tasks=3, first_seq=1) + parallel_events(visit=2, tasks=2, first_seq=10)
    )

    assert [row["output"] for row in rows[:3]] == [{"wrong": []}, {"wrong": []}, {"results": [{"wrong": []}] * 3}]
    assert rows[-1]["output"] == {"results": [{"wrong": []}] * 2}


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
    assert script_row["label"].startswith("<span class='block-icon'>\u00a0</span><br/><b>list_files</b><br/>script · ")
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


# --- the tasks of a parallel block, script results, and input and output titles ---------------------


def check_row_of(project: Project, run_id: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = [row for row in detail_of(project, run_id)["timeline"] if row["block"] == "check"]
    (row,) = rows
    return row


def test_a_parallel_row_with_subagents_keeps_each_task_answer_and_output(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )
    submit_answer(project, run_id, "wrong: 3\n", task=1)
    submit_answer(project, run_id, "wrong: [x]\n", task=1)
    submit_answer(project, run_id, "wrong: []\n", task=0)

    row = check_row_of(project, run_id)

    assert [submission["task"] for submission in row["submissions"]] == [1, 1, 0]
    tasks = row["tasks"]
    assert [(task["task"], task["state"], task["output"]) for task in tasks] == [
        (0, "done", {"wrong": []}),
        (1, "done", {"wrong": ["x"]}),
    ]
    assert [len(task["submissions"]) for task in tasks] == [1, 2]
    assert [task["label"] for task in tasks] == ["task 0", "task 1 · 1 rejected"]
    assert tasks[0]["packet"].startswith("You are a subagent of a pskill run.")
    assert "Check every claim in a.md." in tasks[0]["packet"]
    assert "Check every claim in b.md." in tasks[1]["packet"]
    assert row["output"] == {"results": [{"wrong": []}, {"wrong": ["x"]}]}


def test_a_one_by_one_parallel_block_lists_the_tasks_of_its_visit(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "wrong: []\n", task=0)
    submit_answer(project, run_id, "wrong: [x]\n", task=1)

    first, second = [row for row in detail_of(project, run_id)["timeline"] if row["block"] == "check"]

    assert [(task["task"], task["state"]) for task in first["tasks"]] == [(0, "done"), (1, "open")]
    assert [(task["task"], task["state"]) for task in second["tasks"]] == [(0, "done"), (1, "done")]
    assert second["tasks"][1]["output"] == {"wrong": ["x"]}
    assert "Check every claim in b.md." in second["tasks"][1]["packet"]


def test_each_task_is_done_rejected_or_open(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(
        project, "fanout", {"files": ["a.md", "b.md", "c.md"]}, mode="interactive", harness="subagents-for-tests"
    )
    submit_answer(project, run_id, "wrong: 3\n", task=0)
    submit_answer(project, run_id, "wrong: []\n", task=1)

    row = check_row_of(project, run_id)

    assert [task["state"] for task in row["tasks"]] == ["rejected", "done", "open"]
    assert row["output"] is None
    assert [len(task["submissions"]) for task in row["tasks"]] == [1, 1, 0]


def test_the_canvas_draws_a_frame_of_task_nodes_next_to_a_parallel_block(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(
        project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )
    submit_answer(project, run_id, "wrong: []\n", task=0)

    detail = detail_of(project, run_id)

    template = detail["canvas"]["template"]
    assert '  subgraph f0_check_TASKS ["check · 2 tasks"]\n    direction LR\n' in template
    assert '    f0_check_T0["@@f0_check_T0@@"]\n' in template
    assert '    f0_check_T1["@@f0_check_T1@@"]\n' in template
    assert "  f0_check -.- f0_check_TASKS\n" in template
    assert "    f0_check_T0 ~~~ f0_check_T1\n" in template  # invisible links put the tasks in rows
    nodes = {node["id"]: node for node in detail["canvas"]["nodes"]}
    assert nodes["f0_check_T1"]["kind"] == "task"
    assert nodes["f0_check_T1"]["parent"] == "f0_check"
    assert nodes["f0_check_T1"]["task"] == 1
    assert nodes["f0_check"]["kind"] == "block"
    edges = {edge["id"]: edge for edge in detail["canvas"]["edges"]}
    assert edges["L_f0_check_f0_check_TASKS_0"]["kind"] == "tasks"
    row = check_row_of(project, run_id)
    assert [task["node"] for task in row["tasks"]] == ["f0_check_T0", "f0_check_T1"]


def test_the_task_rows_are_balanced_so_that_no_task_stands_alone() -> None:
    assert task_row_sizes(1) == [1]
    assert task_row_sizes(4) == [4]
    assert task_row_sizes(5) == [3, 2]
    assert task_row_sizes(9) == [3, 3, 3]
    assert task_row_sizes(13) == [4, 3, 3, 3]


def test_a_script_run_keeps_its_stdout_parsed_as_json(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    json_run, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")
    failed_run, _ = start_run(project, "failing", {}, mode="interactive", harness="generic")

    json_script = detail_of(project, json_run)["timeline"][0]["script_runs"][0]
    failed_script = detail_of(project, failed_run)["timeline"][0]["script_runs"][0]

    assert json_script["parsed"] == {"files": ["a.md", "b.md"]}
    assert failed_script["parsed"] is None


def test_each_row_names_its_input_and_output(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    plan_run = run_to_the_end(project)
    script_run, _ = start_run(project, "scripted", {}, mode="interactive", harness="generic")

    plan_rows = detail_of(project, plan_run)["timeline"]
    script_row = detail_of(project, script_run)["timeline"][0]

    titles = {row["block"]: (row["input_title"], row["output_title"]) for row in plan_rows}
    assert titles["create_plan"] == ("Input: the instruction the agent got", "Output: the agent's answer")
    assert titles["ask_user"] == ("Input: the question to decide", "Output: the decision")
    assert titles["done"] == ("Input: the report the agent got", "Output: the skill's outputs")
    assert (script_row["input_title"], script_row["output_title"]) == (
        "Input: the command the runner ran",
        "Output: the command's result",
    )


def test_a_parallel_block_in_a_child_skill_keeps_the_tasks_of_each_call(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "fanout-caller", {}, mode="interactive", harness="subagents-for-tests")
    for task in range(3):
        submit_answer(project, run_id, "wrong: []\n", task=task)
    submit_answer(project, run_id, "wrong: [second]\n", task=0)

    detail = detail_of(project, run_id)

    first, second = [row for row in detail["timeline"] if row["block"] == "check"]
    assert [task["state"] for task in first["tasks"]] == ["done", "done", "done"]
    assert [(task["task"], task["output"]) for task in second["tasks"]] == [(0, {"wrong": ["second"]})]
    assert second["tasks"][0]["node"] == "f1_check_T0"
    template = detail["canvas"]["template"]
    frame = template[template.index("  subgraph f1 ") : template.index("  end\n", template.index("  subgraph f1 "))]
    assert '    subgraph f1_check_TASKS ["check · 3 tasks"]\n' in frame


def test_a_parallel_block_that_runs_twice_keeps_the_tasks_of_each_visit(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(
        project, "fanout-twice", {"files": ["a.md", "b.md", "c.md"]}, mode="interactive", harness="subagents-for-tests"
    )
    for task in range(3):
        submit_answer(project, run_id, "wrong: []\n", task=task)
    submit_answer(project, run_id, "wrong: [again]\n", task=0)

    detail = detail_of(project, run_id)

    first, second = [row for row in detail["timeline"] if row["block"] == "check"]
    assert [task["output"] for task in first["tasks"]] == [{"wrong": []}, {"wrong": []}, {"wrong": []}]
    assert [(task["task"], task["output"]) for task in second["tasks"]] == [(0, {"wrong": ["again"]}), (1, None)]
    assert '  subgraph f0_check_TASKS ["check · 3 tasks"]\n' in detail["canvas"]["template"]


def test_a_live_one_by_one_block_counts_its_tasks_from_the_run_state(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "fanout", {"files": ["a.md", "b.md", "c.md"]}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "wrong: []\n", task=0)

    rows = [row for row in detail_of(project, run_id)["timeline"] if row["block"] == "check"]

    assert [task["state"] for task in rows[-1]["tasks"]] == ["done", "open", "open"]


def test_a_rejected_answer_one_by_one_stays_with_its_task(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "fanout", {"files": ["a.md", "b.md"]}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "wrong: 3\n", task=0)
    submit_answer(project, run_id, "wrong: []\n", task=0)
    submit_answer(project, run_id, "wrong: []\n", task=1)

    first, second = [row for row in detail_of(project, run_id)["timeline"] if row["block"] == "check"]

    assert first["tasks"][0]["label"] == "task 0 · 1 rejected"
    assert [len(task["submissions"]) for task in second["tasks"]] == [2, 1]


def test_an_answer_for_a_task_that_does_not_exist_adds_no_task(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(
        project, "fanout", {"files": ["a.md", "b.md", "c.md"]}, mode="interactive", harness="subagents-for-tests"
    )
    submit_answer(project, run_id, "wrong: 3\n", task=7)

    detail = detail_of(project, run_id)

    row = check_row_of(project, run_id)
    assert len(row["tasks"]) == 3
    assert [submission["task"] for submission in row["submissions"]] == [7]
    assert "f0_check_T7" not in detail["canvas"]["template"]


def test_a_task_frame_with_many_tasks_has_several_rows(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    files = [f"{name}.md" for name in "abcde"]
    run_id, _ = start_run(project, "fanout", {"files": files}, mode="interactive", harness="subagents-for-tests")

    template = detail_of(project, run_id)["canvas"]["template"]

    assert "    f0_check_T0 ~~~ f0_check_T1 ~~~ f0_check_T2\n" in template
    assert "    f0_check_T3 ~~~ f0_check_T4\n" in template


def test_a_one_by_one_answer_out_of_order_keeps_one_visit(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "fanout", {"files": ["a.md", "b.md", "c.md"]}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "wrong: [b]\n", task=1)  # the packet shows task 0
    submit_answer(project, run_id, "wrong: []\n", task=0)

    rows = [row for row in detail_of(project, run_id)["timeline"] if row["block"] == "check"]

    assert [len(row["tasks"]) for row in rows] == [3] * len(rows)
    assert [task["state"] for task in rows[-1]["tasks"]] == ["done", "done", "open"]
    assert rows[-1]["tasks"][1]["output"] == {"wrong": ["b"]}


def test_a_task_heading_inside_an_instruction_adds_no_task(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    subagent_run, _ = start_run(
        project, "heading-task", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )
    one_by_one_run, _ = start_run(
        project, "heading-task", {"files": ["a.md", "b.md"]}, mode="interactive", harness="generic"
    )

    for run_id in (subagent_run, one_by_one_run):
        detail = detail_of(project, run_id)
        rows = [row for row in detail["timeline"] if row["block"] == "check"]
        assert len(rows[-1]["tasks"]) == 2
        assert "This heading is part of the instruction" in rows[-1]["tasks"][0]["packet"]
        assert "f0_check_T5" not in detail["canvas"]["template"]


def test_the_task_frame_id_never_equals_a_block_node_id(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(
        project, "heading-task", {"files": ["a.md", "b.md"]}, mode="interactive", harness="subagents-for-tests"
    )

    template = detail_of(project, run_id)["canvas"]["template"]

    assert '  subgraph f0_check_TASKS ["check · 2 tasks"]\n' in template
    assert '  f0_check_tasks["@@f0_check_tasks@@"]\n' in template


def test_an_answer_out_of_order_in_a_later_visit_stays_in_that_visit(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(
        project, "fanout-twice", {"files": ["a.md", "b.md", "c.md"]}, mode="interactive", harness="generic"
    )
    for task in range(3):
        submit_answer(project, run_id, "wrong: [v1]\n", task=task)
    submit_answer(project, run_id, "wrong: [v2]\n", task=1)  # visit 2 shows task 0

    rows = [row for row in detail_of(project, run_id)["timeline"] if row["block"] == "check"]
    first_visit = [row for row in rows if row["visit"] == 1]
    second_visit = [row for row in rows if row["visit"] == 2]

    assert [task["output"] for task in first_visit[-1]["tasks"]] == [{"wrong": ["v1"]}] * 3
    assert [task["state"] for task in second_visit[-1]["tasks"]] == ["open", "done"]
    assert second_visit[-1]["tasks"][1]["output"] == {"wrong": ["v2"]}


def test_a_node_hint_names_the_blocks_own_retries_and_timeout() -> None:
    script = ScriptBlock(id="list_files", run=["git", "ls-files"], retries=0, timeout_s=30, next=[])

    assert node_hint(script) == (
        "The runner runs a command. No AI model takes part.\n"
        "It does not try again when it fails.\n"
        "The command stops after 30 s."
    )
    assert node_hint(replace(script, retries=4, timeout_s=None)).endswith("It tries again up to 4 times when it fails.")


def test_a_choice_with_an_edge_list_draws_one_edge_per_condition(tmp_path: Path) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "per-item", PER_ITEM_SKILL)
    project = find_project(tmp_path)
    run_id, _ = start_run(project, "per-item", {"findings": ["a", "b"]}, mode="interactive", harness="generic")
    submit_answer(project, run_id, "choice: fix\nrationale: Real.\n")
    submit_answer(project, run_id, "choice: fix\nrationale: Real too.\n")

    detail = detail_of(project, run_id)

    condition = "(history.ask_finding | length) < (inputs.findings | length)"
    template = detail["canvas"]["template"]
    assert f'  f0_ask_finding -->|"fix: {condition.replace("<", "#lt;")}"| f0_ask_finding\n' in template
    assert '  f0_ask_finding -->|"fix"| f0_done\n' in template
    assert '  f0_ask_finding -->|"stop"| f0_done\n' in template
    hints = {edge["id"]: edge["hint"] for edge in detail["canvas"]["edges"]}
    assert hints["L_f0_ask_finding_f0_ask_finding_0"] == f'Taken when the decider picks "fix" and {condition}.'
    assert hints["L_f0_ask_finding_f0_done_0"] == 'Taken when the decider picks "fix" and no condition above matches.'
    assert hints["L_f0_ask_finding_f0_done_2"] == 'Taken when the decider picks "stop": Stop asking.'
    rows = detail["timeline"]
    assert [row["edge"] for row in rows] == [
        "L_start_f0_ask_finding_0",
        "L_f0_ask_finding_f0_ask_finding_0",
        "L_f0_ask_finding_f0_done_0",
    ]
    assert [row["arrival"] for row in rows[1:]] == [
        f"ask_finding (choice fix, {condition})",
        "ask_finding (choice fix)",
    ]


def test_a_choice_reason_splits_only_before_its_condition() -> None:
    assert split_choice_reason("choice yes: go") == ("yes: go", None)
    assert split_choice_reason("choice fix: {{ a < b }}") == ("fix", "{{ a < b }}")
