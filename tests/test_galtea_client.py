"""Tests for pskill_runner.galtea_client: the Galtea REST calls, and the urllib sender."""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest

from pskill_runner.galtea_client import GalteaClient, urllib_sender


class RecordingSender:
    """A fake sender: it records each call and returns the next prepared reply."""

    def __init__(self, *replies: Any) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.replies = list(replies)

    def __call__(self, method: str, path: str, body: Any) -> Any:
        self.calls.append((method, path, body))
        return self.replies.pop(0) if self.replies else None


def test_find_product_asks_by_exact_name_and_returns_the_first_match() -> None:
    sender = RecordingSender([{"id": "prod_1", "name": "pskill review"}])

    product = GalteaClient(sender).find_product("pskill review")

    assert product == {"id": "prod_1", "name": "pskill review"}
    assert sender.calls == [("GET", "/products?names=pskill%20review", None)]


def test_find_product_returns_none_when_no_product_has_the_name() -> None:
    assert GalteaClient(RecordingSender([])).find_product("missing") is None


def test_each_call_uses_its_galtea_route() -> None:
    sender = RecordingSender(
        {"id": "prod_1"}, None, {"id": "ver_1"}, {"id": "ses_1"}, None, None, {"id": "inf_1"}, None
    )
    client = GalteaClient(sender)

    assert client.create_product("p", "d") == {"id": "prod_1"}
    client.update_product("prod_1", {"description": "d"})
    assert client.get_or_create_version("prod_1", {"skill": "sha256:1"}) == {"id": "ver_1"}
    assert client.create_session({"customId": "c"}) == {"id": "ses_1"}
    client.update_session("ses_1", {"metadata": {}})
    client.finish_session("ses_1", {"stoppingReason": "done"})
    assert client.create_turn({"sessionId": "ses_1"}) == {"id": "inf_1"}
    client.create_spans([{"name": "s"}])

    assert [(method, path) for method, path, _ in sender.calls] == [
        ("POST", "/products"),
        ("PATCH", "/products/prod_1"),
        ("POST", "/versions/get-or-create"),
        ("POST", "/sessions"),
        ("PATCH", "/sessions/ses_1"),
        ("PATCH", "/sessions/ses_1/finish"),
        ("POST", "/inferenceResults"),
        ("POST", "/traces/batch?includeRejected=true"),
    ]
    assert sender.calls[0][2] == {"name": "p", "description": "d"}
    assert sender.calls[2][2] == {"productId": "prod_1", "facts": {"skill": "sha256:1"}}
    assert sender.calls[7][2] == {"traces": [{"name": "s"}]}


class RecordingHandler(BaseHTTPRequestHandler):
    """A local Galtea stand-in: it records each request and answers with JSON, or with no body."""

    requests: ClassVar[list[tuple[str, str, str | None, Any]]] = []

    def handle_request(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        RecordingHandler.requests.append((self.command, self.path, self.headers.get("Authorization"), body))
        reply = b"" if self.path.endswith("/finish") else json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    do_GET = handle_request
    do_POST = handle_request
    do_PATCH = handle_request

    def log_message(self, format: str, *args: Any) -> None:
        """Keep the test output quiet."""


@pytest.fixture
def galtea_server() -> Iterator[str]:
    RecordingHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_the_urllib_sender_sends_json_with_the_bearer_key(galtea_server: str) -> None:
    send = urllib_sender("gsk_test", galtea_server)

    reply = send("POST", "/sessions", {"customId": "c"})
    empty_reply = send("PATCH", "/sessions/s/finish", {"stoppingReason": "done"})
    get_reply = send("GET", "/products?names=p", None)

    assert reply == {"ok": True}
    assert empty_reply is None
    assert get_reply == {"ok": True}
    assert RecordingHandler.requests == [
        ("POST", "/sessions", "Bearer gsk_test", {"customId": "c"}),
        ("PATCH", "/sessions/s/finish", "Bearer gsk_test", {"stoppingReason": "done"}),
        ("GET", "/products?names=p", "Bearer gsk_test", None),
    ]


def test_find_session_asks_by_custom_id_and_version() -> None:
    sender = RecordingSender([{"id": "ses_1"}], [])
    client = GalteaClient(sender)

    assert client.find_session("a@r/b#1", "ver_1") == {"id": "ses_1"}
    assert client.find_session("a@r", "ver_1") is None
    assert sender.calls[0] == ("GET", "/sessions?customIds=a%40r%2Fb%231&versionIds=ver_1", None)
