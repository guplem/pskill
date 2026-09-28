"""Tests for the command line, run through the real entry script."""

import re
import subprocess
import sys
import time
from pathlib import Path

from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill

ENTRY_SCRIPT = Path(__file__).resolve().parent.parent / "pskill.py"


def run_pskill(project_root: Path, *arguments: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ENTRY_SCRIPT), *arguments],
        cwd=project_root,
        input=stdin,
        stdin=subprocess.DEVNULL if stdin is None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def make_project(root: Path, skill_yaml: str = PLAN_SKILL) -> Path:
    write_skill(root / ".pskill" / "skills", "plan-work", skill_yaml, PLAN_SKILL_FILES)
    return root


def run_id_of(packet: str) -> str:
    match = re.search(r"Run (r-\d{8}-\d{4}-[0-9a-f]{4})", packet)
    assert match is not None, packet
    return match[1]


def test_a_five_block_skill_runs_to_the_end_through_start_and_submit(tmp_path: Path) -> None:
    root = make_project(tmp_path)

    started = run_pskill(root, "start", "plan-work", "--input", "topic=the login page")
    assert started.returncode == 0, started.stderr
    run_id = run_id_of(started.stdout)
    assert "Write a plan for the login page." in started.stdout

    asked = run_pskill(root, "submit", run_id, stdin="status: question\nplan: Draft.\nquestion: Which database?\n")
    assert "Ask the user: Which database?" in asked.stdout

    replanned = run_pskill(root, "submit", run_id, stdin="answer: Postgres.\n$answered_by: human\n")
    assert "· create_plan (visit 2)" in replanned.stdout

    approval = run_pskill(root, "submit", run_id, stdin="status: finished\nplan: |\n  1. Build it.\n  2. Test it.\n")
    assert "Show the plan:\n\n1. Build it.\n2. Test it." in approval.stdout

    finished = run_pskill(
        root, "submit", run_id, stdin="choice: approve\nrationale: Looks good.\n$answered_by: human\n"
    )
    assert finished.returncode == 0, finished.stderr
    assert "finished with status succeeded" in finished.stdout
    assert "result: approved" in finished.stdout


def test_inputs_can_come_from_stdin_as_yaml(tmp_path: Path) -> None:
    root = make_project(tmp_path)

    started = run_pskill(
        root, "start", "plan-work", "--inputs", "-", stdin="topic: |\n  a page with 'quotes' and $dollars\n"
    )

    assert started.returncode == 0, started.stderr
    assert "Write a plan for a page with 'quotes' and $dollars" in started.stdout


def test_submit_without_an_answer_fails_quickly(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    run_id = run_id_of(run_pskill(root, "start", "plan-work", "--input", "topic=x").stdout)
    started = time.monotonic()

    result = run_pskill(root, "submit", run_id)

    assert result.returncode == 1
    assert "No answer" in result.stderr
    assert time.monotonic() - started < 10


def test_current_and_pause_resume_cancel(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    run_id = run_id_of(run_pskill(root, "start", "plan-work", "--input", "topic=x").stdout)

    assert "· create_plan (visit 1)" in run_pskill(root, "current").stdout
    assert "is paused" in run_pskill(root, "pause", run_id).stdout
    assert "· create_plan (visit 1)" in run_pskill(root, "resume", run_id).stdout
    assert "cancelled" in run_pskill(root, "cancel", run_id).stdout
    assert "cancelled" in run_pskill(root, "runs").stdout


def test_runs_open_lists_only_unfinished_runs(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    open_run = run_id_of(run_pskill(root, "start", "plan-work", "--input", "topic=x").stdout)
    closed_run = run_id_of(run_pskill(root, "start", "plan-work", "--input", "topic=y").stdout)
    run_pskill(root, "cancel", closed_run)

    listed = run_pskill(root, "runs", "--open").stdout

    assert open_run in listed
    assert closed_run not in listed


def test_list_shows_the_skills(tmp_path: Path) -> None:
    listed = run_pskill(make_project(tmp_path), "list")

    assert listed.returncode == 0
    assert "plan-work" in listed.stdout
    assert "Plan a piece of work with the user." in listed.stdout


def test_validate_passes_a_valid_skill(tmp_path: Path) -> None:
    result = run_pskill(make_project(tmp_path), "validate")

    assert result.returncode == 0, result.stdout
    assert "1 skill checked: 0 errors, 0 warnings." in result.stdout


def test_validate_fails_with_exit_code_2_on_errors(tmp_path: Path) -> None:
    result = run_pskill(make_project(tmp_path, PLAN_SKILL.replace("to: ask_user", "to: nowhere")), "validate")

    assert result.returncode == 2
    assert "error  plan-work  blocks.create_plan: the target 'nowhere' is not a block" in result.stdout


def test_a_usage_error_exits_with_code_1(tmp_path: Path) -> None:
    result = run_pskill(make_project(tmp_path), "submit", "r-00000000-0000-0000", stdin="a: b\n")

    assert result.returncode == 1
    assert "There is no run" in result.stderr


def test_commands_outside_a_project_explain_what_to_do(tmp_path: Path) -> None:
    result = run_pskill(tmp_path, "list")

    assert result.returncode == 1
    assert "No .pskill folder" in result.stderr


def test_validate_checks_calls_across_skills(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    caller = PLAN_SKILL.replace("id: plan-work", "id: caller").replace(
        "  done:\n    type: end",
        "  done:\n    type: call\n    skill: missing-skill\n    next: finished\n  finished:\n    type: end",
    )
    write_skill(root / ".pskill" / "skills", "caller", caller, PLAN_SKILL_FILES)

    result = run_pskill(root, "validate")

    assert result.returncode == 2
    assert "caller  blocks.done: there is no skill 'missing-skill'" in result.stdout
