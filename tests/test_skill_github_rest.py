"""Tests for github_rest.py, the REST helper that every example skill that calls GitHub has a copy of."""

import subprocess
from typing import Any

import pytest

from tests.skill_scripts import SKILLS_FOLDER, load_skill_script

# Keep this list equal to the header of every copy.
GITHUB_REST_READERS = [
    "checkout-pr",
    "implement-issue",
    "resolve-pr-feedback",
    "review-head-check",
    "review-pr",
]


def test_every_reader_has_the_same_github_rest_helper() -> None:
    copies = {
        reader: (SKILLS_FOLDER / reader / "scripts" / "github_rest.py").read_bytes() for reader in GITHUB_REST_READERS
    }

    assert len(set(copies.values())) == 1, f"The copies differ: {sorted(copies)}. Change all of them together."


def test_the_reader_list_names_every_copy() -> None:
    found = sorted(path.parents[1].name for path in SKILLS_FOLDER.glob("*/scripts/github_rest.py"))

    assert found == GITHUB_REST_READERS, "Add the new copy to GITHUB_REST_READERS and to the header of every copy."


def test_the_header_names_every_copy() -> None:
    header = (SKILLS_FOLDER / "implement-issue" / "scripts" / "github_rest.py").read_text(encoding="utf-8")

    assert all(reader in header for reader in GITHUB_REST_READERS)


def fake_gh(monkeypatch: pytest.MonkeyPatch, returncode: int = 0, stdout: str = "", stderr: str = "") -> list[Any]:
    """Replace subprocess.run in the helper. Return the list that records each call as (command, input)."""
    calls: list[Any] = []

    def fake_run(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, options.get("input")))
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_gh_api_call_sends_a_body_as_json_on_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = load_skill_script("implement-issue", "github_rest")
    calls = fake_gh(monkeypatch, stdout="{}")

    helper.gh_api_call("repos/{owner}/{repo}/pulls", "POST", {"draft": True})

    assert calls == [
        (["gh", "api", "--method", "POST", "repos/{owner}/{repo}/pulls", "--input", "-"], '{"draft": true}')
    ]


def test_gh_api_call_without_a_body_sends_no_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = load_skill_script("implement-issue", "github_rest")
    calls = fake_gh(monkeypatch)

    helper.gh_api_call("user")

    assert calls == [(["gh", "api", "--method", "GET", "user"], None)]


def test_gh_api_parses_the_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = load_skill_script("implement-issue", "github_rest")
    fake_gh(monkeypatch, stdout='{"login": "ana"}')

    assert helper.gh_api("user") == {"login": "ana"}


def test_gh_api_gives_none_for_an_empty_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = load_skill_script("implement-issue", "github_rest")
    fake_gh(monkeypatch, stdout="  \n")

    assert helper.gh_api("repos/{owner}/{repo}/issues/1/assignees", "POST") is None


def test_gh_api_exits_with_the_error_of_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = load_skill_script("implement-issue", "github_rest")
    fake_gh(monkeypatch, returncode=1, stderr="HTTP 404: Not Found\n")

    with pytest.raises(SystemExit, match="`gh api --method GET user` failed: HTTP 404: Not Found"):
        helper.gh_api("user")


def pages_of(monkeypatch: pytest.MonkeyPatch, helper: Any, pages: list[Any]) -> list[str]:
    """Answer each page read with the next reply of `pages`. Return the list of the paths read."""
    paths: list[str] = []

    def fake_gh_api(path: str) -> Any:
        paths.append(path)
        return pages[len(paths) - 1]

    monkeypatch.setattr(helper, "gh_api", fake_gh_api)
    return paths


def numbered(start: int, count: int) -> list[dict[str, int]]:
    return [{"number": number} for number in range(start, start + count)]


def test_gh_api_pages_reads_until_a_short_page(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = load_skill_script("implement-issue", "github_rest")
    paths = pages_of(monkeypatch, helper, [numbered(1, 100), numbered(101, 2)])

    items = helper.gh_api_pages("repos/{owner}/{repo}/issues?state=all")

    assert len(items) == 102
    assert paths == [
        "repos/{owner}/{repo}/issues?state=all&per_page=100&page=1",
        "repos/{owner}/{repo}/issues?state=all&per_page=100&page=2",
    ]


def test_gh_api_pages_reads_the_list_inside_an_object_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = load_skill_script("implement-issue", "github_rest")
    paths = pages_of(monkeypatch, helper, [{"check_runs": [{"id": 1}], "total_count": 1}])

    assert helper.gh_api_pages("repos/{owner}/{repo}/commits/abc/check-runs", "check_runs") == [{"id": 1}]
    assert paths == ["repos/{owner}/{repo}/commits/abc/check-runs?per_page=100&page=1"]


def test_gh_api_pages_stops_early_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = load_skill_script("implement-issue", "github_rest")
    pages_of(monkeypatch, helper, [numbered(1, 100), numbered(101, 100)])

    items = helper.gh_api_pages("repos/{owner}/{repo}/pulls", stop=lambda page: page[-1]["number"] >= 100)

    assert len(items) == 100


def test_gh_api_pages_gives_an_item_that_moved_to_the_next_page_once(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = load_skill_script("implement-issue", "github_rest")
    pages_of(monkeypatch, helper, [numbered(1, 100), numbered(100, 1)])

    assert len(helper.gh_api_pages("repos/{owner}/{repo}/issues")) == 100


def test_gh_api_pages_keeps_items_that_have_no_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = load_skill_script("implement-issue", "github_rest")
    pages_of(monkeypatch, helper, [["a", "a"]])

    assert helper.gh_api_pages("repos/{owner}/{repo}/topics") == ["a", "a"]


def test_gh_api_pages_exits_after_the_page_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = load_skill_script("implement-issue", "github_rest")
    monkeypatch.setattr(helper, "MAX_PAGES", 2)
    pages_of(monkeypatch, helper, [numbered(1, 100), numbered(101, 100)])

    with pytest.raises(SystemExit, match="has more than 2 pages of 100 items"):
        helper.gh_api_pages("repos/{owner}/{repo}/issues")


def pull_request(head_repo: str | None, base_repo: str = "ana/app") -> dict[str, Any]:
    head = {"repo": None if head_repo is None else {"full_name": head_repo}}
    return {"head": head, "base": {"repo": {"full_name": base_repo}}}


@pytest.mark.parametrize(
    ("head_repo", "cross"),
    [("ana/app", False), ("bob/app", True), (None, True)],
)
def test_is_cross_repository(head_repo: str | None, cross: bool) -> None:
    helper = load_skill_script("implement-issue", "github_rest")

    assert helper.is_cross_repository(pull_request(head_repo)) is cross
