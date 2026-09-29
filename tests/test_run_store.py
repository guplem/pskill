"""Tests for pskill_runner.run_store."""

import json
import os
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pskill_runner.run_store import (
    append_event,
    copy_skill_snapshot,
    folder_hash,
    new_run_id,
    read_events,
    read_json,
    run_lock,
    write_json_atomic,
)
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill


def test_new_run_id_has_the_date_time_and_a_random_part() -> None:
    run_id = new_run_id(datetime(2026, 9, 27, 14, 32, tzinfo=UTC))

    assert re.fullmatch(r"r-20260927-1432-[0-9a-f]{4}", run_id)


def test_write_json_atomic_round_trips_and_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "run.json"

    write_json_atomic(path, {"status": "active", "count": 2})

    assert read_json(path) == {"status": "active", "count": 2}
    assert [child.name for child in tmp_path.iterdir()] == ["run.json"]


def test_append_event_adds_one_numbered_line_per_event(tmp_path: Path) -> None:
    append_event(tmp_path, "run_started", frame="plan-work", skill_id="plan-work")
    append_event(tmp_path, "block_started", frame="plan-work", block="create_plan")

    events = read_events(tmp_path)
    assert [event["seq"] for event in events] == [1, 2]
    assert events[1]["type"] == "block_started"
    assert events[1]["block"] == "create_plan"
    assert events[1]["frame"] == "plan-work"
    assert events[0]["ts"].endswith("Z")
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["skill_id"] == "plan-work"


def test_copy_skill_snapshot_copies_the_whole_skill_folder(tmp_path: Path) -> None:
    skill_folder = write_skill(tmp_path / "skills", "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)
    run_folder = tmp_path / "runs" / "r-1"

    copy_skill_snapshot(skill_folder, run_folder)

    assert (run_folder / "skills" / "plan-work" / "instructions" / "approve_plan.md").is_file()


def test_folder_hash_changes_only_when_the_content_changes(tmp_path: Path) -> None:
    folder = write_skill(tmp_path, "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)
    first_hash = folder_hash(folder)

    assert folder_hash(folder) == first_hash
    (folder / "instructions" / "approve_plan.md").write_text("Changed.", encoding="utf-8")
    assert folder_hash(folder) != first_hash
    assert first_hash.startswith("sha256:")


def test_run_lock_lets_one_holder_in_at_a_time(tmp_path: Path) -> None:
    order: list[str] = []

    def hold(name: str) -> None:
        with run_lock(tmp_path):
            order.append(f"{name} in")
            time.sleep(0.1)
            order.append(f"{name} out")

    threads = [threading.Thread(target=hold, args=(name,)) for name in ("a", "b", "c")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(order) == 6
    assert all(order[index].endswith("in") and order[index + 1].endswith("out") for index in range(0, 6, 2))
    assert not (tmp_path / ".lock").exists()


def test_run_lock_breaks_a_stale_lock(tmp_path: Path) -> None:
    stale_lock = tmp_path / ".lock"
    stale_lock.write_text("", encoding="utf-8")
    old_time = time.time() - 120
    os.utime(stale_lock, (old_time, old_time))

    with run_lock(tmp_path):
        assert stale_lock.exists()

    assert not stale_lock.exists()


def test_run_lock_waits_while_windows_still_removes_the_old_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = os.open
    calls: list[str] = []

    def open_once_denied(path: str, flags: int, *arguments: int) -> int:
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError(13, "Permission denied")  # Windows, while a deleted file is still pending
        return real_open(path, flags, *arguments)

    monkeypatch.setattr(os, "open", open_once_denied)

    with run_lock(tmp_path):
        assert (tmp_path / ".lock").exists()

    assert len(calls) == 2
