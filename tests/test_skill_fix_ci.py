"""Tests for the fix-ci skill's read_checks.py script."""

import json
from typing import Any

import pytest

from tests.skill_scripts import FakeShell, install_shell, load_skill_script, run_main

SKILL = "fix-ci"
PULLS = "gh api GET repos/{owner}/{repo}/pulls/7"
CHECK_RUNS = "gh api GET repos/{owner}/{repo}/commits/origin1/check-runs"
STATUSES = "gh api GET repos/{owner}/{repo}/commits/origin1/statuses"


def pull_request(**changes: Any) -> dict[str, Any]:
    """A pull request as the REST API gives it."""
    return {
        "head": {"ref": "42-fix-save", "sha": "github1", "repo": {"full_name": "o/r"}},
        "base": {"repo": {"full_name": "o/r"}},
        "mergeable": True,
        "draft": False,
        **changes,
    }


def check_run(name: str, status: str = "completed", conclusion: str | None = "success") -> dict[str, Any]:
    return {"name": name, "status": status, "conclusion": conclusion, "details_url": f"https://ci/{name}"}


def checks_shell(check_runs: list[dict[str, Any]], statuses: list[dict[str, Any]] | None = None) -> FakeShell:
    return FakeShell(
        {
            PULLS: json.dumps(pull_request()),
            "git ls-remote origin refs/heads/42-fix-save": "origin1\trefs/heads/42-fix-save",
            CHECK_RUNS: json.dumps({"total_count": len(check_runs), "check_runs": check_runs}),
            STATUSES: json.dumps(statuses or []),
        }
    )


@pytest.mark.parametrize(
    ("check_runs", "statuses", "state", "failed"),
    [
        ([], [], "none", []),
        ([check_run("lint"), check_run("docs", conclusion="skipped")], [], "passed", []),
        ([check_run("lint"), check_run("tests", status="in_progress", conclusion=None)], [], "pending", []),
        ([check_run("lint", conclusion="failure")], [], "failed", ["lint: https://ci/lint"]),
        ([check_run("lint")], [{"id": 1, "context": "deploy", "state": "pending", "target_url": None}], "pending", []),
        (
            [],
            [
                {"id": 1, "context": "deploy", "state": "failure", "target_url": "https://old"},
                {"id": 2, "context": "deploy", "state": "success", "target_url": "https://new"},
                {"id": 3, "context": "audit", "state": "error", "target_url": None},
            ],
            "failed",
            ["audit: "],
        ),
    ],
)
def test_read_once_sums_up_the_check_runs_and_the_newest_status_of_each_context(
    monkeypatch: pytest.MonkeyPatch,
    check_runs: list[dict[str, Any]],
    statuses: list[dict[str, Any]],
    state: str,
    failed: list[str],
) -> None:
    script = load_skill_script(SKILL, "read_checks")
    install_shell(monkeypatch, script, checks_shell(check_runs, statuses))

    result = script.read_once(7)

    assert result["head_sha"] == "origin1"
    assert result["state"] == state
    assert result["failed_checks"] == failed
    assert result["mergeable"] is True and result["draft"] is False


def test_read_once_takes_the_head_of_github_for_a_fork(monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_skill_script(SKILL, "read_checks")
    fork = pull_request(head={"ref": "main", "sha": "fork1", "repo": {"full_name": "fork/r"}})
    shell = install_shell(monkeypatch, script, FakeShell({PULLS: json.dumps(fork)}))

    assert script.read_once(7)["head_sha"] == "fork1"
    assert not shell.ran("git ls-remote")


def test_read_once_takes_the_head_of_github_when_origin_has_no_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_skill_script(SKILL, "read_checks")
    install_shell(monkeypatch, script, FakeShell({PULLS: json.dumps(pull_request())}))

    assert script.read_once(7)["head_sha"] == "github1"


class FakeClock:
    """A clock that moves only when the script sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def time(self) -> float:
        return self.now


def polls(monkeypatch: pytest.MonkeyPatch, script: Any, states: list[str]) -> None:
    """Answer each read with the next state of `states`, then with the last one."""
    answers = iter(states)
    last = {"state": states[-1]}

    def fake_read_once(pr_number: int) -> dict[str, Any]:
        last["state"] = next(answers, last["state"])
        return {"state": last["state"]}

    monkeypatch.setattr(script, "read_once", fake_read_once)


def test_read_checks_polls_until_no_check_is_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_skill_script(SKILL, "read_checks")
    polls(monkeypatch, script, ["pending", "pending", "passed"])
    clock = FakeClock()

    assert script.read_checks(7, 540, clock.sleep, clock.time)["state"] == "passed"
    assert clock.sleeps == [30, 30]


def test_read_checks_returns_a_pending_state_when_the_wait_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_skill_script(SKILL, "read_checks")
    polls(monkeypatch, script, ["pending"])
    clock = FakeClock()

    assert script.read_checks(7, 45, clock.sleep, clock.time)["state"] == "pending"
    assert clock.sleeps == [30, 15]


def test_read_checks_waits_at_most_540_seconds_whatever_the_input_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_skill_script(SKILL, "read_checks")
    polls(monkeypatch, script, ["pending"])
    clock = FakeClock()

    assert script.read_checks(7, 9999, clock.sleep, clock.time)["state"] == "pending"
    assert clock.now == 540


def test_read_checks_waits_at_most_300_seconds_for_a_first_check(monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_skill_script(SKILL, "read_checks")
    polls(monkeypatch, script, ["none"])
    clock = FakeClock()

    assert script.read_checks(7, 9999, clock.sleep, clock.time)["state"] == "none"
    assert clock.now == 300


def test_main_reads_the_pull_request_and_its_wait(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "read_checks")
    install_shell(monkeypatch, script, checks_shell([check_run("lint")]))

    printed = run_main(monkeypatch, capsys, script, {"pr": 7, "wait_s": 0})

    assert printed == {
        "head_sha": "origin1",
        "state": "passed",
        "mergeable": True,
        "draft": False,
        "checks": [{"name": "lint", "state": "passed", "link": "https://ci/lint"}],
        "failed_checks": [],
    }
