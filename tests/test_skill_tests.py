"""Tests for pskill_runner.skill_tests (the `pskill test` command)."""

import textwrap
from pathlib import Path

import pytest

from pskill_runner import skill_tests
from pskill_runner.project import Project, find_project
from pskill_runner.skill_tests import run_skill_tests
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill
from tests.test_engine_blocks import CHILD_SKILL, PARALLEL_SKILL, PARENT_SKILL, SCRIPT_SKILL

APPROVED_CASE = """\
name: two questions, then approval
inputs: {topic: the login page}
answers:
  create_plan:
    - {status: question, plan: Draft., question: "Which database?"}
    - {status: finished, plan: "1. Build it."}
  ask_user:
    - {answer: Postgres., $answered_by: human}
  approve_plan:
    - {choice: approve, rationale: Good., $answered_by: human}
expect:
  path: [create_plan, ask_user, create_plan, approve_plan, done]
  status: succeeded
  outputs: {result: approved}
"""


def project_with(tmp_path: Path, skill_id: str, skill_yaml: str, cases: dict[str, str], **extra: str) -> Project:
    files = {f"tests/{name}.yaml": text for name, text in cases.items()}
    if skill_id == "plan-work":
        files.update(PLAN_SKILL_FILES)
    write_skill(tmp_path / ".pskill" / "skills", skill_id, skill_yaml, files)
    for other_id, other_yaml in extra.items():
        write_skill(tmp_path / ".pskill" / "skills", other_id, other_yaml)
    (tmp_path / ".pskill" / "agents").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".pskill" / "agents" / "checker.md").write_text("You check facts.", encoding="utf-8")
    return find_project(tmp_path)


def test_a_case_whose_path_status_and_outputs_match_passes(tmp_path: Path) -> None:
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"approved": APPROVED_CASE})

    results = run_skill_tests(project, "plan-work")

    assert [(result.case, result.passed, result.problem) for result in results] == [
        ("two questions, then approval", True, None)
    ]


def test_a_wrong_path_fails_with_the_difference(tmp_path: Path) -> None:
    case = APPROVED_CASE.replace(
        "path: [create_plan, ask_user, create_plan, approve_plan, done]", "path: [create_plan, done]"
    )
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"approved": case})

    [result] = run_skill_tests(project, "plan-work")

    assert not result.passed
    assert result.problem == (
        "path: expected [create_plan, done], got [create_plan, ask_user, create_plan, approve_plan, done]"
    )


def test_path_contains_checks_an_ordered_subsequence(tmp_path: Path) -> None:
    case = APPROVED_CASE.replace(
        "path: [create_plan, ask_user, create_plan, approve_plan, done]", "path_contains: [ask_user, done]"
    )
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"approved": case})

    assert run_skill_tests(project, "plan-work")[0].passed


def test_running_out_of_answers_names_the_block(tmp_path: Path) -> None:
    case = APPROVED_CASE.replace(
        "  approve_plan:\n    - {choice: approve, rationale: Good., $answered_by: human}\n", ""
    )
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"approved": case})

    [result] = run_skill_tests(project, "plan-work")

    assert result.problem == "the block 'approve_plan' asked for an answer, but the case has no more answers for it"


def test_a_rejected_answer_is_followed_by_the_next_answer(tmp_path: Path) -> None:
    case = APPROVED_CASE.replace(
        "  create_plan:\n    - {status: question",
        "  create_plan:\n    - {status: maybe}\n    - {status: question",
    )
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"approved": case})

    assert run_skill_tests(project, "plan-work")[0].passed


def test_scripts_use_the_recorded_results(tmp_path: Path) -> None:
    case = """\
    name: recorded script
    scripts:
      list_files:
        - {exit_code: 0, stdout: '{"files": ["a", "b", "c"]}'}
    expect:
      path: [list_files, done]
      outputs: {count: 3}
    """
    project = project_with(tmp_path, "scripted", SCRIPT_SKILL, {"recorded": textwrap.dedent(case)})

    assert run_skill_tests(project, "scripted")[0].passed


def test_a_script_without_a_recorded_result_fails_the_case(tmp_path: Path) -> None:
    case = "name: no script result\nexpect:\n  status: succeeded\n"
    project = project_with(tmp_path, "scripted", SCRIPT_SKILL, {"missing": case})

    [result] = run_skill_tests(project, "scripted")

    assert result.problem == "the script block 'list_files' ran, but the case has no recorded result for it"


def test_calls_use_the_recorded_child_results(tmp_path: Path) -> None:
    case = """\
    name: recorded call
    answers:
      greet:
        - {text: Hi.}
    calls:
      child:
        - {status: succeeded, outputs: {greeting: Hello from the mock.}}
    expect:
      path: [greet, child, done]
      outputs: {greeting: Hello from the mock.}
    """
    project = project_with(tmp_path, "parent", PARENT_SKILL, {"recorded": textwrap.dedent(case)}, child=CHILD_SKILL)

    assert run_skill_tests(project, "parent")[0].passed


def call_inputs_case(recorded_inputs: str) -> str:
    """A case for PARENT_SKILL whose recorded call states the inputs that it expects."""
    case = f"""\
    name: recorded call inputs
    answers:
      greet:
        - {{text: Hi.}}
    calls:
      child:
        - {{status: succeeded, outputs: {{greeting: Hello.}}, inputs: {recorded_inputs}}}
    expect:
      status: succeeded
    """
    return textwrap.dedent(case)


def test_a_call_that_sends_the_recorded_inputs_passes(tmp_path: Path) -> None:
    case = call_inputs_case("{name: Ada}")
    project = project_with(tmp_path, "parent", PARENT_SKILL, {"inputs": case}, child=CHILD_SKILL)

    [result] = run_skill_tests(project, "parent")

    assert result.passed, result.problem


def test_a_call_that_sends_other_inputs_fails_with_the_difference(tmp_path: Path) -> None:
    case = call_inputs_case("{name: Bob}")
    project = project_with(tmp_path, "parent", PARENT_SKILL, {"inputs": case}, child=CHILD_SKILL)

    [result] = run_skill_tests(project, "parent")

    assert (
        result.problem == "the call block 'child' sent the input 'name' = 'Ada' on visit 1, but the case expects 'Bob'"
    )


def test_a_recorded_input_that_the_call_does_not_send_fails_the_case(tmp_path: Path) -> None:
    case = call_inputs_case("{age: 3}")
    project = project_with(tmp_path, "parent", PARENT_SKILL, {"inputs": case}, child=CHILD_SKILL)

    [result] = run_skill_tests(project, "parent")

    assert result.problem == "the call block 'child' did not send the input 'age' on visit 1, but the case expects 3"


def test_a_recorded_null_input_that_the_call_does_not_send_fails_the_case(tmp_path: Path) -> None:
    case = call_inputs_case("{age: null}")
    project = project_with(tmp_path, "parent", PARENT_SKILL, {"inputs": case}, child=CHILD_SKILL)

    [result] = run_skill_tests(project, "parent")

    assert result.problem == "the call block 'child' did not send the input 'age' on visit 1, but the case expects None"


def test_the_input_check_names_the_visit_of_the_call_block() -> None:
    recorded = {"status": "succeeded", "inputs": {"round": 2}}
    executor = skill_tests.RecordedExecutor({}, {"review": [recorded, recorded]})
    executor.call_result("review", "review-pr", {"round": 2})

    with pytest.raises(skill_tests.SkillTestError) as error:
        executor.call_result("review", "review-pr", {"round": 1})

    assert "on visit 2" in str(error.value)


def test_parallel_answers_are_listed_task_by_task(tmp_path: Path) -> None:
    case = """\
    name: two documents
    inputs: {files: [a.md, b.md]}
    answers:
      check:
        - {wrong: [x]}
        - {wrong: [y, z]}
    expect:
      path: [check, done]
      outputs: {wrong_count: 3}
    """
    project = project_with(tmp_path, "fanout", PARALLEL_SKILL, {"two": textwrap.dedent(case)})

    assert run_skill_tests(project, "fanout")[0].passed


def test_an_unknown_key_in_a_case_is_reported(tmp_path: Path) -> None:
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"bad": "name: bad\nexpected: {}\n"})

    [result] = run_skill_tests(project, "plan-work")

    known_keys = "answers, calls, expect, inputs, mode, name, scripts"
    assert result.problem == f"the case file has an unknown key 'expected' (known keys: {known_keys})"


def test_test_runs_leave_no_run_folders_in_the_project(tmp_path: Path) -> None:
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"approved": APPROVED_CASE})

    run_skill_tests(project, "plan-work")

    assert not project.runs_folder.exists() or not any(project.runs_folder.iterdir())


def test_a_case_file_with_broken_yaml_is_reported(tmp_path: Path) -> None:
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"broken": "name: [unclosed\n"})

    [result] = run_skill_tests(project, "plan-work")

    assert result.case == "broken"
    assert result.problem is not None and result.problem.startswith("the case file is not valid YAML:")


QUESTION_MARK_HINT = "Hint: put a value with '?' or ': ' inside { } in quotes"


def test_a_question_mark_inside_braces_adds_a_hint_to_quote_the_value(tmp_path: Path) -> None:
    case = APPROVED_CASE.replace('question: "Which database?"', "question: Which database?")
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"approved": case})

    [result] = run_skill_tests(project, "plan-work")

    assert result.problem is not None
    assert result.problem.startswith("the case file is not valid YAML:")
    assert result.problem.endswith(f'{QUESTION_MARK_HINT}, such as question: "Which database?".')


def test_other_broken_yaml_gets_no_hint(tmp_path: Path) -> None:
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"broken": "name: [unclosed\n"})

    [result] = run_skill_tests(project, "plan-work")

    assert result.problem is not None and "Hint" not in result.problem


def test_a_skill_without_a_tests_folder_has_no_cases(tmp_path: Path) -> None:
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {})

    assert run_skill_tests(project, "plan-work") == []


def test_a_call_without_a_recorded_result_fails_the_case(tmp_path: Path) -> None:
    case = "name: no call result\nanswers:\n  greet:\n    - {text: Hi.}\n"
    project = project_with(tmp_path, "parent", PARENT_SKILL, {"missing": case}, child=CHILD_SKILL)

    [result] = run_skill_tests(project, "parent")

    assert result.problem == "the call block 'child' ran, but the case has no recorded result for it"


def test_a_case_file_that_is_not_a_mapping_is_reported(tmp_path: Path) -> None:
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"listed": "- name: listed\n"})

    [result] = run_skill_tests(project, "plan-work")

    assert result.problem == "the case file must be a mapping, such as 'name: my case'"


def test_broken_yaml_without_a_question_mark_gets_no_hint(tmp_path: Path) -> None:
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"broken": "name: {a: b}: c\n"})

    [result] = run_skill_tests(project, "plan-work")

    assert result.problem is not None
    assert result.problem.startswith("the case file is not valid YAML:")
    assert "Hint" not in result.problem


def test_a_run_that_needs_more_answers_than_the_limit_stops_where_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(skill_tests, "MAX_SUBMISSIONS", 1)
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"approved": APPROVED_CASE})

    [result] = run_skill_tests(project, "plan-work")

    assert (
        result.problem
        == "path: expected [create_plan, ask_user, create_plan, approve_plan, done], got [create_plan, ask_user]"
    )


def test_a_missing_ordered_subsequence_fails_with_the_path(tmp_path: Path) -> None:
    case = APPROVED_CASE.replace(
        "path: [create_plan, ask_user, create_plan, approve_plan, done]", "path_contains: [done, ask_user]"
    )
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"approved": case})

    [result] = run_skill_tests(project, "plan-work")

    assert result.problem == (
        "path_contains: [done, ask_user] is not in order in the path "
        "[create_plan, ask_user, create_plan, approve_plan, done]"
    )


def test_a_wrong_status_fails_with_the_difference(tmp_path: Path) -> None:
    case = APPROVED_CASE.replace("  status: succeeded\n", "  status: cancelled\n")
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"approved": case})

    [result] = run_skill_tests(project, "plan-work")

    assert result.problem == "status: expected cancelled, got succeeded"


def test_a_wrong_output_fails_with_the_difference(tmp_path: Path) -> None:
    case = APPROVED_CASE.replace("outputs: {result: approved}", "outputs: {result: stopped}")
    project = project_with(tmp_path, "plan-work", PLAN_SKILL, {"approved": case})

    [result] = run_skill_tests(project, "plan-work")

    assert result.problem == "outputs.result: expected 'stopped', got 'approved'"
