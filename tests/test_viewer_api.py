"""Tests for pskill_runner.viewer_api: the answers that both viewers give. test_viewer_server.py covers the rest."""

import json
from pathlib import Path

from pskill_runner.engine import read_run_info, start_run
from pskill_runner.project import Project, find_project
from pskill_runner.viewer_api import answer_get, answer_post, is_write_path
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill


def make_project(tmp_path: Path) -> Project:
    write_skill(tmp_path / ".pskill" / "skills", "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)
    return find_project(tmp_path)


def test_a_path_outside_the_api_has_no_answer(tmp_path: Path) -> None:
    assert answer_get(make_project(tmp_path), "/index.html") is None


def test_a_write_to_an_unknown_path_is_not_found(tmp_path: Path) -> None:
    answer = answer_post(make_project(tmp_path), "/api/skills", b"{}")

    assert answer.status == 404
    assert json.loads(answer.body) == {"error": "There is no such endpoint."}


def test_an_export_names_its_download(tmp_path: Path) -> None:
    answer = answer_get(make_project(tmp_path), "/api/skills/plan-work/export")

    assert answer is not None
    assert (answer.status, answer.content_type, answer.download_name) == (200, "application/zip", "plan-work.zip")


def test_a_run_is_cancelled_then_deleted_and_each_answer_says_so(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")

    cancelled = answer_post(project, f"/api/runs/{run_id}/cancel", b"{}")
    assert cancelled.status == 200
    assert json.loads(cancelled.body)["info"]["status"] == "cancelled"
    assert read_run_info(project, run_id)["status"] == "cancelled"

    deleted = answer_post(project, f"/api/runs/{run_id}/delete", b"{}")
    assert (deleted.status, json.loads(deleted.body)) == (200, {"deleted": run_id})
    assert not (project.runs_folder / run_id).exists()


def test_a_run_action_that_the_runner_refuses_returns_its_reason(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")

    answer = answer_post(project, f"/api/runs/{run_id}/delete", b"{}")

    assert answer.status == 400
    assert "Cancel it first" in json.loads(answer.body)["error"][0]


def test_the_run_actions_are_writes() -> None:
    assert is_write_path("/api/runs/r-1/cancel")
    assert is_write_path("/api/runs/r-1/delete")
    assert not is_write_path("/api/runs/r-1/pause")
