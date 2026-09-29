"""Tests for pskill_runner.viewer_server: the local JSON API and the static viewer files."""

import io
import json
import threading
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from pskill_runner.engine import start_run
from pskill_runner.project import Project, find_project
from pskill_runner.viewer_server import make_server
from tests.skill_files import PLAN_SKILL, PLAN_SKILL_FILES, write_skill


@pytest.fixture
def project(tmp_path: Path) -> Project:
    write_skill(tmp_path / ".pskill" / "skills", "plan-work", PLAN_SKILL, PLAN_SKILL_FILES)
    return find_project(tmp_path)


@pytest.fixture
def viewer_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "viewer"
    folder.mkdir()
    (folder / "index.html").write_text("<!doctype html><title>pskill</title>", encoding="utf-8")
    (folder / "app.js").write_text("console.log('pskill');", encoding="utf-8")
    return folder


@pytest.fixture
def server(project: Project, viewer_folder: Path) -> Iterator[ThreadingHTTPServer]:
    running_server = make_server(project, viewer_folder, port=0)
    thread = threading.Thread(target=running_server.serve_forever, daemon=True)
    thread.start()
    yield running_server
    running_server.shutdown()
    running_server.server_close()


def get(server: ThreadingHTTPServer, path: str) -> tuple[int, str, bytes]:
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, response.headers["Content-Type"], response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers["Content-Type"], error.read()


def test_the_server_listens_only_on_the_local_machine(server: ThreadingHTTPServer) -> None:
    assert server.server_address[0] == "127.0.0.1"


def test_the_runs_endpoint_returns_the_overview(server: ThreadingHTTPServer, project: Project) -> None:
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")

    status, content_type, body = get(server, "/api/runs")

    assert status == 200
    assert content_type.startswith("application/json")
    assert [row["run_id"] for row in json.loads(body)["runs"]] == [run_id]


def test_the_run_endpoint_returns_the_detail(server: ThreadingHTTPServer, project: Project) -> None:
    run_id, _ = start_run(project, "plan-work", {"topic": "x"}, mode="interactive", harness="generic")

    status, _, body = get(server, f"/api/runs/{run_id}")

    assert status == 200
    assert json.loads(body)["timeline"][0]["block"] == "create_plan"


def test_an_unknown_run_is_a_404(server: ThreadingHTTPServer) -> None:
    status, _, body = get(server, "/api/runs/r-00000000-0000-0000")

    assert status == 404
    assert "no run" in json.loads(body)["error"]


def test_the_viewer_files_are_served(server: ThreadingHTTPServer) -> None:
    index_status, index_type, index_body = get(server, "/")
    script_status, script_type, _ = get(server, "/app.js")

    assert (index_status, index_type.split(";")[0]) == (200, "text/html")
    assert b"<title>pskill</title>" in index_body
    assert (script_status, script_type.split(";")[0]) == (200, "text/javascript")


def test_paths_outside_the_viewer_folder_are_refused(server: ThreadingHTTPServer) -> None:
    assert get(server, "/../../.pskill/skills/plan-work/skill.yaml")[0] == 404
    assert get(server, "/missing.css")[0] == 404


def test_the_skills_endpoint_lists_every_skill(server: ThreadingHTTPServer) -> None:
    status, content_type, body = get(server, "/api/skills")

    assert (status, content_type) == (200, "application/json; charset=utf-8")
    assert [skill["skill_id"] for skill in json.loads(body)["skills"]] == ["plan-work"]


def test_the_skill_endpoint_returns_one_skill(server: ThreadingHTTPServer) -> None:
    status, _, body = get(server, "/api/skills/plan-work")

    assert status == 200
    assert json.loads(body)["skill"]["id"] == "plan-work"


def test_an_unknown_skill_is_not_found(server: ThreadingHTTPServer) -> None:
    status, _, body = get(server, "/api/skills/missing")

    assert status == 404
    assert json.loads(body) == {"error": "There is no skill with this id."}


def test_the_export_endpoint_downloads_the_skill_as_a_zip(server: ThreadingHTTPServer) -> None:
    url = f"http://127.0.0.1:{server.server_address[1]}/api/skills/plan-work/export"
    with urllib.request.urlopen(url, timeout=10) as response:
        headers = response.headers
        body = response.read()

    assert headers["Content-Type"] == "application/zip"
    assert headers["Content-Disposition"] == 'attachment; filename="plan-work.zip"'
    assert zipfile.ZipFile(io.BytesIO(body)).namelist() == ["plan-work/SKILL.md"]


def test_the_export_of_an_unknown_skill_is_not_found(server: ThreadingHTTPServer) -> None:
    status, _, body = get(server, "/api/skills/missing/export")

    assert status == 404
    assert "missing" in json.loads(body)["error"]
