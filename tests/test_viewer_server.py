"""Tests for pskill_runner.viewer_server: the local JSON API and the static viewer files."""

import http.client
import io
import json
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from pskill_runner import __version__, viewer_server
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


def test_the_version_endpoint_returns_the_running_version(server: ThreadingHTTPServer, project: Project) -> None:
    status, _, body = get(server, "/api/version")

    assert status == 200
    assert json.loads(body) == {"version": __version__, "project": project.root.name}


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


def test_a_skill_named_export_gets_its_detail_not_a_download(tmp_path: Path) -> None:
    write_skill(
        tmp_path / ".pskill" / "skills", "export", PLAN_SKILL.replace("id: plan-work", "id: export"), PLAN_SKILL_FILES
    )
    viewer_folder = tmp_path / "viewer"
    viewer_folder.mkdir()
    running_server = make_server(find_project(tmp_path), viewer_folder, port=0)
    thread = threading.Thread(target=running_server.serve_forever, daemon=True)
    thread.start()
    try:
        status, content_type, body = get(running_server, "/api/skills/export")
    finally:
        running_server.shutdown()
        running_server.server_close()

    assert (status, content_type) == (200, "application/json; charset=utf-8")
    assert json.loads(body)["skill"]["id"] == "export"


def post(
    server: ThreadingHTTPServer, path: str, body: dict[str, Any], headers: dict[str, str] | None = None
) -> tuple[int, Any]:
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


DESCRIPTION_CHANGE = {"action": "update", "block": "done", "values": {"description": "The happy end."}}


def test_the_edit_endpoint_saves_a_change_and_returns_the_new_detail(
    server: ThreadingHTTPServer, project: Project
) -> None:
    status, body = post(server, "/api/skills/plan-work/edit", DESCRIPTION_CHANGE)

    assert status == 200
    assert body["blocks"]["done"]["description"] == "The happy end."
    assert "description: The happy end." in (project.skills_folder / "plan-work" / "skill.yaml").read_text(
        encoding="utf-8"
    )


def test_an_edit_with_a_problem_returns_the_problems(server: ThreadingHTTPServer) -> None:
    status, body = post(server, "/api/skills/plan-work/edit", {"action": "delete", "block": "done"})

    assert status == 400
    assert "approve_plan" in body["error"][0]


@pytest.mark.parametrize(
    "headers",
    [{"Origin": "https://example.com"}, {"Host": "evil.example:7777"}, {"Content-Type": "text/plain"}],
)
def test_an_edit_from_another_page_is_refused(
    server: ThreadingHTTPServer, project: Project, headers: dict[str, str]
) -> None:
    before = (project.skills_folder / "plan-work" / "skill.yaml").read_text(encoding="utf-8")

    status, _ = post(server, "/api/skills/plan-work/edit", DESCRIPTION_CHANGE, headers)

    assert status == 403
    assert (project.skills_folder / "plan-work" / "skill.yaml").read_text(encoding="utf-8") == before


@pytest.mark.parametrize("length", ["abc", "-1"])
def test_an_edit_with_a_bad_length_is_refused(server: ThreadingHTTPServer, length: str) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    connection.putrequest("POST", "/api/skills/plan-work/edit")
    connection.putheader("Content-Type", "application/json")
    connection.putheader("Content-Length", length)
    connection.endheaders()

    response = connection.getresponse()

    assert response.status == 403
    connection.close()


def test_a_refused_edit_with_a_late_body_still_gets_its_answer(server: ThreadingHTTPServer) -> None:
    """The server reads the body before it answers. Else, on Windows, the late body resets the connection."""
    body = json.dumps(DESCRIPTION_CHANGE).encode("utf-8")
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    connection.putrequest("POST", "/api/skills/plan-work/edit", skip_host=True)
    connection.putheader("Host", "evil.example:7777")
    connection.putheader("Content-Type", "application/json")
    connection.putheader("Content-Length", str(len(body)))
    connection.endheaders()
    time.sleep(0.2)
    connection.send(body)
    time.sleep(0.2)

    response = connection.getresponse()

    assert response.status == 403
    connection.close()


def write_agent(project: Project, name: str, text: str) -> None:
    project.agents_folder.mkdir(parents=True, exist_ok=True)
    (project.agents_folder / f"{name}.md").write_text(text, encoding="utf-8")


def test_the_agents_endpoint_lists_every_agent(server: ThreadingHTTPServer, project: Project) -> None:
    write_agent(project, "checker", "You check facts.\n")

    status, _, body = get(server, "/api/agents")

    assert status == 200
    assert json.loads(body)["agents"][0]["name"] == "checker"


def test_the_agent_endpoint_returns_one_agent(server: ThreadingHTTPServer, project: Project) -> None:
    write_agent(project, "checker", "You check facts.\n")

    status, _, body = get(server, "/api/agents/checker")

    assert status == 200
    assert json.loads(body)["text"] == "You check facts.\n"


def test_an_unknown_agent_is_not_found(server: ThreadingHTTPServer) -> None:
    status, _, _ = get(server, "/api/agents/missing")

    assert status == 404


def test_the_agent_edit_endpoint_saves_the_text_and_returns_the_new_detail(
    server: ThreadingHTTPServer, project: Project
) -> None:
    write_agent(project, "checker", "You check facts.\n")

    status, body = post(server, "/api/agents/checker/edit", {"text": "You check every fact.\n"})

    assert status == 200
    assert body["text"] == "You check every fact.\n"
    assert (project.agents_folder / "checker.md").read_text(encoding="utf-8") == "You check every fact.\n"


def test_an_edit_of_an_unknown_agent_is_refused(server: ThreadingHTTPServer) -> None:
    status, body = post(server, "/api/agents/missing/edit", {"text": "x"})

    assert status == 400
    assert "no agent" in body["error"][0]


def test_an_agent_edit_from_another_page_is_refused(server: ThreadingHTTPServer, project: Project) -> None:
    write_agent(project, "checker", "You check facts.\n")

    status, _ = post(server, "/api/agents/checker/edit", {"text": "x"}, {"Origin": "https://example.com"})

    assert status == 403
    assert (project.agents_folder / "checker.md").read_text(encoding="utf-8") == "You check facts.\n"


def test_a_post_to_an_unknown_path_is_not_found(server: ThreadingHTTPServer) -> None:
    status, body = post(server, "/api/skills/plan-work/rename", DESCRIPTION_CHANGE)

    assert status == 404
    assert body == {"error": "There is no such endpoint."}


def test_an_edit_without_an_action_is_a_bad_request(server: ThreadingHTTPServer, project: Project) -> None:
    before = (project.skills_folder / "plan-work" / "skill.yaml").read_text(encoding="utf-8")

    status, body = post(server, "/api/skills/plan-work/edit", {"block": "done"})

    assert status == 400
    assert body == {"error": ["The request is not a valid edit: 'action'"]}
    assert (project.skills_folder / "plan-work" / "skill.yaml").read_text(encoding="utf-8") == before


def test_the_edit_endpoint_adds_a_block(server: ThreadingHTTPServer) -> None:
    status, body = post(server, "/api/skills/plan-work/edit", {"action": "add", "block": "extra", "type": "end"})

    assert status == 200
    assert body["blocks"]["extra"]["type"] == "end"


def test_an_edit_with_an_unknown_action_is_refused(server: ThreadingHTTPServer) -> None:
    status, body = post(server, "/api/skills/plan-work/edit", {"action": "rename", "block": "done"})

    assert status == 400
    assert body == {"error": ["Unknown action 'rename': use update, add, or delete."]}


def record_servers(monkeypatch: pytest.MonkeyPatch) -> list[ThreadingHTTPServer]:
    """Make `serve_viewer` use a real server on a free port, and keep it for the test to look at."""
    servers: list[ThreadingHTTPServer] = []

    def make_recorded_server(project: Project, viewer_folder: Path, port: int) -> ThreadingHTTPServer:
        servers.append(make_server(project, viewer_folder, 0))
        return servers[-1]

    monkeypatch.setattr(viewer_server, "make_server", make_recorded_server)
    return servers


def test_the_viewer_opens_the_browser_and_stops_on_ctrl_c(
    project: Project, viewer_folder: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    servers = record_servers(monkeypatch)
    opened_urls: list[str] = []
    monkeypatch.setattr(webbrowser, "open", opened_urls.append)

    def press_ctrl_c(self: ThreadingHTTPServer) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(ThreadingHTTPServer, "serve_forever", press_ctrl_c)

    viewer_server.serve_viewer(project, viewer_folder, port=7777, open_browser=True)

    url = f"http://127.0.0.1:{servers[0].server_address[1]}/"
    assert opened_urls == [url]
    assert capsys.readouterr().out == f"pskill viewer: {url} (press Ctrl+C to stop)\n"
    assert servers[0].socket.fileno() == -1  # the server closed its socket


def test_the_viewer_without_a_browser_opens_nothing_and_closes_its_server(
    project: Project, viewer_folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    servers = record_servers(monkeypatch)
    opened_urls: list[str] = []
    monkeypatch.setattr(webbrowser, "open", opened_urls.append)
    monkeypatch.setattr(ThreadingHTTPServer, "serve_forever", lambda self: None)

    viewer_server.serve_viewer(project, viewer_folder, port=7777, open_browser=False)

    assert opened_urls == []
    assert servers[0].socket.fileno() == -1
