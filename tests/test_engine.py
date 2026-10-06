"""Tests for pskill_runner.engine: running a skill block by block."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from pskill_runner.engine import (
    RunError,
    cancel_run,
    current_packet,
    delete_run,
    pause_run,
    read_run_info,
    read_run_state,
    register_stop_attempt,
    resume_run,
    start_run,
    submit_answer,
    task_packet,
)
from pskill_runner.project import Project, find_project
from pskill_runner.run_store import read_events
from tests.skill_files import PER_ITEM_SKILL, PLAN_SKILL, PLAN_SKILL_FILES, write_skill

FINISHED_PLAN = "status: finished\nplan: |\n  1. Build the form.\n  2. Add the tests.\n"
QUESTION_PLAN = "status: question\nplan: Draft.\nquestion: Which database?\n"

SMALL_SKILL = """\
schema: pskill/v1
id: small
description: A task, then the end.
goal: Say hello.
outputs:
  greeting: {type: string, description: "The greeting."}
entry: greet
blocks:
  greet:
    type: task
    instruction: "Say hello."
    output:
      text: {type: string, description: "The greeting."}
    next: done
  done:
    type: end
    status: succeeded
    outputs: {greeting: "{{ steps.greet.text }}"}
    report: "Tell the user: {{ steps.greet.text }}"
"""


def make_project(tmp_path: Path, skill_id: str = "plan-work", skill_yaml: str = PLAN_SKILL) -> Project:
    files = PLAN_SKILL_FILES if skill_id == "plan-work" else {}
    write_skill(tmp_path / ".pskill" / "skills", skill_id, skill_yaml, files)
    return find_project(tmp_path)


def start(project: Project, skill_id: str = "plan-work", mode: str = "interactive", **inputs: Any) -> str:
    run_id, _ = start_run(project, skill_id, inputs or {"topic": "the login page"}, mode=mode, harness="generic")
    return run_id


def event_types(project: Project, run_id: str) -> list[str]:
    return [event["type"] for event in read_events(project.runs_folder / run_id)]


def test_start_prints_the_first_block_and_records_the_run(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    run_id, packet = start_run(project, "plan-work", {"topic": "the login page"}, mode="interactive", harness="generic")

    assert "· plan-work · create_plan (visit 1)" in packet
    assert "Write a plan for the login page." in packet
    assert "### Goal" not in packet  # the stub gives the goal
    info = read_run_info(project, run_id)
    assert info["status"] == "active"
    assert info["current_block"] == "create_plan"
    assert (project.runs_folder / run_id / "skills" / "plan-work" / "skill.yaml").is_file()
    assert event_types(project, run_id) == ["run_started", "block_started"]
    assert "Write a plan for the login page." in read_events(project.runs_folder / run_id)[1]["packet"]


def test_a_task_then_an_end_finishes_the_run_with_its_outputs(tmp_path: Path) -> None:
    project = make_project(tmp_path, "small", SMALL_SKILL)
    run_id, _ = start_run(project, "small", {}, mode="interactive", harness="generic")

    packet = submit_answer(project, run_id, "text: Hello, Ada!\n")

    info = read_run_info(project, run_id)
    assert info["status"] == "succeeded"
    assert info["outputs"] == {"greeting": "Hello, Ada!"}
    assert "Run " + run_id + " finished with status succeeded." in packet
    assert "Tell the user: Hello, Ada!" in packet
    assert event_types(project, run_id)[-1] == "run_ended"


def test_a_condition_list_picks_the_first_matching_edge(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    packet = submit_answer(project, run_id, QUESTION_PLAN)

    assert "· ask_user (visit 1)" in packet
    assert "Ask the user: Which database?" in packet
    assert read_run_info(project, run_id)["status"] == "waiting_for_human"


def test_a_choice_map_picks_the_edge_of_the_choice(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    submit_answer(project, run_id, FINISHED_PLAN)

    packet = submit_answer(project, run_id, "choice: stop\nrationale: Not now.\n$answered_by: human\n")

    assert read_run_info(project, run_id)["status"] == "cancelled"
    assert read_run_info(project, run_id)["outputs"] == {"result": "stopped"}
    assert "finished with status cancelled" in packet


def test_an_invalid_answer_is_rejected_with_the_errors(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    packet = submit_answer(project, run_id, "status: maybe\n")

    assert "### Errors" in packet
    assert "- 'plan' is a required field" in packet
    assert "- status: 'maybe' is not one of: finished, question" in packet
    assert read_run_info(project, run_id)["attempts"] == 1
    assert event_types(project, run_id)[-1] == "submission_rejected"


def test_a_yaml_answer_converts_by_the_declared_types(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace(
        "approve: Accept the plan.\n      stop: Stop without a plan.",
        "yes: Accept the plan.\n      no: Stop without a plan.",
    ).replace("next: {approve: done, stop: stopped}", "next: {yes: done, no: stopped}")
    project = make_project(tmp_path, skill_yaml=skill_yaml)
    run_id = start(project)
    submit_answer(project, run_id, FINISHED_PLAN)

    submit_answer(project, run_id, "choice: no\nrationale: Later.\n$answered_by: human\n")

    frame = read_run_state(project, run_id)["frames"][0]
    assert frame["steps"]["create_plan"]["plan"] == "1. Build the form.\n2. Add the tests.\n"
    assert frame["steps"]["approve_plan"]["choice"] == "no"
    assert read_run_info(project, run_id)["outputs"] == {"result": "stopped"}


def test_the_run_pauses_when_the_retries_run_out(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    for _ in range(2):
        submit_answer(project, run_id, "status: maybe\n")
    packet = submit_answer(project, run_id, "status: maybe\n")

    info = read_run_info(project, run_id)
    assert info["status"] == "paused"
    assert info["pause_reason"] == "block_failed"
    assert "is paused at block create_plan (block_failed)" in packet


def test_cannot_complete_counts_as_a_failed_attempt(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    packet = submit_answer(project, run_id, "$cannot_complete: The repository is empty.\n")

    assert "The repository is empty." in packet
    assert read_run_info(project, run_id)["attempts"] == 1


def test_max_visits_redirects_to_on_max_visits(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    for _ in range(3):
        submit_answer(project, run_id, QUESTION_PLAN)
        packet = submit_answer(project, run_id, "answer: Postgres.\n$answered_by: human\n")

    assert read_run_info(project, run_id)["status"] == "cancelled"
    assert "finished with status cancelled" in packet


def test_history_keeps_every_visit(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    submit_answer(project, run_id, QUESTION_PLAN)
    submit_answer(project, run_id, "answer: Postgres.\n$answered_by: human\n")
    submit_answer(project, run_id, QUESTION_PLAN.replace("Which database?", "Which cache?"))
    submit_answer(project, run_id, "answer: Redis.\n$answered_by: human\n")

    frame = read_run_state(project, run_id)["frames"][0]
    assert [visit["answer"] for visit in frame["history"]["ask_user"]] == ["Postgres.", "Redis."]
    assert frame["steps"]["ask_user"]["answer"] == "Redis."
    assert frame["visits"]["create_plan"] == 3


def test_a_human_decision_in_interactive_mode_needs_answered_by(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    submit_answer(project, run_id, QUESTION_PLAN)

    packet = submit_answer(project, run_id, "answer: Postgres.\n")

    assert "$answered_by" in packet.split("### Errors")[1].split("###")[0]


def test_a_human_decision_in_autonomous_mode_is_taken_by_the_agent(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project, mode="autonomous")
    submit_answer(project, run_id, QUESTION_PLAN)

    submit_answer(project, run_id, "answer: Postgres, as the project already uses it.\n")

    completed = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "block_completed"]
    assert completed[-1]["block"] == "ask_user"
    assert completed[-1]["decided_by"] == "agent_autonomous"
    assert read_run_info(project, run_id)["status"] == "active"


def test_a_conditional_entry_picks_the_first_block(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace(
        "entry: create_plan",
        "entry:\n  - when: \"{{ inputs.topic == 'nothing' }}\"\n    to: stopped\n  - to: create_plan",
    )
    project = make_project(tmp_path, skill_yaml=skill_yaml)

    run_id, packet = start_run(project, "plan-work", {"topic": "nothing"}, mode="interactive", harness="generic")

    assert read_run_info(project, run_id)["status"] == "cancelled"
    assert "finished with status cancelled" in packet


def test_no_matching_edge_pauses_the_run(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace(
        "      - to: approve_plan\n",
        "      - when: \"{{ steps.create_plan.status == 'never' }}\"\n        to: approve_plan\n",
    )
    project = make_project(tmp_path, skill_yaml=skill_yaml)
    run_id = start(project)

    packet = submit_answer(project, run_id, FINISHED_PLAN)

    assert read_run_info(project, run_id)["pause_reason"] == "runner_error"
    assert "no edge matched" in packet


def test_pause_resume_and_cancel(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    assert "is paused" in pause_run(project, run_id)
    with pytest.raises(RunError, match="paused"):
        submit_answer(project, run_id, FINISHED_PLAN)
    assert "· create_plan (visit 1)" in resume_run(project, run_id)
    assert read_run_info(project, run_id)["status"] == "active"
    assert "cancelled" in cancel_run(project, run_id)
    assert read_run_info(project, run_id)["status"] == "cancelled"
    assert event_types(project, run_id)[-3:] == ["run_paused", "run_resumed", "run_ended"]


def test_delete_removes_the_folder_of_a_finished_run(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    cancel_run(project, run_id)

    assert "deleted" in delete_run(project, run_id)
    assert not (project.runs_folder / run_id).exists()


def test_an_unfinished_run_must_be_cancelled_before_it_is_deleted(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    with pytest.raises(RunError, match="Cancel it first"):
        delete_run(project, run_id)
    assert (project.runs_folder / run_id / "run.json").is_file()


def test_delete_refuses_a_folder_outside_the_runs_folder(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    project.runs_folder.mkdir()  # Linux and macOS resolve "runs/../keep" only when runs/ exists
    outside = project.pskill_folder / "keep"
    outside.mkdir()
    (outside / "run.json").write_text('{"status": "cancelled"}', encoding="utf-8")

    with pytest.raises(RunError, match="There is no run"):
        delete_run(project, "../keep")
    assert outside.is_dir()


def test_current_prints_the_same_packet_without_changing_the_run(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    events_before = event_types(project, run_id)

    packet = current_packet(project, run_id)

    assert "· create_plan (visit 1)" in packet
    assert event_types(project, run_id) == events_before


def test_current_and_resume_repeat_the_goal_and_the_rules_for_a_new_session(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    current = current_packet(project, run_id)
    pause_run(project, run_id)
    resumed = resume_run(project, run_id)

    for packet in (current, resumed):
        assert "### Goal\nProduce a plan that the user approved." in packet
        assert "### Rules" in packet


def test_current_without_a_run_id_uses_the_newest_unfinished_run(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    assert f"Run {run_id}" in current_packet(project, None)


def test_start_rejects_a_skill_with_errors(tmp_path: Path) -> None:
    project = make_project(tmp_path, skill_yaml=PLAN_SKILL.replace("to: ask_user", "to: nowhere"))

    with pytest.raises(RunError, match="nowhere"):
        start(project)


INTERNAL_PLAN_SKILL = PLAN_SKILL.replace("goal:", "invocation: internal\ngoal:", 1)


def test_start_rejects_an_internal_skill(tmp_path: Path) -> None:
    project = make_project(tmp_path, skill_yaml=INTERNAL_PLAN_SKILL)

    with pytest.raises(RunError, match=r"internal skill.*call block"):
        start(project)


def test_an_internal_skill_starts_when_the_caller_allows_it(tmp_path: Path) -> None:
    project = make_project(tmp_path, skill_yaml=INTERNAL_PLAN_SKILL)

    run_id, _ = start_run(
        project, "plan-work", {"topic": "Login"}, mode="interactive", harness="generic", allow_internal=True
    )

    assert run_id.startswith("r-")


def test_start_rejects_invalid_inputs(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    with pytest.raises(RunError, match="'topic' is a required field"):
        start_run(project, "plan-work", {}, mode="interactive", harness="generic")


def test_a_run_that_continues_in_another_harness_records_the_change(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    submit_answer(project, run_id, QUESTION_PLAN, harness="claude-code")

    assert read_run_info(project, run_id)["harness"] == "claude-code"
    changed = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "harness_changed"]
    assert [(event["from"], event["to"]) for event in changed] == [("generic", "claude-code")]


def test_current_in_another_harness_records_the_change(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    current_packet(project, run_id, harness="codex")

    assert read_run_info(project, run_id)["harness"] == "codex"
    changed = [event for event in read_events(project.runs_folder / run_id) if event["type"] == "harness_changed"]
    assert [(event["from"], event["to"]) for event in changed] == [("generic", "codex")]


def test_a_block_with_its_own_retries_pauses_after_them(tmp_path: Path) -> None:
    project = make_project(
        tmp_path, skill_yaml=PLAN_SKILL.replace("    max_visits: 3\n", "    max_visits: 3\n    retries: 0\n")
    )
    run_id = start(project)

    packet = submit_answer(project, run_id, "status: maybe\n")

    assert read_run_info(project, run_id)["pause_reason"] == "block_failed"
    assert "is paused at block create_plan (block_failed)" in packet


def test_a_choice_with_an_edge_list_takes_the_first_matching_edge(tmp_path: Path) -> None:
    project = make_project(tmp_path, "per-item", PER_ITEM_SKILL)
    run_id, _ = start_run(project, "per-item", {"findings": ["a", "b"]}, mode="interactive", harness="generic")

    packet = submit_answer(project, run_id, "choice: fix\nrationale: Real bug.\n")

    frame = read_run_state(project, run_id)["frames"][0]
    assert (frame["current_block"], frame["visits"]["ask_finding"]) == ("ask_finding", 2)
    assert frame["arrival_reason"] == "choice fix: {{ (history.ask_finding | length) < (inputs.findings | length) }}"
    assert "- fix: Fix the finding." in packet
    submit_answer(project, run_id, "choice: fix\nrationale: Also real.\n")
    info = read_run_info(project, run_id)
    assert (info["status"], info["outputs"]) == ("succeeded", {"fixed": 2})


def test_a_plain_choice_target_still_records_the_choice(tmp_path: Path) -> None:
    project = make_project(tmp_path, "per-item", PER_ITEM_SKILL)
    run_id, _ = start_run(project, "per-item", {"findings": ["a", "b"]}, mode="interactive", harness="generic")

    submit_answer(project, run_id, "choice: stop\nrationale: Enough.\n")

    assert read_run_info(project, run_id)["outputs"] == {"fixed": 0}
    assert read_run_state(project, run_id)["frames"][0]["arrival_reason"] == "choice stop"


def test_current_without_a_run_id_fails_when_every_run_is_finished(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    cancel_run(project, start(project))

    with pytest.raises(RunError, match="There is no unfinished run"):
        current_packet(project, None)


def test_a_command_on_an_unknown_run_fails(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    with pytest.raises(RunError, match="There is no run 'r-unknown'"):
        pause_run(project, "r-unknown")


def test_start_rejects_an_unknown_skill(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    with pytest.raises(RunError, match="There is no skill 'nothing-here'"):
        start(project, "nothing-here")


def test_start_rejects_a_skill_that_does_not_load(tmp_path: Path) -> None:
    project = make_project(tmp_path, "broken", "schema: pskill/v1\nblocks: [\n")

    with pytest.raises(RunError, match="The skill 'broken' is invalid"):
        start(project, "broken")


def test_a_run_records_the_git_commit_and_the_uncommitted_changes(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.com"]
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    subprocess.run(
        [*git, "-c", "commit.gpgsign=false", "commit", "--quiet", "--allow-empty", "-m", "First"], check=True
    )
    head = subprocess.run([*git, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)

    info = read_run_info(project, start(project))

    assert info["repo_commit"] == head.stdout.strip()
    assert info["repo_dirty"] is True  # the skill files are not committed


def test_a_run_outside_git_records_no_commit(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    info = read_run_info(project, start(project))

    assert (info["repo_commit"], info["repo_dirty"]) == (None, None)


def test_a_visit_cap_without_on_max_visits_pauses_the_run(tmp_path: Path) -> None:
    project = make_project(tmp_path, skill_yaml=PLAN_SKILL.replace("    on_max_visits: stopped\n", ""))
    run_id = start(project)

    for _ in range(3):
        submit_answer(project, run_id, QUESTION_PLAN)
        packet = submit_answer(project, run_id, "answer: Postgres.\n$answered_by: human\n")

    info = read_run_info(project, run_id)
    assert (info["status"], info["pause_reason"]) == ("paused", "runner_error")
    assert "The block 'create_plan' reached its visit cap (3)." in packet


def test_a_run_that_matched_no_entry_edge_cannot_resume(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace(
        "entry: create_plan", "entry:\n  - when: \"{{ inputs.topic == 'nothing' }}\"\n    to: create_plan"
    )
    project = make_project(tmp_path, skill_yaml=skill_yaml)
    run_id, packet = start_run(project, "plan-work", {"topic": "the login page"}, mode="interactive", harness="generic")

    assert "is paused at block (none) (runner_error)" in packet
    with pytest.raises(RunError, match="The run has no current block"):
        resume_run(project, run_id)


def test_a_condition_that_fails_pauses_the_run(tmp_path: Path) -> None:
    skill_yaml = PLAN_SKILL.replace("steps.create_plan.status == 'question'", "steps.create_plan.question | length > 0")
    project = make_project(tmp_path, skill_yaml=skill_yaml)
    run_id = start(project)

    packet = submit_answer(project, run_id, FINISHED_PLAN)  # no question: the condition reads a missing value

    assert read_run_info(project, run_id)["pause_reason"] == "runner_error"
    assert "The condition '{{ steps.create_plan.question | length > 0 }}' failed" in packet


SMALL_SKILL_WITH_NOTE = SMALL_SKILL.replace(
    '      text: {type: string, description: "The greeting."}\n',
    '      text: {type: string, description: "The greeting."}\n'
    '      note: {type: string, optional: true, description: "A note."}\n',
)


def test_an_end_output_that_fails_to_compute_pauses_the_run(tmp_path: Path) -> None:
    skill_yaml = SMALL_SKILL_WITH_NOTE.replace(
        '{greeting: "{{ steps.greet.text }}"}', '{greeting: "{{ steps.greet.note }}"}'
    )
    project = make_project(tmp_path, "small", skill_yaml)
    run_id, _ = start_run(project, "small", {}, mode="interactive", harness="generic")

    packet = submit_answer(project, run_id, "text: Hello, Ada!\n")

    assert read_run_info(project, run_id)["pause_reason"] == "runner_error"
    assert "The end block 'done' failed" in packet and "the value is missing" in packet


def test_a_report_that_fails_to_render_pauses_the_run(tmp_path: Path) -> None:
    skill_yaml = SMALL_SKILL_WITH_NOTE.replace(
        "Tell the user: {{ steps.greet.text }}", "Tell the user: {{ steps.greet.note }}"
    )
    project = make_project(tmp_path, "small", skill_yaml)
    run_id, _ = start_run(project, "small", {}, mode="interactive", harness="generic")

    packet = submit_answer(project, run_id, "text: Hello, Ada!\n")

    info = read_run_info(project, run_id)
    assert (info["status"], info["pause_reason"], info["outputs"]) == ("paused", "runner_error", None)
    assert "The report failed" in packet


def test_an_end_output_of_the_wrong_type_pauses_the_run(tmp_path: Path) -> None:
    skill_yaml = SMALL_SKILL.replace(
        'greeting: {type: string, description: "The greeting."}',
        'greeting: {type: integer, description: "The greeting."}',
    )
    project = make_project(tmp_path, "small", skill_yaml)
    run_id, _ = start_run(project, "small", {}, mode="interactive", harness="generic")

    packet = submit_answer(project, run_id, "text: Hello, Ada!\n")

    assert read_run_info(project, run_id)["pause_reason"] == "runner_error"
    assert "The end block 'done' gives invalid outputs: " in packet


def test_current_on_a_paused_run_prints_the_pause_text(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    pause_run(project, run_id)

    packet = current_packet(project, run_id)

    assert "is paused at block create_plan (paused_by_user)" in packet
    assert read_run_info(project, run_id)["status"] == "paused"


def test_the_task_command_refuses_a_block_without_tasks(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    with pytest.raises(RunError, match="The block 'create_plan' has no tasks"):
        task_packet(project, run_id, 0)


def test_a_task_number_on_a_block_without_tasks_is_refused(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    with pytest.raises(RunError, match="has no tasks, so `--task` does not apply"):
        submit_answer(project, run_id, FINISHED_PLAN, task=0)
    assert read_run_info(project, run_id)["current_block"] == "create_plan"


def test_a_task_number_is_refused_while_stop_attempts_pause_a_block_without_tasks(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    while register_stop_attempt(project, run_id):
        pass

    with pytest.raises(RunError, match="has no tasks, so `--task` does not apply"):
        submit_answer(project, run_id, FINISHED_PLAN, task=0)


def test_an_answer_that_is_not_yaml_is_rejected(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    packet = submit_answer(project, run_id, "status: [finished\n")

    assert "- The answer is not valid YAML: " in packet.split("### Errors")[1]
    assert read_run_info(project, run_id)["attempts"] == 1


def test_a_colon_in_plain_text_gets_the_free_text_hint(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    packet = submit_answer(project, run_id, "status: finished\nnote: getOneById(id): Promise<Group>\n")

    errors = packet.split("### Errors")[1]
    assert "- The answer is not valid YAML: " in errors
    assert "Write free text as `field: |` with indented lines." in errors
