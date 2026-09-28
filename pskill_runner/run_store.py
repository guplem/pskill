"""Run files on disk (SPEC.md section 10.2).

A run folder holds `run.json` (metadata and status), `state.json` (the call stack), `events.jsonl`
(the trace, one JSON object per line), and `skills/` (the copy of the skills that the run uses).
"""

import hashlib
import json
import os
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVENTS_FILE_NAME = "events.jsonl"


def utc_now() -> datetime:
    return datetime.now(UTC)


def timestamp(moment: datetime) -> str:
    """UTC ISO 8601 with milliseconds, for example 2026-09-27T14:32:05.120Z."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_timestamp(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def new_run_id(moment: datetime) -> str:
    return f"r-{moment.astimezone(UTC):%Y%m%d-%H%M}-{secrets.token_hex(2)}"


def write_json_atomic(path: Path, data: Any) -> None:
    """Write to a temp file first, then replace the target, so a reader never sees half a file."""
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp_path, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_events(run_folder: Path) -> list[dict[str, Any]]:
    path = run_folder / EVENTS_FILE_NAME
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_event(run_folder: Path, event_type: str, **fields: Any) -> None:
    """Append one event. Its `seq` is the number of events already in the file, plus one."""
    path = run_folder / EVENTS_FILE_NAME
    seq = len(read_events(run_folder)) + 1
    event = {"ts": timestamp(utc_now()), "seq": seq, "type": event_type, **fields}
    with path.open("a", encoding="utf-8", newline="\n") as events_file:
        events_file.write(json.dumps(event, ensure_ascii=False) + "\n")


def copy_skill_snapshot(skill_folder: Path, run_folder: Path) -> None:
    """Copy a skill folder into the run, so the run always resumes from the same version (D22)."""
    shutil.copytree(skill_folder, run_folder / "skills" / skill_folder.name, dirs_exist_ok=True)


def folder_hash(folder: Path) -> str:
    """A hash of every file path and content in a folder."""
    digest = hashlib.sha256()
    for path in sorted(item for item in folder.rglob("*") if item.is_file()):
        digest.update(path.relative_to(folder).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"
