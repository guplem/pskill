"""Tests for pskill_runner.run_waits: `pskill wait`, the alarm that keeps the Stop hook quiet."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pskill_runner import run_waits
from pskill_runner.engine import (
    RunError,
    cancel_run,
    current_packet,
    delete_run,
    pause_run,
    read_run_info,
    resume_run,
    run_folder,
    start_run,
    submit_answer,
)
from pskill_runner.hooks import stop_hook_reason
from pskill_runner.project import Project, find_project
from pskill_runner.run_records import RunInfo
from pskill_runner.run_store import timestamp
from pskill_runner.run_waits import start_wait, wait_for_run_change
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill

START = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


class FakeClock:
    """A clock that moves only when the wait sleeps. `on_sleep` changes the run, as another command would."""

    def __init__(self, on_sleep: Callable[[], object] | None = None) -> None:
        self.now = START
        self.sleeps: list[float] = []
        self.on_sleep = on_sleep

    def time(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)
        if self.on_sleep is not None:
            self.on_sleep()


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


def test_a_wait_with_nothing_new_ends_at_its_alarm_with_one_line(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    clock = FakeClock()

    text = wait_for_run_change(project, run_id, "the CI checks", clock.sleep, clock.time)

    assert text == (
        "20 minutes passed and nothing changed. If you still wait on the CI checks, run the wait again. "
        f"Else continue the run: run `uv run .pskill/pskill.py current {run_id}`.\n"
    )
    assert clock.now == START + timedelta(minutes=20)
    assert max(clock.sleeps) <= 5


def test_a_pause_ends_the_wait_at_once(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    clock = FakeClock(on_sleep=lambda: pause_run(project, run_id))

    text = wait_for_run_change(project, run_id, "the CI checks", clock.sleep, clock.time)

    assert text == f"Run {run_id} is now paused.\n"
    assert len(clock.sleeps) == 1


def test_a_submit_ends_the_wait_at_once(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    answer = "status: unknown\n"  # a rejected answer changes the run too
    clock = FakeClock(on_sleep=lambda: submit_answer(project, run_id, answer))

    text = wait_for_run_change(project, run_id, "the CI checks", clock.sleep, clock.time)

    assert text == f"Run {run_id} changed. Continue it: run `uv run .pskill/pskill.py current {run_id}`.\n"
    assert len(clock.sleeps) == 1


def wait_fields(project: Project, run_id: str) -> list[str | None]:
    info = read_run_info(project, run_id)
    return [info["wait_reason"], info["wait_started_at"], info["wait_until"], info["waits_since"]]


def test_a_submit_clears_the_wait(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    start_wait(project, run_id, "the CI checks", START)

    submit_answer(project, run_id, "status: unknown\n")

    assert wait_fields(project, run_id) == [None, None, None, None]


def test_a_resume_clears_the_wait(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    start_wait(project, run_id, "the CI checks", START)
    pause_run(project, run_id)

    resume_run(project, run_id)

    assert wait_fields(project, run_id) == [None, None, None, None]


def test_a_save_with_nothing_new_does_not_end_the_wait(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    clock = FakeClock(on_sleep=lambda: current_packet(project, run_id))  # `current` saves run.json

    text = wait_for_run_change(project, run_id, "the CI checks", clock.sleep, clock.time)

    assert text.startswith("20 minutes passed and nothing changed.")


def test_after_a_wait_ends_on_a_submit_the_stop_hook_counts_again(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)
    clock = FakeClock(on_sleep=lambda: submit_answer(project, run_id, "status: unknown"))

    wait_for_run_change(project, run_id, "the CI checks", clock.sleep, clock.time)

    assert stop_hook_reason(project, "claude-code") is not None
    assert read_run_info(project, run_id)["stop_blocks"] == 1


def test_each_poll_reads_the_run_under_its_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On Windows, a read during an `os.replace` of `run.json` fails both sides, so a poll takes the lock."""
    project = make_project(tmp_path)
    run_id = start(project)
    lock_file = run_folder(project, run_id) / ".lock"
    locked_reads: list[bool] = []

    def read_and_note_the_lock(project: Project, run_id: str) -> RunInfo:
        locked_reads.append(lock_file.exists())
        return read_run_info(project, run_id)

    monkeypatch.setattr(run_waits, "read_run_info", read_and_note_the_lock)
    clock = FakeClock()

    wait_for_run_change(project, run_id, "the CI checks", clock.sleep, clock.time)

    assert len(locked_reads) > 1
    assert all(locked_reads)


def test_a_run_deleted_during_the_wait_ends_it(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id = start(project)

    def cancel_and_delete() -> None:
        cancel_run(project, run_id)
        delete_run(project, run_id)

    clock = FakeClock(on_sleep=cancel_and_delete)

    text = wait_for_run_change(project, run_id, "the CI checks", clock.sleep, clock.time)

    assert text == f"Run {run_id} is deleted.\n"
