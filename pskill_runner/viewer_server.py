"""`pskill view`: a small local web server for the read-only viewer (SPEC.md section 14).

It serves the static files of `viewer/`, four JSON endpoints (runs and skills), and a skill export.
It listens on 127.0.0.1 only, and reads the files on every request, so it never shows stale state.
"""

import json
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from pskill_runner.project import Project
from pskill_runner.skill_export import ExportError, export_zip
from pskill_runner.skill_view import skill_detail, skills_overview
from pskill_runner.viewer_data import run_detail, runs_overview

LOCAL_HOST = "127.0.0.1"
EXPORT_SUFFIX = "/export"
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
        elif path.startswith("/api/skills/") and path.endswith(EXPORT_SUFFIX):
            self.send_export(path.removeprefix("/api/skills/").removesuffix(EXPORT_SUFFIX))
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
