"""The upload of runs to Galtea as production usage (SPEC.md section 10.4, decision D29).

After each run command, `upload_run` reads the new events of the run and sends them to Galtea:
- one session for each execution of a skill whose `skill.yaml` names `x-galtea.product`,
- one turn for each block that completes, and one FAILED turn for a block that pauses the run,
- spans inside each turn: the block itself, its rejected submissions, its script attempts, its pauses.

The upload is best effort. With no key it does nothing. Any error is swallowed, and the command
prints and returns what it would print and return without Galtea.
"""

import contextlib
import json
import os
import re
import urllib.error
import uuid
from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any, TypedDict, cast

from pskill_runner.adapters import adapter_for, tier_row
from pskill_runner.computed_values import ComputedValueError, render_text
from pskill_runner.galtea_client import GalteaClient, urllib_sender
from pskill_runner.project import Project
from pskill_runner.run_records import RunInfo, RunState, child_call_id, frame_context
from pskill_runner.run_store import folder_hash, parse_timestamp, read_events, read_json, timestamp, write_json_atomic
from pskill_runner.yaml_loading import load_skill_yaml

KEY_FILE_NAME = "galtea.env"
KEY_VARIABLE = "GALTEA_API_KEY"
STATE_FILE_NAME = "galtea.json"
# Galtea closes a session after this many minutes with no new turn. A run can pause for days.
AUTO_CLOSE_MINUTES = 10080
# A paused run that resumes sends turns to a closed session: Galtea must reopen it, not drop them.
CLOSED_SESSION_POLICY = "REOPEN_AND_REEVALUATE"
# A turn holds two texts in a body of at most 512 KB: 60 000 characters of 4 UTF-8 bytes each still fit.
TEXT_LIMIT = 60_000
FAILURE_PAUSE_REASONS = ("block_failed", "runner_error")
FAILED_END_STATUSES = ("failed", "cancelled")
SPAN_TYPES = {"task": "AGENT", "decision": "AGENT", "parallel": "AGENT", "visit_cap": "AGENT"}
SPAN_TYPES.update({"script": "TOOL", "call": "CHAIN", "end": "SPAN"})
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgsk_[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
]
REDACTED = "[redacted]"


class SessionRecord(TypedDict):
    """One execution of one skill: its Galtea session, or None when the skill names no product."""

    session_id: str | None
    custom_id: str
    turns: int
    metadata: dict[str, Any]
    finished: bool  # the session got its finish call


class UploadState(TypedDict):
    """`galtea.json` in the run folder: what the upload already did."""

    last_seq: int
    products: dict[str, str]  # product name -> product id
    versions: dict[str, str]  # product id and facts (JSON) -> version id; Galtea allows 10 a minute
    sessions: dict[str, SessionRecord]  # call id -> its session ("" is the root skill)


ClientFactory = Callable[[str], GalteaClient]


def default_client(api_key: str) -> GalteaClient:
    return GalteaClient(urllib_sender(api_key))


def upload_run(
    project: Project,
    run_id: str,
    make_client: ClientFactory = default_client,
    environment: Mapping[str, str] = os.environ,
) -> None:
    """Send the new events of a run to Galtea. Never raises: an upload must never break a command."""
    try:
        api_key = read_api_key(project, environment)
        if api_key is not None:
            RunUpload(project, project.runs_folder / run_id, make_client(api_key)).upload_new_events()
    except Exception:  # an upload must never break a command, so every failure ends quietly
        return


def read_api_key(project: Project, environment: Mapping[str, str]) -> str | None:
    """The key in `.pskill/galtea.env` (one `GALTEA_API_KEY=...` line), else the environment variable."""
    key_file = project.pskill_folder / KEY_FILE_NAME
    if key_file.is_file():
        for line in key_file.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == KEY_VARIABLE and value.strip():
                return value.strip().strip("\"'")
    return environment.get(KEY_VARIABLE) or None


def galtea_settings(skill_folder: Path) -> dict[str, Any]:
    """The `x-galtea` mapping of a skill copy, or an empty mapping."""
    raw = load_skill_yaml((skill_folder / "skill.yaml").read_text(encoding="utf-8"))
    settings = raw.get("x-galtea") if isinstance(raw, dict) else None
    return settings if isinstance(settings, dict) else {}


def redacted(value: Any) -> Any:
    """The value with every known secret pattern replaced, and every text cut to the size limit."""
    if isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            value = pattern.sub(REDACTED, value)
        return value[:TEXT_LIMIT]
    if isinstance(value, dict):
        return {key: redacted(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redacted(item) for item in value]
    return value


def as_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


class RunUpload:
    """The upload of one run's new events, with the state that `galtea.json` keeps between commands."""

    def __init__(self, project: Project, folder: Path, client: GalteaClient) -> None:
        self.project = project
        self.folder = folder
        self.client = client
        self.info = cast(RunInfo, read_json(folder / "run.json"))
        state_path = folder / STATE_FILE_NAME
        empty = UploadState(last_seq=0, products={}, versions={}, sessions={})
        self.state = cast(UploadState, read_json(state_path)) if state_path.is_file() else empty
        self.events: list[dict[str, Any]] = []

    def upload_new_events(self) -> None:
        self.events = read_events(self.folder)
        reachable = True
        for event in self.events:
            if event["seq"] <= self.state["last_seq"]:
                continue
            try:
                if reachable:
                    self.upload_event(event)
            except urllib.error.HTTPError:  # Galtea refused this event: the next one may pass
                pass
            except OSError:  # Galtea is down or blocked: every call would wait for the timeout, so stop trying
                reachable = False
            except Exception:  # fire and forget: a failed event is not sent again
                pass
            self.state["last_seq"] = event["seq"]
            self.save()
        if reachable:
            self.update_metadata()
        self.save()

    def save(self) -> None:
        write_json_atomic(self.folder / STATE_FILE_NAME, self.state)

    # --- events -----------------------------------------------------------------------------------

    def upload_event(self, event: dict[str, Any]) -> None:
        if event["type"] == "block_completed":
            self.upload_completed_block(event)
        elif event["type"] == "run_paused" and event.get("reason") in FAILURE_PAUSE_REASONS:
            self.upload_failed_block(event)
        elif event["type"] == "run_ended":
            self.finish_root(event)

    def upload_completed_block(self, event: dict[str, Any]) -> None:
        call_id = event.get("call_id", "")
        started = self.block_start(event)
        session = self.session_for(call_id, skill_id_of(event))
        if started.get("block_type") == "call":
            child_id = child_call_id(call_id, event["block"], started.get("visit", 0))
            self.finish_child(child_id, event["output"])
        if session is None:
            return
        output = dict(event["output"]) if isinstance(event["output"], dict) else {"output": event["output"]}
        if started.get("block_type") == "call":
            child = self.state["sessions"].get(child_call_id(call_id, event["block"], started.get("visit", 0)))
            if child is not None and child["session_id"] is not None:
                output["child_session"] = child["custom_id"]
        turn = {
            "input": as_text(self.turn_input(started)),
            "actualOutput": as_text(output),
            "latency": event.get("duration_ms", 0),
            "status": "GENERATED",
        }
        self.send_turn(session, turn, started, event, decided_by=event.get("decided_by"))

    def upload_failed_block(self, event: dict[str, Any]) -> None:
        started = self.last_block_start(event)
        session = self.session_for(started.get("call_id", ""), skill_id_of(started))
        if session is None:
            return
        error = event.get("error") or event.get("reason", "")  # the event keeps the error of this pause
        turn = {
            "input": as_text(self.turn_input(started)),
            "actualOutput": "",
            "latency": elapsed_ms(started["ts"], event["ts"]),
            "status": "FAILED",
            "error": str(error),
        }
        self.send_turn(session, turn, started, event, decided_by=None)

    def send_turn(
        self,
        session: SessionRecord,
        turn: dict[str, Any],
        started: dict[str, Any],
        ended: dict[str, Any],
        decided_by: str | None,
    ) -> None:
        body = redacted({"sessionId": session["session_id"], "index": session["turns"], **turn})
        session["turns"] += 1
        created = self.client.create_turn(body)
        self.client.create_spans(redacted(self.spans(created["id"], started, ended, decided_by)))

    def turn_input(self, started: dict[str, Any]) -> Any:
        """What went into the block: the packet, a script's command and stdin, or a call's inputs."""
        if started.get("packet"):
            return started["packet"]
        if started.get("block_type") == "call":
            return started.get("inputs", {})
        if started.get("block_type") == "script":
            script_runs = [e for e in self.block_window(started, None) if e["type"] == "script_ran"]
            if script_runs:  # none when its command or input failed to compute: the script never ran
                return {"argv": script_runs[0].get("argv"), "input": script_runs[0].get("input")}
        return {"block": started.get("block")}

    # --- spans ------------------------------------------------------------------------------------

    def spans(
        self, turn_id: str, started: dict[str, Any], ended: dict[str, Any], decided_by: str | None
    ) -> list[dict[str, Any]]:
        root_id = str(uuid.uuid4())
        metadata = {
            "frame": started.get("frame"),
            "call_id": started.get("call_id", ""),
            "block_type": started.get("block_type"),
            "visit": started.get("visit"),
            "from": started.get("from"),
            "reason": started.get("reason"),
            "decided_by": decided_by,
        }
        if "task" in ended:
            metadata["task"] = ended["task"]
            metadata.update(self.task_model(started, ended["task"]))
        root = {
            "id": root_id,
            "inferenceResultId": turn_id,
            "name": str(started.get("block")),
            "type": SPAN_TYPES.get(str(started.get("block_type")), "SPAN"),
            "startTime": started["ts"],
            "endTime": ended["ts"],
            "metadata": metadata,
        }
        children = [self.detail_span(turn_id, root_id, event) for event in self.block_window(started, ended)]
        return [root, *[child for child in children if child is not None]]

    def detail_span(self, turn_id: str, parent_id: str, event: dict[str, Any]) -> dict[str, Any] | None:
        base = {"id": str(uuid.uuid4()), "inferenceResultId": turn_id, "parentTraceId": parent_id}
        if event["type"] == "submission_rejected":
            return {
                **base,
                "name": "rejected submission",
                "type": "EVENT",
                "inputData": {"raw": event.get("raw")},
                "outputData": {"errors": event.get("errors")},
                "startTime": event["ts"],
                "endTime": event["ts"],
            }
        if event["type"] == "script_ran":
            start = parse_timestamp(event["ts"]) - timedelta(milliseconds=event.get("duration_ms", 0))
            return {
                **base,
                "name": "script attempt",
                "type": "TOOL",
                "inputData": {"argv": event.get("argv"), "input": event.get("input")},
                "outputData": {
                    "exit_code": event.get("exit_code"),
                    "stdout": event.get("stdout"),
                    "stderr": event.get("stderr"),
                },
                "error": event.get("problem"),
                "latencyMs": event.get("duration_ms", 0),
                "startTime": timestamp(start),
                "endTime": event["ts"],
            }
        if event["type"] in ("run_paused", "run_resumed"):
            return {
                **base,
                "name": event["type"].replace("_", " "),
                "type": "EVENT",
                "metadata": {"reason": event.get("reason")},
                "startTime": event["ts"],
                "endTime": event["ts"],
            }
        return None

    def task_model(self, started: dict[str, Any], task: int) -> dict[str, Any]:
        """The tier of a parallel task and the model that the tier means, while the run still holds the task."""
        state = cast(RunState, read_json(self.folder / "state.json"))
        for frame in state["frames"]:
            tasks = frame.get("tasks") or []
            tier = tasks[task].get("tier") if task < len(tasks) else None
            if frame.get("call_id", "") == started.get("call_id", "") and tier is not None:
                return {"tier": tier, "tier_model": self.tier_model(tier)}
        return {}  # no tier, or the block is over and the run no longer holds its tasks

    def tier_model(self, tier: str) -> str:
        row = tier_row(adapter_for(self.info["harness"]), self.project.config.tiers, tier)
        return row.model or "inherited"

    # --- finding events ---------------------------------------------------------------------------

    def block_start(self, event: dict[str, Any]) -> dict[str, Any]:
        """The last `block_started` of the event's block and call before the event. The engine always logs one."""
        return next(
            candidate
            for candidate in reversed(self.events[: event["seq"] - 1])
            if candidate["type"] == "block_started"
            and candidate.get("block") == event.get("block")
            and candidate.get("call_id", "") == event.get("call_id", "")
        )

    def last_block_start(self, event: dict[str, Any]) -> dict[str, Any]:
        """The block that was open when the event came. None open raises, and the event is skipped."""
        return next(
            candidate for candidate in reversed(self.events[: event["seq"] - 1]) if candidate["type"] == "block_started"
        )

    def block_window(self, started: dict[str, Any], ended: dict[str, Any] | None) -> list[dict[str, Any]]:
        """The events of a block's own call between its start and its end (or the end of the trace)."""
        last = ended["seq"] if ended is not None else len(self.events) + 1
        return [
            event
            for event in self.events[started.get("seq", last) : last - 1]
            if event.get("call_id", "") == started.get("call_id", "")
        ]

    # --- sessions ---------------------------------------------------------------------------------

    def session_for(self, call_id: str, skill_id: str) -> SessionRecord | None:
        """The session of a call, created on first use. None when its skill names no product."""
        sessions = self.state["sessions"]
        if call_id not in sessions:
            sessions[call_id] = self.new_session(call_id, skill_id)
        record = sessions[call_id]
        return record if record["session_id"] is not None else None

    def new_session(self, call_id: str, skill_id: str) -> SessionRecord:
        custom_id = f"{skill_id}@{self.info['run_id']}" + (f"/{call_id}" if call_id else "")
        record = SessionRecord(session_id=None, custom_id=custom_id, turns=0, metadata={}, finished=False)
        skill_folder = self.folder / "skills" / skill_id
        settings = galtea_settings(skill_folder)
        product_name = settings.get("product")
        if not isinstance(product_name, str) or not product_name.strip():
            return record
        raw = load_skill_yaml((skill_folder / "skill.yaml").read_text(encoding="utf-8"))
        product_id = self.product_id(product_name.strip(), str(raw.get("description") or skill_id))
        facts = self.version_facts(skill_id, skill_folder, raw)
        version_id = self.version_id(product_id, facts)
        metadata = self.automatic_metadata(call_id)
        # Parallel commands upload at once with no lock, so another one may have created the session.
        session = self.client.find_session(custom_id, version_id) or self.client.create_session(
            redacted(
                {
                    "versionId": version_id,
                    "customId": custom_id,
                    "isProduction": True,
                    "context": str(raw.get("goal") or ""),
                    "metadata": metadata,
                }
            )
        )
        return SessionRecord(session_id=session["id"], custom_id=custom_id, turns=0, metadata=metadata, finished=False)

    def product_id(self, name: str, description: str) -> str:
        """The id of the product, created when missing. Its description and session settings follow the skill."""
        if name not in self.state["products"]:
            product = self.client.find_product(name) or self.client.create_product(name, description)
            self.client.update_product(
                product["id"],
                {
                    "description": description,
                    "autoCloseInactivityMinutes": AUTO_CLOSE_MINUTES,
                    "closedSessionInferenceCreationPolicy": CLOSED_SESSION_POLICY,
                },
            )
            self.state["products"][name] = product["id"]
        return self.state["products"][name]

    def version_id(self, product_id: str, facts: dict[str, str]) -> str:
        """The id of the version with these facts, asked of Galtea once per run (its rate limit is low)."""
        versions = self.state.setdefault("versions", {})
        key = json.dumps([product_id, facts], sort_keys=True)
        if key not in versions:
            versions[key] = self.client.get_or_create_version(product_id, facts)["id"]
        return versions[key]

    def version_facts(self, skill_id: str, skill_folder: Path, raw: dict[str, Any]) -> dict[str, str]:
        """What can change how the skill behaves. A new value gives a new Galtea version."""
        skill_hash = self.info["skill_hash"] if skill_id == self.info["skill_id"] else folder_hash(skill_folder)
        facts = {
            "skill": skill_hash,
            "runner": self.info["runner_version"],
            "harness": self.info["harness"],
            "llm": self.info.get("llm") or "unknown",
        }
        blocks = raw.get("blocks") or {}
        if any(isinstance(block, dict) and block.get("type") == "parallel" for block in blocks.values()):
            adapter = adapter_for(self.info["harness"])
            rows = {tier: self.tier_model(tier) for tier in sorted(adapter.tier_rows)}
            facts["tiers"] = json.dumps(rows, sort_keys=True)
        return facts

    def automatic_metadata(self, call_id: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "run_id": self.info["run_id"],
            "repo_commit": self.info.get("repo_commit"),
            "repo_dirty": self.info.get("repo_dirty"),
            "harness": self.info["harness"],
            "llm": self.info.get("llm"),
            "mode": self.info["mode"],
            "runner_version": self.info["runner_version"],
            "started_at": self.info["created_at"],
        }
        if call_id:
            parent_call_id = call_id.rpartition(">")[0]
            parent = self.state["sessions"].get(parent_call_id)
            metadata["call_id"] = call_id
            metadata["parent_session_custom_id"] = parent["custom_id"] if parent is not None else None
        return metadata

    def finish_child(self, call_id: str, output: Any) -> None:
        record = self.state["sessions"].get(call_id)
        if record is None or record["session_id"] is None:
            return
        status = str(output.get("status", "")) if isinstance(output, dict) else ""
        self.finish_session(record, status)

    def finish_root(self, event: dict[str, Any]) -> None:
        """Finish the root session, and each child session that the run ended inside (a cancel in a child)."""
        for call_id, child in self.state["sessions"].items():
            if call_id and child["session_id"] is not None and not child.get("finished"):
                self.finish_session(child, str(event.get("status", "")))
        record = self.state["sessions"].get("")
        if record is None or record["session_id"] is None:
            return
        final = {"status": event.get("status"), "ended_at": event["ts"], "duration_ms": event.get("duration_ms")}
        record["metadata"] = {**record["metadata"], **final}
        with contextlib.suppress(urllib.error.HTTPError):  # a refused update must not keep the session open
            self.client.update_session(record["session_id"], {"metadata": redacted(record["metadata"])})
        self.finish_session(record, str(event.get("status", "")))

    def finish_session(self, record: SessionRecord, status: str) -> None:
        record["finished"] = True
        session_id = str(record["session_id"])
        if status in FAILED_END_STATUSES:
            self.client.finish_session(session_id, {"error": status})
        else:
            self.client.finish_session(session_id, {"stoppingReason": status or "done"})

    # --- metadata templates -----------------------------------------------------------------------

    def update_metadata(self) -> None:
        """Render the `x-galtea.metadata` templates of each frame on the stack; send the values that are new."""
        for frame in cast(RunState, read_json(self.folder / "state.json"))["frames"]:
            record = self.state["sessions"].get(frame.get("call_id", ""))
            if record is None or record["session_id"] is None:
                continue
            try:
                templates = galtea_settings(self.folder / "skills" / frame["skill_id"]).get("metadata") or {}
                skill_folder = self.folder / "skills" / frame["skill_id"]
                raw = load_skill_yaml((skill_folder / "skill.yaml").read_text(encoding="utf-8"))
                context = frame_context(self.info, self.folder, frame, skill_folder, raw.get("blocks") or {})
                rendered = rendered_metadata(templates, context)
                if any(record["metadata"].get(name) != value for name, value in rendered.items()):
                    record["metadata"] = {**record["metadata"], **rendered}
                    self.client.update_session(record["session_id"], {"metadata": redacted(record["metadata"])})
            except Exception:  # fire and forget, as for the events
                continue


def rendered_metadata(templates: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    """The metadata templates that render now. A template whose step has not run yet waits for a later command."""
    values: dict[str, str] = {}
    for name, template in templates.items():
        try:
            values[str(name)] = render_text(str(template), context)
        except ComputedValueError:
            continue
    return values


def skill_id_of(event: dict[str, Any]) -> str:
    """The skill that logged an event: the last skill of its frame chain."""
    return str(event.get("frame", "")).split(">")[-1]


def elapsed_ms(start: str, end: str) -> int:
    return int((parse_timestamp(end) - parse_timestamp(start)).total_seconds() * 1000)
