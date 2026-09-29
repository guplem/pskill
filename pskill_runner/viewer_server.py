"""`pskill view`: a small local web server for the viewer and its skill editor (SPEC.md section 14).

It serves the static files of `viewer/`, four JSON endpoints (runs and skills), a skill export, and
one write endpoint for the skill editor.
It listens on 127.0.0.1 only, and reads the files on every request, so it never shows stale state.
"""

import json
import re
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse

from pskill_runner.project import Project
from pskill_runner.skill_editor import EditError, add_block, delete_block, update_block
from pskill_runner.skill_export import ExportError, export_zip
from pskill_runner.skill_view import skill_detail, skills_overview
from pskill_runner.viewer_data import run_detail, runs_overview

LOCAL_HOST = "127.0.0.1"
EXPORT_PATH = re.compile(r"/api/skills/([^/]+)/export")
EDIT_PATH = re.compile(r"/api/skills/([^/]+)/edit")
MAX_EDIT_BYTES = 1_000_000
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}


class ViewerRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, *arguments: Any, project: Project, viewer_folder: Path, **keywords: Any) -> None:
        self.project = project
        self.viewer_folder = viewer_folder.resolve()
        super().__init__(*arguments, **keywords)

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/api/runs":
            self.send_json(HTTPStatus.OK, runs_overview(self.project))
        elif path.startswith("/api/runs/"):
            detail = run_detail(self.project, path.removeprefix("/api/runs/"))
            if detail is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "There is no run with this id."})
            else:
                self.send_json(HTTPStatus.OK, detail)
        elif export_match := EXPORT_PATH.fullmatch(path):
            self.send_export(export_match[1])
        elif path == "/api/skills":
            self.send_json(HTTPStatus.OK, skills_overview(self.project))
        elif path.startswith("/api/skills/"):
            skill = skill_detail(self.project, path.removeprefix("/api/skills/"))
            if skill is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "There is no skill with this id."})
            else:
                self.send_json(HTTPStatus.OK, skill)
        else:
            self.send_viewer_file(path)

    def do_POST(self) -> None:
        """The skill editor's one write endpoint: update, add, or delete a block (issue #3)."""
        path = unquote(urlparse(self.path).path)
        edit_match = EDIT_PATH.fullmatch(path)
        if edit_match is None:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "There is no such endpoint."})
            return
        refusal = self.write_refusal()
        if refusal is not None:
            self.send_json(HTTPStatus.FORBIDDEN, {"error": refusal})
            return
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            apply_edit(self.project, edit_match[1], request)
        except (ValueError, TypeError, KeyError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": [f"The request is not a valid edit: {error}"]})
            return
        except EditError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": error.problems})
            return
        self.send_json(HTTPStatus.OK, skill_detail(self.project, edit_match[1]))

    def write_refusal(self) -> str | None:
        """Why a write must not happen, or None. Only the viewer page itself may write.

        A JSON body makes the browser ask first (a CORS preflight), which this server never allows, so
        another web site cannot send it. The Host check stops a web site whose name points to 127.0.0.1
        (DNS rebinding), and the Origin check stops any other page.
        """
        host = self.headers.get("Host", "")
        port = cast(ThreadingHTTPServer, self.server).server_port
        if host not in (f"{LOCAL_HOST}:{port}", f"localhost:{port}"):
            return "Only the viewer on this machine may change skills."
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{host}":
            return "Only the viewer page may change skills."
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return "A change must be sent as JSON."
        if int(self.headers.get("Content-Length") or 0) > MAX_EDIT_BYTES:
            return "The change is too large."
        return None

    def send_export(self, skill_id: str) -> None:
        """The skill as plain Markdown skills in a zip file, as a download (issue #55)."""
        try:
            archive = export_zip(self.project, skill_id)
        except ExportError as error:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": str(error)})
            return
        disposition = f'attachment; filename="{skill_id}.zip"'
        self.send_body(HTTPStatus.OK, "application/zip", archive, {"Content-Disposition": disposition})

    def send_json(self, status: HTTPStatus, data: Any) -> None:
        self.send_body(status, "application/json; charset=utf-8", json.dumps(data).encode("utf-8"))

    def send_viewer_file(self, path: str) -> None:
        relative_path = "index.html" if path in ("", "/") else path.lstrip("/")
        file_path = (self.viewer_folder / relative_path).resolve()
        is_inside_viewer = file_path.is_relative_to(self.viewer_folder)
        if not is_inside_viewer or not file_path.is_file() or file_path.suffix not in CONTENT_TYPES:
            self.send_body(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found")
            return
        self.send_body(HTTPStatus.OK, CONTENT_TYPES[file_path.suffix], file_path.read_bytes())

    def send_body(
        self, status: HTTPStatus, content_type: str, body: bytes, headers: dict[str, str] | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *arguments: Any) -> None:
        """Keep the terminal quiet: one line per request would drown the useful output."""


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


def make_server(project: Project, viewer_folder: Path, port: int) -> ThreadingHTTPServer:
    handler = partial(ViewerRequestHandler, project=project, viewer_folder=viewer_folder)
    return ThreadingHTTPServer((LOCAL_HOST, port), handler)


def serve_viewer(project: Project, viewer_folder: Path, port: int, open_browser: bool) -> None:
    """Run the viewer until the user stops it with Ctrl+C."""
    server = make_server(project, viewer_folder, port)
    url = f"http://{LOCAL_HOST}:{server.server_address[1]}/"
    print(f"pskill viewer: {url} (press Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
