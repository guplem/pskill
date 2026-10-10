"""Tests for the create-issue skill: its scripts, and that every GitHub call targets the repository of the run."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pskill_runner.skill_loader import load_skill
from pskill_runner.skill_model import ScriptBlock
from tests.skill_scripts import FakeShell, install_shell, load_skill_script, run_main

SKILL = "create-issue"
SKILL_FOLDER = Path(__file__).resolve().parent.parent / ".pskill" / "skills" / SKILL
RESOLVED_REPOSITORY = "{{ steps.resolve_repo.json.full_name }}"


def script_blocks() -> dict[str, ScriptBlock]:
    skill = load_skill(SKILL_FOLDER)
    return {block_id: block for block_id, block in skill.blocks.items() if isinstance(block, ScriptBlock)}


def test_the_run_first_resolves_the_repository_from_the_repo_input() -> None:
    skill = load_skill(SKILL_FOLDER)

    assert [edge.to for edge in skill.entry] == ["resolve_repo"]
    assert script_blocks()["resolve_repo"].run == [
        "gh",
        "api",
        "repos/{{ inputs.repo or '{owner}/{repo}' }}",
        "--jq",
        "{full_name}",
    ]


def test_every_other_github_call_names_the_resolved_repository() -> None:
    blocks = {block_id: block for block_id, block in script_blocks().items() if block_id != "resolve_repo"}

    assert sorted(blocks) == ["create", "ensure_label", "label_issue", "search_duplicates"]
    for block_id in ["create", "label_issue"]:
        assert blocks[block_id].run[:2] == ["gh", "api"], block_id
        assert str(blocks[block_id].run[2]).startswith(f"repos/{RESOLVED_REPOSITORY}/issues"), block_id
    for block_id in ["search_duplicates", "ensure_label"]:
        assert blocks[block_id].input["repo"] == RESOLVED_REPOSITORY, block_id


def issue(number: int, title: str, body: str | None = "", **changes: Any) -> dict[str, Any]:
    url = f"https://github.com/o/r/issues/{number}"
    return {"number": number, "title": title, "body": body, "state": "open", "html_url": url, **changes}


def test_search_issues_keeps_the_issues_with_the_most_search_words(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "search_issues")
    issues = [
        issue(1, "Dark theme", "For the VIEWER."),
        issue(2, "Viewer crash", None, state="closed"),
        issue(3, "Unrelated"),
        issue(4, "Dark viewer", pull_request={"url": "u"}),
    ]
    shell = install_shell(monkeypatch, script, FakeShell({"gh api GET repos/o/r/issues?state=all": json.dumps(issues)}))

    printed = run_main(monkeypatch, capsys, script, {"repo": "o/r", "terms": ["dark", "viewer"]})

    assert printed == [
        {"number": 1, "title": "Dark theme", "state": "open", "url": "https://github.com/o/r/issues/1"},
        {"number": 2, "title": "Viewer crash", "state": "closed", "url": "https://github.com/o/r/issues/2"},
    ]
    assert shell.ran("gh api GET repos/o/r/issues?state=all")


def test_search_issues_reads_at_most_ten_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_skill_script(SKILL, "search_issues")
    stops: list[bool] = []

    def fake_gh_api_pages(path: str, stop: Any) -> list[dict[str, Any]]:
        stops.extend(stop([]) for _ in range(10))
        return []

    monkeypatch.setattr(script, "gh_api_pages", fake_gh_api_pages)

    assert script.matching_issues("o/r", ["x"]) == []
    assert stops == [False] * 9 + [True]


def label_result(returncode: int, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, "{}", stderr)


@pytest.mark.parametrize(
    "result",
    [label_result(0), label_result(1, '{"errors":[{"code":"already_exists"}]} (HTTP 422)')],
)
def test_ensure_label_creates_the_label_or_keeps_the_one_that_exists(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], result: subprocess.CompletedProcess[str]
) -> None:
    script = load_skill_script(SKILL, "ensure_label")
    calls: list[Any] = []

    def fake_gh_api_call(path: str, method: str, body: Any) -> subprocess.CompletedProcess[str]:
        calls.append((path, method, body))
        return result

    monkeypatch.setattr(script, "gh_api_call", fake_gh_api_call)

    printed = run_main(monkeypatch, capsys, script, {"repo": "o/r"})

    assert printed == {"label": "waiting-for-human-check"}
    assert calls == [
        (
            "repos/o/r/labels",
            "POST",
            {
                "name": "waiting-for-human-check",
                "color": "D93F0B",
                "description": "No human has verified this yet: direct AI output",
            },
        )
    ]


def test_ensure_label_stops_on_another_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_skill_script(SKILL, "ensure_label")
    monkeypatch.setattr(script, "gh_api_call", lambda path, method, body: label_result(1, "HTTP 403: Forbidden"))

    with pytest.raises(SystemExit, match="HTTP 403: Forbidden"):
        run_main(monkeypatch, capsys, script, {"repo": "o/r"})
