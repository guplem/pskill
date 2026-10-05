"""The viewer's API as plain functions: a request path in, an answer out (SPEC.md section 14).

Both viewers answer with this module: the local server (`viewer_server.py`), and the hosted viewer on GitHub
Pages, which runs it in the browser with Pyodide (`viewer/hosted.js`). The local server checks first that a
write comes from its own page; the hosted viewer has no server, so nothing else can call it.
"""

import json
import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from pskill_runner import __version__
from pskill_runner.agent_view import AgentEditError, agent_detail, agents_overview, save_agent
from pskill_runner.engine import RunError, cancel_run, delete_run
from pskill_runner.project import Project
from pskill_runner.skill_editor import EditError, add_block, delete_block, update_block
from pskill_runner.skill_export import ExportError, export_zip
from pskill_runner.skill_view import skill_detail, skills_overview
from pskill_runner.viewer_data import run_detail, runs_overview

EXPORT_PATH = re.compile(r"/api/skills/([^/]+)/export")
EDIT_PATH = re.compile(r"/api/skills/([^/]+)/edit")
AGENT_EDIT_PATH = re.compile(r"/api/agents/([^/]+)/edit")
RUN_ACTION_PATH = re.compile(r"/api/runs/([^/]+)/(cancel|delete)")
JSON_TYPE = "application/json; charset=utf-8"


@dataclass(frozen=True)
class Answer:
    """An answer to one request. A download has the name of its file."""

    status: int
    body: bytes
    content_type: str = JSON_TYPE
    download_name: str | None = None


def json_answer(status: int, data: Any) -> Answer:
    return Answer(status, json.dumps(data).encode("utf-8"))


def answer_get(project: Project, path: str) -> Answer | None:
    """The answer to a GET of an API path, or None when the path is not an API path (a viewer file)."""
    if path == "/api/version":
        return json_answer(HTTPStatus.OK, {"version": __version__, "project": project.root.name})
    if path == "/api/runs":
        return json_answer(HTTPStatus.OK, runs_overview(project))
    if path.startswith("/api/runs/"):
        detail = run_detail(project, path.removeprefix("/api/runs/"))
        return found(detail, "There is no run with this id.")
    if export_match := EXPORT_PATH.fullmatch(path):
        return export_answer(project, export_match[1])
    if path == "/api/skills":
        return json_answer(HTTPStatus.OK, skills_overview(project))
    if path.startswith("/api/skills/"):
        return found(skill_detail(project, path.removeprefix("/api/skills/")), "There is no skill with this id.")
    if path == "/api/agents":
        return json_answer(HTTPStatus.OK, agents_overview(project))
    if path.startswith("/api/agents/"):
        return found(agent_detail(project, path.removeprefix("/api/agents/")), "There is no agent with this name.")
    return None


def found(data: dict[str, Any] | None, missing: str) -> Answer:
    return json_answer(HTTPStatus.NOT_FOUND, {"error": missing}) if data is None else json_answer(HTTPStatus.OK, data)


def export_answer(project: Project, skill_id: str) -> Answer:
    """The skill as plain Markdown skills in a zip file, as a download (issue #55)."""
    try:
        archive = export_zip(project, skill_id)
    except ExportError as error:
        return json_answer(HTTPStatus.NOT_FOUND, {"error": str(error)})
    return Answer(HTTPStatus.OK, archive, "application/zip", f"{skill_id}.zip")


def is_write_path(path: str) -> bool:
    return any(pattern.fullmatch(path) for pattern in (EDIT_PATH, AGENT_EDIT_PATH, RUN_ACTION_PATH))


def answer_post(project: Project, path: str, body: bytes) -> Answer:
    """The answer to a write: a block of a skill (issue #3), the text of an agent, or a run to cancel or delete."""
    if run_match := RUN_ACTION_PATH.fullmatch(path):
        return run_action_answer(project, run_match[1], run_match[2])
    edit_match = EDIT_PATH.fullmatch(path)
    agent_match = AGENT_EDIT_PATH.fullmatch(path)
    if edit_match is None and agent_match is None:
        return json_answer(HTTPStatus.NOT_FOUND, {"error": "There is no such endpoint."})
    try:
        request = json.loads(body)
        if edit_match is not None:
            apply_edit(project, edit_match[1], request)
            result = skill_detail(project, edit_match[1])
        else:
            assert agent_match is not None
            save_agent(project, agent_match[1], str(request["text"]))
            result = agent_detail(project, agent_match[1])
    except (ValueError, TypeError, KeyError) as error:
        return json_answer(HTTPStatus.BAD_REQUEST, {"error": [f"The request is not a valid edit: {error}"]})
    except (EditError, AgentEditError) as error:
        return json_answer(HTTPStatus.BAD_REQUEST, {"error": error.problems})
    return json_answer(HTTPStatus.OK, result)


def run_action_answer(project: Project, run_id: str, action: str) -> Answer:
    """Cancel a run (it answers with the new run detail), or delete a finished one."""
    try:
        if action == "cancel":
            cancel_run(project, run_id)
            return json_answer(HTTPStatus.OK, run_detail(project, run_id))
        delete_run(project, run_id)
    except RunError as error:
        return json_answer(HTTPStatus.BAD_REQUEST, {"error": [str(error)]})
    return json_answer(HTTPStatus.OK, {"deleted": run_id})


def apply_edit(project: Project, skill_id: str, request: dict[str, Any]) -> None:
    action = request["action"]
    if action == "update":
        update_block(project, skill_id, str(request["block"]), dict(request["values"]))
    elif action == "add":
        add_block(project, skill_id, str(request["block"]), str(request["type"]))
    elif action == "delete":
        delete_block(project, skill_id, str(request["block"]))
    else:
        raise EditError([f"Unknown action {action!r}: use update, add, or delete."])
