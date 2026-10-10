"""Tests for the command line, run in the test's own process so that coverage sees `cli.py`.

`test_cli.py` runs the real entry script in a new process (the end-to-end checks). These tests call
`main()` directly, with stdin, the working folder, and the environment set by `monkeypatch`.
"""

import io
import re
import shutil
import sys
from pathlib import Path

import pytest

from pskill_runner import cli
from pskill_runner.engine import read_run_info
from pskill_runner.install import CACHE_VARIABLE
from pskill_runner.project import Project, find_project
from pskill_runner.release import build_release_archive, release_file_map
from pskill_runner.run_store import utc_now
from pskill_runner.run_waits import start_wait
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

# Every variable that the runner reads to detect the app (the harness) that runs it.
HARNESS_VARIABLES = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CLAUDE_PROJECT_DIR")

SPELL_SKILL = """\
schema: pskill/v1
id: spell
description: Gives letters in parallel.
goal: Two letters.
outputs:
  letters: {type: array, items: {type: string}, description: "The letters."}
entry: spell
blocks:
  spell:
    type: parallel
    for_each: [first, last]
    instruction: "Give the {{ item }} letter of tide."
    output:
      letter: {type: string, description: "One letter."}
    next: done
  done:
    type: end
    status: succeeded
    outputs: {letters: "{{ steps.spell.results | map(attribute='letter') | list }}"}
"""

PASSING_CASE = """\
name: stops at once
inputs: {topic: nothing}
answers:
  create_plan:
    - {status: finished, plan: Done.}
  approve_plan:
    - {choice: stop, rationale: No., $answered_by: human}
expect:
  status: cancelled
"""


@pytest.fixture(autouse=True)
def no_detected_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide the harness of the shell that runs the tests, so that each test sets its own."""
    for name in HARNESS_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def run_cli(monkeypatch: pytest.MonkeyPatch, *arguments: str, stdin: str | None = None) -> int:
    """Call `main()` like the entry script does. Return the exit code."""
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    return cli.main(list(arguments))


def make_project(root: Path, monkeypatch: pytest.MonkeyPatch, skill_yaml: str = PLAN_SKILL) -> Project:
    """Write the plan-work skill into `root` and make `root` the working folder."""
    write_skill(root / ".pskill" / "skills", "plan-work", skill_yaml, PLAN_SKILL_FILES)
    monkeypatch.chdir(root)
    return find_project(root)


def run_id_of(packet: str) -> str:
    match = re.search(r"Run (r-\d{8}-\d{4}-[0-9a-f]{4})", packet)
    assert match is not None, packet
    return match[1]


def start_plan(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *options: str) -> str:
    """Start the plan-work skill and return the run id."""
    assert run_cli(monkeypatch, "start", "plan-work", "--input", "topic=x", *options) == cli.EXIT_OK
    return run_id_of(capsys.readouterr().out)


def add_test_case(project: Project, file_name: str, case_yaml: str) -> None:
    tests_folder = project.skills_folder / "plan-work" / "tests"
    tests_folder.mkdir(exist_ok=True)
    (tests_folder / file_name).write_text(case_yaml, encoding="utf-8")


# --- main ----------------------------------------------------------------------------------------


def test_no_command_prints_the_help_and_exits_with_code_1(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main([])

    assert exit_code == cli.EXIT_USAGE_ERROR
    assert "usage: pskill" in capsys.readouterr().out


def test_an_unexpected_failure_exits_with_code_3_and_prints_the_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path, monkeypatch)
    broken_run = project.runs_folder / "r-broken"
    broken_run.mkdir(parents=True)
    (broken_run / "run.json").write_text("{", encoding="utf-8")

    exit_code = run_cli(monkeypatch, "runs")

    assert exit_code == cli.EXIT_INTERNAL_ERROR
    error_text = capsys.readouterr().err
    assert "pskill: internal error. Please report it with the text below." in error_text
    assert "Traceback" in error_text


def test_utf8_streams_switch_the_encoding_of_text_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    windows_console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", windows_console)
    monkeypatch.setattr(sys, "stdin", io.StringIO("a stream with no encoding to change"))

    cli.use_utf8_streams()

    assert windows_console.encoding == "utf-8"


# --- start, submit, current, task, pause, resume, cancel ----------------------------------------


def test_start_and_submit_run_a_skill_to_the_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)

    assert run_cli(monkeypatch, "start", "plan-work", "--input", "topic=the login page") == cli.EXIT_OK
    started = capsys.readouterr().out
    run_id = run_id_of(started)
    assert "Write a plan for the login page." in started

    run_cli(monkeypatch, "submit", run_id, stdin="status: finished\nplan: Build it.\n")
    assert "Show the plan:\n\nBuild it." in capsys.readouterr().out

    exit_code = run_cli(monkeypatch, "submit", run_id, stdin="choice: approve\nrationale: Good.\n$answered_by: human\n")

    assert exit_code == cli.EXIT_OK
    finished = capsys.readouterr().out
    assert "finished with status succeeded" in finished
    assert finished.endswith("\n")


def test_start_reads_the_inputs_from_stdin_as_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)

    exit_code = run_cli(monkeypatch, "start", "plan-work", "--inputs", "-", stdin="topic: a page with $dollars\n")

    assert exit_code == cli.EXIT_OK
    assert "Write a plan for a page with $dollars." in capsys.readouterr().out


def test_start_rejects_stdin_inputs_that_are_not_name_value_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)

    exit_code = run_cli(monkeypatch, "start", "plan-work", "--inputs", "-", stdin="- first\n- second\n")

    assert exit_code == cli.EXIT_USAGE_ERROR
    assert "pskill: The inputs on stdin must be 'name: value' lines." in capsys.readouterr().err


def test_start_rejects_an_input_without_an_equals_sign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)

    exit_code = run_cli(monkeypatch, "start", "plan-work", "--input", "topic")

    assert exit_code == cli.EXIT_USAGE_ERROR
    assert "pskill: --input 'topic' must look like NAME=VALUE." in capsys.readouterr().err


def test_start_records_the_mode_and_harness_from_the_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path, monkeypatch)

    run_id = start_plan(monkeypatch, capsys, "--mode", "autonomous", "--harness", "codex")

    info = read_run_info(project, run_id)
    assert info["mode"] == "autonomous"
    assert info["harness"] == "codex"


def test_start_takes_the_mode_from_the_config_and_the_harness_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)
    (tmp_path / ".pskill" / "config.yaml").write_text("default_mode: autonomous\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-a")

    run_id = start_plan(monkeypatch, capsys)

    info = read_run_info(find_project(tmp_path), run_id)
    assert info["mode"] == "autonomous"
    assert info["harness"] == "claude-code"
    assert info["session_id"] == "session-a"


def test_submit_without_an_answer_exits_with_code_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)
    run_id = start_plan(monkeypatch, capsys)

    exit_code = run_cli(monkeypatch, "submit", run_id, stdin="")

    assert exit_code == cli.EXIT_USAGE_ERROR
    assert "pskill: No answer on stdin." in capsys.readouterr().err


def test_submit_with_a_file_records_a_long_answer_with_quotes_backslashes_and_dollars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)
    run_id = start_plan(monkeypatch, capsys)
    long_line = "It's 5 o'clock in C:\\temp, and it costs $5. "
    plan = long_line * 500  # about 22 KB: the size that breaks a heredoc in Claude Code on Windows
    answer_path = f".pskill/runs/{run_id}/answers/create_plan.yaml"  # the path that the packet names
    answer_file = tmp_path / answer_path
    answer_file.write_text(f"status: finished\nplan: |\n  {plan}\n", encoding="utf-8")

    exit_code = run_cli(monkeypatch, "submit", run_id, "--file", answer_path)  # no stdin: the file only

    assert exit_code == cli.EXIT_OK
    assert f"Show the plan:\n\n{plan.strip()}" in capsys.readouterr().out
    assert not answer_file.exists()  # a later visit can never send this answer again


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ("status: bogus\nplan: A long plan.\n", "status"),
        ("$cannot_complete: The page does not exist.\n", "You could not complete the block: The page does not exist."),
    ],
    ids=["invalid field", "cannot complete"],
)
def test_submit_with_a_file_keeps_a_rejected_answer_for_the_fix(
    answer: str, error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)
    run_id = start_plan(monkeypatch, capsys)
    answer_path = f".pskill/runs/{run_id}/answers/create_plan.yaml"
    answer_file = tmp_path / answer_path
    answer_file.write_text(answer, encoding="utf-8")

    exit_code = run_cli(monkeypatch, "submit", run_id, "--file", answer_path)

    assert exit_code == cli.EXIT_OK
    packet = capsys.readouterr().out
    assert "Your last answer was rejected" in packet
    assert error in packet
    assert answer_file.exists()  # the agent fixes one field, not the whole long answer


def test_submit_with_a_file_and_a_task_number_records_the_task_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "spell", SPELL_SKILL)
    monkeypatch.chdir(tmp_path)
    run_cli(monkeypatch, "start", "spell")
    run_id = run_id_of(capsys.readouterr().out)
    answers = f".pskill/runs/{run_id}/answers"
    (tmp_path / answers / "spell-task-0.yaml").write_text("letters: t\n", encoding="utf-8")
    run_cli(monkeypatch, "submit", run_id, "--task", "0", "--file", f"{answers}/spell-task-0.yaml")
    assert "letter" in capsys.readouterr().out  # rejected: `letter` is missing
    assert (tmp_path / answers / "spell-task-0.yaml").exists()  # so the file stays for the fix
    (tmp_path / answers / "spell-task-0.yaml").write_text("letter: t\n", encoding="utf-8")
    (tmp_path / answers / "spell-task-1.yaml").write_text("letter: e\n", encoding="utf-8")

    run_cli(monkeypatch, "submit", run_id, "--task", "0", "--file", f"{answers}/spell-task-0.yaml")
    run_cli(monkeypatch, "submit", run_id, "--task", "1", "--file", f"{answers}/spell-task-1.yaml")

    assert "finished with status succeeded" in capsys.readouterr().out
    assert not list((tmp_path / answers).iterdir())  # each recorded task answer lost its file


def test_submit_with_a_file_outside_the_answers_folder_never_deletes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)
    run_id = start_plan(monkeypatch, capsys)
    own_file = tmp_path / "plan.yaml"  # a file of the user's, maybe tracked in git
    own_file.write_text("status: finished\nplan: Build it.\n", encoding="utf-8")

    exit_code = run_cli(monkeypatch, "submit", run_id, "--file", "plan.yaml")

    assert exit_code == cli.EXIT_OK
    assert own_file.exists()


def test_submit_with_a_missing_file_exits_with_code_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)
    run_id = start_plan(monkeypatch, capsys)

    exit_code = run_cli(monkeypatch, "submit", run_id, "--file", "missing.yaml")

    assert exit_code == cli.EXIT_USAGE_ERROR
    assert "pskill: No answer file at missing.yaml." in capsys.readouterr().err


def test_current_from_a_known_harness_moves_the_run_to_that_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path, monkeypatch)
    run_id = start_plan(monkeypatch, capsys, "--harness", "generic")
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")

    exit_code = run_cli(monkeypatch, "current")

    assert exit_code == cli.EXIT_OK
    assert "· create_plan (visit 1)" in capsys.readouterr().out
    assert read_run_info(project, run_id)["harness"] == "codex"


def test_current_from_an_unknown_shell_keeps_the_harness_of_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path, monkeypatch)
    run_id = start_plan(monkeypatch, capsys, "--harness", "claude-code")

    exit_code = run_cli(monkeypatch, "current", run_id)

    assert exit_code == cli.EXIT_OK
    assert read_run_info(project, run_id)["harness"] == "claude-code"


def test_task_and_submit_with_a_task_number_drive_a_parallel_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_skill(tmp_path / ".pskill" / "skills", "spell", SPELL_SKILL)
    monkeypatch.chdir(tmp_path)
    run_cli(monkeypatch, "start", "spell")
    run_id = run_id_of(capsys.readouterr().out)

    assert run_cli(monkeypatch, "task", run_id, "1") == cli.EXIT_OK
    assert "Give the last letter of tide." in capsys.readouterr().out

    run_cli(monkeypatch, "submit", run_id, "--task", "0", stdin="letter: t\n")
    run_cli(monkeypatch, "submit", run_id, "--task", "1", stdin="letter: e\n")
    assert "finished with status succeeded" in capsys.readouterr().out


def test_pause_resume_and_cancel_change_the_status_of_a_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path, monkeypatch)
    run_id = start_plan(monkeypatch, capsys)

    assert run_cli(monkeypatch, "pause", run_id) == cli.EXIT_OK
    assert "is paused" in capsys.readouterr().out
    assert run_cli(monkeypatch, "resume", run_id) == cli.EXIT_OK
    assert "· create_plan (visit 1)" in capsys.readouterr().out
    assert run_cli(monkeypatch, "cancel", run_id) == cli.EXIT_OK
    assert "cancelled" in capsys.readouterr().out
    assert read_run_info(project, run_id)["status"] == "cancelled"
    assert run_cli(monkeypatch, "delete", run_id) == cli.EXIT_OK
    assert "deleted" in capsys.readouterr().out
    assert not (project.runs_folder / run_id).exists()


# --- wait -----------------------------------------------------------------------------------------


def test_wait_records_the_wait_and_prints_one_line_at_its_alarm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path, monkeypatch)
    (project.pskill_folder / "config.yaml").write_text("wait_minutes: 0\n", encoding="utf-8")
    run_id = start_plan(monkeypatch, capsys)

    exit_code = run_cli(monkeypatch, "wait", run_id, "--reason", "the CI checks")

    assert exit_code == cli.EXIT_OK
    assert capsys.readouterr().out.startswith("0 minutes passed and nothing changed. If you still wait on the CI")
    assert read_run_info(project, run_id)["wait_reason"] == "the CI checks"


def test_wait_refuses_after_max_wait_minutes_with_exit_code_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path, monkeypatch)
    (project.pskill_folder / "config.yaml").write_text("wait_minutes: 0\nmax_wait_minutes: 0\n", encoding="utf-8")
    run_id = start_plan(monkeypatch, capsys)
    run_cli(monkeypatch, "wait", run_id, "--reason", "the CI checks")
    capsys.readouterr()

    exit_code = run_cli(monkeypatch, "wait", run_id, "--reason", "the CI checks")

    assert exit_code == cli.EXIT_USAGE_ERROR
    assert "0 minutes with nothing new" in capsys.readouterr().err


def test_runs_shows_the_reason_and_the_start_of_a_running_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path, monkeypatch)
    run_id = start_plan(monkeypatch, capsys)
    start_wait(project, run_id, "the CI checks", utc_now())
    started_at = read_run_info(project, run_id)["wait_started_at"]

    run_cli(monkeypatch, "runs", "--open")

    assert capsys.readouterr().out.endswith(f"  waiting on the CI checks since {started_at}\n")


def test_runs_shows_no_wait_for_a_paused_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path, monkeypatch)
    run_id = start_plan(monkeypatch, capsys)
    start_wait(project, run_id, "the CI checks", utc_now())
    run_cli(monkeypatch, "pause", run_id)
    capsys.readouterr()

    run_cli(monkeypatch, "runs", "--open")

    assert "waiting on" not in capsys.readouterr().out


# --- runs and list --------------------------------------------------------------------------------


def test_runs_says_when_there_are_no_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)

    exit_code = run_cli(monkeypatch, "runs")

    assert exit_code == cli.EXIT_OK
    assert capsys.readouterr().out == "No runs.\n"


def test_runs_lists_every_run_and_open_lists_only_the_unfinished_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)
    open_run = start_plan(monkeypatch, capsys)
    finished_run = start_plan(monkeypatch, capsys)
    run_cli(monkeypatch, "submit", finished_run, stdin="status: finished\nplan: Done.\n")
    run_cli(monkeypatch, "submit", finished_run, stdin="choice: stop\nrationale: No.\n$answered_by: human\n")
    capsys.readouterr()

    run_cli(monkeypatch, "runs")
    every_run = capsys.readouterr().out
    run_cli(monkeypatch, "runs", "--open")
    open_runs = capsys.readouterr().out

    assert every_run.startswith("run  skill  status  block  updated\n")
    assert f"{open_run}  plan-work  active  create_plan  " in every_run
    assert f"{finished_run}  plan-work  cancelled  stopped  " in every_run
    assert open_run in open_runs
    assert finished_run not in open_runs


def test_list_shows_valid_and_invalid_skills_and_skips_other_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path, monkeypatch)
    write_skill(project.skills_folder, "broken", "schema: pskill/v1\nid: broken\n")
    (project.skills_folder / "notes").mkdir()

    exit_code = run_cli(monkeypatch, "list")

    assert exit_code == cli.EXIT_OK
    assert capsys.readouterr().out == (
        "broken  (invalid: run `pskill validate broken`)\nplan-work  auto  Plan a piece of work with the user.\n"
    )


def test_list_says_when_the_project_has_no_skills_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".pskill").mkdir()
    monkeypatch.chdir(tmp_path)

    exit_code = run_cli(monkeypatch, "list")

    assert exit_code == cli.EXIT_OK
    assert capsys.readouterr().out == "No skills in .pskill/skills/.\n"


def test_commands_outside_a_project_exit_with_code_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = run_cli(monkeypatch, "list")

    assert exit_code == cli.EXIT_USAGE_ERROR
    assert "No .pskill folder" in capsys.readouterr().err


# --- validate -------------------------------------------------------------------------------------


def test_validate_passes_one_named_valid_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)

    exit_code = run_cli(monkeypatch, "validate", "plan-work")

    assert exit_code == cli.EXIT_OK
    assert capsys.readouterr().out == "1 skill checked: 0 errors, 0 warnings.\n"


def test_validate_rejects_an_unknown_skill_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)

    exit_code = run_cli(monkeypatch, "validate", "missing")

    assert exit_code == cli.EXIT_USAGE_ERROR
    assert "pskill: There is no skill 'missing'." in capsys.readouterr().err


def test_validate_reports_load_errors_graph_errors_and_stale_stubs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path, monkeypatch, PLAN_SKILL.replace("to: ask_user", "to: nowhere"))
    write_skill(project.skills_folder, "broken", "schema: pskill/v1\nid: broken\n")

    exit_code = run_cli(monkeypatch, "validate")

    assert exit_code == cli.EXIT_VALIDATION_ERROR
    output = capsys.readouterr().out
    assert "error  broken  skill.yaml: " in output
    assert "error  plan-work  blocks.create_plan: the target 'nowhere' is not a block" in output
    assert "error  (stubs)  .agents/skills/plan-work/SKILL.md is out of date: run `pskill sync`" in output
    assert "2 skills checked: " in output


def test_validate_with_no_skills_checks_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".pskill").mkdir()
    monkeypatch.chdir(tmp_path)
    run_cli(monkeypatch, "sync")
    capsys.readouterr()

    exit_code = run_cli(monkeypatch, "validate")

    assert exit_code == cli.EXIT_OK
    assert capsys.readouterr().out == "0 skills checked: 0 errors, 0 warnings.\n"


# --- test -----------------------------------------------------------------------------------------


def test_the_test_command_prints_one_line_per_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path, monkeypatch)
    add_test_case(project, "stop.yaml", PASSING_CASE)

    exit_code = run_cli(monkeypatch, "test", "plan-work")

    assert exit_code == cli.EXIT_OK
    assert capsys.readouterr().out == "PASS  plan-work  stops at once\n1 case run: 1 passed, 0 failed.\n"


def test_the_test_command_exits_with_code_2_when_a_case_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path, monkeypatch)
    add_test_case(project, "pass.yaml", PASSING_CASE)
    add_test_case(project, "fail.yaml", PASSING_CASE.replace("status: cancelled", "status: succeeded"))

    exit_code = run_cli(monkeypatch, "test")

    assert exit_code == cli.EXIT_VALIDATION_ERROR
    output = capsys.readouterr().out
    assert "FAIL  plan-work  stops at once: status: expected succeeded, got cancelled" in output
    assert "2 cases run: 1 passed, 1 failed." in output


def test_the_test_command_with_no_cases_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)

    exit_code = run_cli(monkeypatch, "test")

    assert exit_code == cli.EXIT_OK
    assert capsys.readouterr().out == "0 cases run: 0 passed, 0 failed.\n"


# --- sync -----------------------------------------------------------------------------------------


def test_sync_writes_the_files_then_reports_that_everything_is_up_to_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)

    assert run_cli(monkeypatch, "sync") == cli.EXIT_OK
    assert ".claude/skills/plan-work/SKILL.md was " in capsys.readouterr().out
    assert (tmp_path / ".claude" / "settings.json").is_file()

    assert run_cli(monkeypatch, "sync", "--check") == cli.EXIT_OK
    assert capsys.readouterr().out == "Everything is up to date.\n"


def test_sync_check_exits_with_code_2_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)

    exit_code = run_cli(monkeypatch, "sync", "--check")

    assert exit_code == cli.EXIT_VALIDATION_ERROR
    assert ".claude/skills/plan-work/SKILL.md is out of date" in capsys.readouterr().out
    assert not (tmp_path / ".claude").exists()


# --- init and update ------------------------------------------------------------------------------


def make_empty_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / "new-project"
    project_root.mkdir()
    monkeypatch.chdir(project_root)
    return project_root


@pytest.fixture
def release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A local release archive as the latest release, and a runner cache for this test only."""
    archive = build_release_archive(REPOSITORY_ROOT, tmp_path / "release" / "pskill.zip")
    monkeypatch.setenv("PSKILL_RELEASE_URL", archive.as_uri())
    monkeypatch.setenv(CACHE_VARIABLE, str(tmp_path / "cache"))
    return archive


def test_init_without_from_pins_the_latest_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], release: Path
) -> None:
    project_root = make_empty_folder(tmp_path, monkeypatch)

    exit_code = run_cli(monkeypatch, "init")

    assert exit_code == cli.EXIT_OK
    assert release.as_uri() in (project_root / ".pskill" / "pskill.py").read_text(encoding="utf-8")
    assert (project_root / ".claude" / "settings.json").is_file()
    assert capsys.readouterr().out.endswith(
        "Next: add a skill in .pskill/skills/<id>/, then run `uv run .pskill/pskill.py sync`.\n"
    )


def test_init_from_a_folder_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], release: Path
) -> None:
    project_root = make_empty_folder(tmp_path, monkeypatch)

    exit_code = run_cli(monkeypatch, "init", "--from", str(REPOSITORY_ROOT))

    assert exit_code == cli.EXIT_USAGE_ERROR
    assert "is not a pskill release" in capsys.readouterr().err
    assert not (project_root / ".pskill" / "pskill.py").exists()


def test_update_without_from_takes_the_release_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], release: Path
) -> None:
    make_empty_folder(tmp_path, monkeypatch)
    run_cli(monkeypatch, "init")
    capsys.readouterr()

    exit_code = run_cli(monkeypatch, "update")

    assert exit_code == cli.EXIT_OK
    assert "Updated pskill from" in capsys.readouterr().out


def test_update_exits_with_code_3_when_the_sync_after_it_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], release: Path
) -> None:
    broken_version = tmp_path / "broken-version"
    for relative_path, source in release_file_map(REPOSITORY_ROOT).items():
        (broken_version / relative_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, broken_version / relative_path)
    (broken_version / "pskill_runner" / "cli.py").write_text("raise SystemExit('this runner is broken')\n")
    broken_release = build_release_archive(broken_version, tmp_path / "broken.zip")
    make_empty_folder(tmp_path, monkeypatch)
    run_cli(monkeypatch, "init")
    capsys.readouterr()

    exit_code = run_cli(monkeypatch, "update", "--from", str(broken_release))

    assert exit_code == cli.EXIT_INTERNAL_ERROR
    output = capsys.readouterr().out
    assert "The sync after the update failed." in output
    assert "this runner is broken" in output


def test_authoring_prints_the_guide_for_writing_skills(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = run_cli(monkeypatch, "authoring")

    assert exit_code == cli.EXIT_OK
    assert "## A complete example" in capsys.readouterr().out


# --- view -----------------------------------------------------------------------------------------


class ViewerCall:
    """What `serve_viewer` received, in place of a real server that would never return."""

    def __init__(self) -> None:
        self.viewer_folder: Path | None = None
        self.port: int | None = None
        self.open_browser: bool | None = None

    def record(self, project: Project, viewer_folder: Path, port: int, open_browser: bool) -> None:
        self.viewer_folder = viewer_folder
        self.port = port
        self.open_browser = open_browser


@pytest.fixture
def viewer_call(monkeypatch: pytest.MonkeyPatch) -> ViewerCall:
    call = ViewerCall()
    monkeypatch.setattr(cli, "serve_viewer", call.record)
    return call


def test_view_serves_the_viewer_on_the_port_from_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, viewer_call: ViewerCall
) -> None:
    make_project(tmp_path, monkeypatch)
    (tmp_path / ".pskill" / "config.yaml").write_text("viewer_port: 8123\n", encoding="utf-8")

    exit_code = run_cli(monkeypatch, "view")

    assert exit_code == cli.EXIT_OK
    assert viewer_call.port == 8123
    assert viewer_call.open_browser is True
    assert viewer_call.viewer_folder == REPOSITORY_ROOT / "viewer"


def test_view_takes_the_port_and_no_open_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, viewer_call: ViewerCall
) -> None:
    make_project(tmp_path, monkeypatch)

    exit_code = run_cli(monkeypatch, "view", "--port", "0", "--no-open")

    assert exit_code == cli.EXIT_OK
    assert viewer_call.port == 0
    assert viewer_call.open_browser is False


# --- hook -----------------------------------------------------------------------------------------


def test_the_claude_stop_hook_blocks_the_session_that_owns_an_open_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-a")
    run_id = start_plan(monkeypatch, capsys)

    other_session = run_cli(monkeypatch, "hook", "stop", "--harness", "claude-code", stdin='{"session_id": "b"}')
    other_output = capsys.readouterr().out
    owner_session = run_cli(
        monkeypatch, "hook", "stop", "--harness", "claude-code", stdin='{"session_id": "session-a"}'
    )
    owner_output = capsys.readouterr().out

    assert (other_session, owner_session) == (cli.EXIT_OK, cli.EXIT_OK)
    assert other_output == ""
    assert f"pskill run {run_id} has an open block" in owner_output
    assert '"hookEventName": "Stop"' in owner_output


def test_a_shared_stop_hook_detects_codex_and_answers_with_a_block_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)
    start_plan(monkeypatch, capsys, "--harness", "codex")

    exit_code = run_cli(monkeypatch, "hook", "stop", "--harness", "auto", stdin='{"turn_id": "t1"}')

    assert exit_code == cli.EXIT_OK
    assert '"decision": "block"' in capsys.readouterr().out


def test_a_generic_stop_hook_prints_the_reason_as_plain_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)
    run_id = start_plan(monkeypatch, capsys, "--harness", "generic")

    exit_code = run_cli(monkeypatch, "hook", "stop", "--harness", "generic", stdin="{}")

    assert exit_code == cli.EXIT_OK
    output = capsys.readouterr().out
    assert output.startswith(f"pskill run {run_id} has an open block.")
    assert output.endswith(" instead.\n")


def test_a_generic_stop_hook_with_nothing_open_prints_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)

    exit_code = run_cli(monkeypatch, "hook", "stop", "--harness", "generic", stdin="{}")

    assert exit_code == cli.EXIT_OK
    assert capsys.readouterr().out == ""


def test_a_hook_finds_the_project_from_the_cwd_in_its_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_root = tmp_path / "project"
    make_project(project_root, monkeypatch)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    hook_input = '{"cwd": "' + project_root.as_posix() + '"}'

    exit_code = run_cli(monkeypatch, "hook", "session-start", "--harness", "claude-code", stdin=hook_input)

    assert exit_code == cli.EXIT_OK
    assert "pskill: updated" in capsys.readouterr().out
    assert (project_root / ".claude" / "skills" / "plan-work" / "SKILL.md").is_file()


@pytest.mark.parametrize("hook_stdin", ["", "[1, 2]"], ids=["no input", "input that is not an object"])
def test_a_hook_with_no_usable_input_uses_the_working_folder(
    hook_stdin: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path, monkeypatch)

    exit_code = run_cli(monkeypatch, "hook", "session-start", "--harness", "claude-code", stdin=hook_stdin)

    assert exit_code == cli.EXIT_OK
    assert "pskill: updated" in capsys.readouterr().out


def test_a_failing_hook_reports_on_stderr_and_still_exits_with_code_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = run_cli(monkeypatch, "hook", "stop", "--harness", "claude-code", stdin="{}")

    assert exit_code == cli.EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("pskill hook stop: No .pskill folder")
