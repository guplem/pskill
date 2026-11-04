"""Tests for dev.py, the developer commands of this repository: check, fast, and sync."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import dev

REPOSITORY = Path(__file__).resolve().parent.parent


def test_check_runs_every_ci_step_in_order() -> None:
    names = [" ".join(step[2:]) if step[1] == "-m" else " ".join(step[1:]) for step in dev.STEPS["check"]]

    assert names == [
        "ruff format --check .",
        "ruff check .",
        "mypy",
        "pytest --cov",
        "pskill.py validate",
        "pskill.py test",
    ]
    assert all(step[0] == sys.executable for step in dev.STEPS["check"])


def test_fast_runs_lint_the_tests_that_stop_at_the_first_failure_and_the_skill_tests() -> None:
    assert [step[1:] for step in dev.STEPS["fast"]] == [
        ["-m", "ruff", "check", "."],
        ["-m", "pytest", "-x", "-q"],
        ["pskill.py", "test"],
    ]


def test_run_steps_stops_at_the_first_failing_step(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []

    def fake_call(command: list[str], cwd: Path) -> int:
        ran.append(command)
        return 1 if command == ["b"] else 0

    monkeypatch.setattr(subprocess, "call", fake_call)

    assert dev.run_steps([["a"], ["b"], ["c"]]) == 1
    assert ran == [["a"], ["b"]]


def test_run_steps_returns_0_when_every_step_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "call", lambda command, cwd: 0)

    assert dev.run_steps([["a"], ["b"]]) == 0


def test_every_copy_group_names_existing_files_and_its_source_is_not_a_target() -> None:
    for source, targets in dev.COPIES.items():
        assert (REPOSITORY / source).is_file()
        assert targets and source not in targets
        assert all((REPOSITORY / target).is_file() for target in targets)


def test_sync_copies_rewrites_each_copy_from_its_source(tmp_path: Path) -> None:
    for source, targets in dev.COPIES.items():
        for path in [source, *targets]:
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPOSITORY / path, tmp_path / path)
        (tmp_path / targets[0]).write_text("stale", encoding="utf-8")

    changed = dev.sync_copies(tmp_path)

    assert changed == [targets[0] for targets in dev.COPIES.values()]
    for source, targets in dev.COPIES.items():
        assert all((tmp_path / target).read_bytes() == (tmp_path / source).read_bytes() for target in targets)


def test_main_runs_the_named_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_run_steps(steps: list[list[str]]) -> int:
        calls.append("steps")
        return 0

    def fake_sync_copies(root: Path) -> list[str]:
        calls.append("copies")
        return ["x"]

    monkeypatch.setattr(dev, "run_steps", fake_run_steps)
    monkeypatch.setattr(dev, "sync_copies", fake_sync_copies)

    assert dev.main(["fast"]) == 0
    assert dev.main(["sync"]) == 0
    assert calls == ["steps", "copies", "steps"]


def test_main_refuses_an_unknown_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert dev.main(["deploy"]) == 2
    assert "check, fast, or sync" in capsys.readouterr().err
