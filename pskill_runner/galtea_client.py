"""The Galtea REST calls that the run upload uses (SPEC.md section 10.4).

Verified against the Galtea monorepo (api/src) on 2026-10-15:
- The API is at https://api.galtea.ai and takes `Authorization: Bearer <key>`. A key acts as its user.
- The REST names are older than the product names: `/inferenceResults` is a turn ("trace" in the app),
  and `/traces` is a span.
- `POST /sessions`: `customId` is unique per version and cannot change. `isProduction` marks real usage.
- `GET /sessions` and `GET /products` filter by `customIds` and `versionIds`, or by `names`, and return a list.
- `POST /inferenceResults` has no metadata and no timestamp. The client may set `index`.
- `POST /traces/batch`: a span `id` is a global key, so it must be unique (a UUID). The body may hold 20 MB.
- Every other body may hold 512 KB. `POST /versions/get-or-create` allows 10 calls a minute per user.
"""

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

DEFAULT_BASE_URL = "https://api.galtea.ai"
TIMEOUT_SECONDS = 5

# A sender does one request: the method, the path under the base URL, and the JSON body (or None).
# It returns the JSON reply, or None for an empty reply.
Sender = Callable[[str, str, Any], Any]


def urllib_sender(api_key: str, base_url: str = DEFAULT_BASE_URL) -> Sender:
    """The real sender: urllib with the Bearer key and a short timeout. An HTTP error raises."""

    def send(method: str, path: str, body: Any) -> Any:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(base_url + path, data=data, method=method)
        request.add_header("Authorization", f"Bearer {api_key}")
        request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            reply = response.read()
        return json.loads(reply) if reply else None

    return send


class GalteaClient:
    """One method per Galtea call. The sender does the HTTP, so tests pass a fake one."""

    def __init__(self, send: Sender) -> None:
        self.send = send

    def find_product(self, name: str) -> dict[str, Any] | None:
        products = self.send("GET", f"/products?names={urllib.parse.quote(name)}", None)
        return products[0] if products else None

    def create_product(self, name: str, description: str) -> dict[str, Any]:
        return dict(self.send("POST", "/products", {"name": name, "description": description}))

    def update_product(self, product_id: str, fields: dict[str, Any]) -> None:
        self.send("PATCH", f"/products/{product_id}", fields)

    def get_or_create_version(self, product_id: str, facts: dict[str, str]) -> dict[str, Any]:
        return dict(self.send("POST", "/versions/get-or-create", {"productId": product_id, "facts": facts}))

    def find_session(self, custom_id: str, version_id: str) -> dict[str, Any] | None:
        query = f"customIds={urllib.parse.quote(custom_id, safe='')}&versionIds={urllib.parse.quote(version_id)}"
        sessions = self.send("GET", f"/sessions?{query}", None)
        return sessions[0] if sessions else None

    def create_session(self, body: dict[str, Any]) -> dict[str, Any]:
        return dict(self.send("POST", "/sessions", body))

    def update_session(self, session_id: str, fields: dict[str, Any]) -> None:
        self.send("PATCH", f"/sessions/{session_id}", fields)

    def finish_session(self, session_id: str, body: dict[str, Any]) -> None:
        self.send("PATCH", f"/sessions/{session_id}/finish", body)

    def create_turn(self, body: dict[str, Any]) -> dict[str, Any]:
        return dict(self.send("POST", "/inferenceResults", body))

    def create_spans(self, spans: list[dict[str, Any]]) -> None:
        self.send("POST", "/traces/batch?includeRejected=true", {"traces": spans})
