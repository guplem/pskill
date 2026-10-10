"""Tests for pskill_runner.run_waits: `pskill wait`, the alarm that keeps the Stop hook quiet."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pskill_runner.engine import RunError, pause_run, read_run_info, start_run
from pskill_runner.project import Project, find_project
from pskill_runner.run_store import timestamp
from pskill_runner.run_waits import start_wait
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill

START = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def make_project(tmp_path: Path) -> Project:
    write_skill(tmp_path / ".pskill" / "skills", "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)
    return find_project(tmp_path)


def start(project: Project) -> str:
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="claude-code")
    return run_id


def test_a_new_run_has_no_wait(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    info = read_run_info(project, start(project))

    assert (info["wait_reason"], info["wait_started_at"], info["wait_until"], info["waits_since"]) == (
        None,
        None,
        None,
        None,
    )


def test_a_wait_records_its_reason_its_start_and_its_alarm(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    start_wait(project, run_id, "the CI checks", START)

    info = read_run_info(project, run_id)
    assert info["wait_reason"] == "the CI checks"
    assert info["wait_started_at"] == timestamp(START)
    assert info["wait_until"] == timestamp(START + timedelta(minutes=20))
    assert info["waits_since"] == timestamp(START)


def test_a_second_wait_keeps_the_start_of_the_first_one(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    start_wait(project, run_id, "the CI checks", START)

    start_wait(project, run_id, "the CI checks", START + timedelta(minutes=20))

    info = read_run_info(project, run_id)
    assert info["wait_started_at"] == timestamp(START + timedelta(minutes=20))
    assert info["waits_since"] == timestamp(START)


def test_a_wait_is_refused_after_max_wait_minutes_with_nothing_new(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    start_wait(project, run_id, "the CI checks", START)

    with pytest.raises(RunError, match="120 minutes with nothing new"):
        start_wait(project, run_id, "the CI checks", START + timedelta(minutes=120))

    info = read_run_info(project, run_id)
    assert info["wait_started_at"] == timestamp(START)
    assert info["wait_reason"] == "the CI checks"


def test_a_wait_is_refused_on_a_run_that_is_not_active(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    pause_run(project, run_id)

    with pytest.raises(RunError, match="is paused, so it cannot wait"):
        start_wait(project, run_id, "the CI checks", START)
