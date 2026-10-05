"""`pskill view`: a small local web server for the viewer and its skill editor (SPEC.md section 14).

It serves the static files of `viewer/`, and answers the API with `viewer_api.py`: six JSON endpoints (runs,
skills, and agents), a skill export, and two write endpoints, the skill editor and the agent editor.
It listens on 127.0.0.1 only, and reads the files on every request, so it never shows stale state.
"""

import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse

from pskill_runner.project import Project
from pskill_runner.viewer_api import Answer, answer_get, answer_post, is_write_path, json_answer

LOCAL_HOST = "127.0.0.1"
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
        answer = answer_get(self.project, path)
        if answer is None:
            self.send_viewer_file(path)
        else:
            self.send_answer(answer)

    def do_POST(self) -> None:
        """The two write endpoints, once the request shows that it comes from the viewer page."""
        body = self.read_body()
        path = unquote(urlparse(self.path).path)
        if not is_write_path(path):
            self.send_answer(json_answer(HTTPStatus.NOT_FOUND, {"error": "There is no such endpoint."}))
            return
        refusal = self.write_refusal()
        if refusal is not None:
            self.send_answer(json_answer(HTTPStatus.FORBIDDEN, {"error": refusal}))
            return
        self.send_answer(answer_post(self.project, path, body))

    def read_body(self) -> bytes:
        """The request body, read before any answer. An empty body if its Content-Length is bad.

        If the server answers and closes the connection before the body arrives, Windows resets the
        connection, and the client loses the answer.
        """
        length = self.headers.get("Content-Length", "")
        if not length.isdigit() or int(length) > MAX_EDIT_BYTES:
            return b""
        return self.rfile.read(int(length))

    def write_refusal(self) -> str | None:
        """Why a write must not happen, or None. Only the viewer page itself may write.

        A JSON body makes the browser ask first (a CORS preflight), which this server never allows, so
        another web site cannot send it. The Host check stops a web site whose name points to 127.0.0.1
        (DNS rebinding), and the Origin check stops any other page.
        """
        host = self.headers.get("Host", "")
        port = cast(ThreadingHTTPServer, self.server).server_port
        if host not in (f"{LOCAL_HOST}:{port}", f"localhost:{port}"):
            return "Only the viewer on this machine may change skills and agents."
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{host}":
            return "Only the viewer page may change skills and agents."
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return "A change must be sent as JSON."
        length = self.headers.get("Content-Length", "")
        if not length.isdigit() or int(length) > MAX_EDIT_BYTES:
            return "A change needs a Content-Length of at most 1 MB."
        return None

    def send_answer(self, answer: Answer) -> None:
        headers = {}
        if answer.download_name is not None:
            headers["Content-Disposition"] = f'attachment; filename="{answer.download_name}"'
        self.send_body(HTTPStatus(answer.status), answer.content_type, answer.body, headers)

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
