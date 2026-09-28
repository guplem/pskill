"""The typed shape of `run.json` and `state.json` (SPEC.md section 10.2)."""

from typing import Any, TypedDict

SCHEMA_VERSION = 1

ACTIVE_STATUSES = ("active", "waiting_for_human")
UNFINISHED_STATUSES = ("active", "waiting_for_human", "paused")


class RunInfo(TypedDict):
    """`run.json`: the run's metadata and status."""

    schema_version: int
    run_id: str
    skill_id: str
    skill_hash: str
    repo_commit: str | None
    repo_dirty: bool | None
    runner_version: str
    harness: str
    mode: str
    inputs: dict[str, Any]
    status: str
    pause_reason: str | None
    pause_error: str | None
    current_block: str | None
    packet_issued_at: str | None
    attempts: int
    stop_blocks: int
    created_at: str
    updated_at: str
    ended_at: str | None
    outputs: dict[str, Any] | None
    final_report: str | None


class Frame(TypedDict):
    """One skill on the call stack. A nested `call` pushes a new frame (M2)."""

    skill_id: str
    inputs: dict[str, Any]
    steps: dict[str, Any]
    history: dict[str, list[Any]]
    visits: dict[str, int]
    current_block: str | None
    arrived_from: str | None
    arrival_reason: str | None


class RunState(TypedDict):
    """`state.json`: the call stack. The last frame is the one that runs."""

    frames: list[Frame]


def new_frame(skill_id: str, inputs: dict[str, Any]) -> Frame:
    return Frame(
        skill_id=skill_id,
        inputs=inputs,
        steps={},
        history={},
        visits={},
        current_block=None,
        arrived_from=None,
        arrival_reason=None,
    )
