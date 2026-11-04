"""The typed shape of `run.json` and `state.json` (SPEC.md section 10.2), the shared frame helpers, and the one
event helper that the viewer and the Galtea upload share."""

from collections.abc import Iterable
from pathlib import Path
from typing import Any, TypedDict

SCHEMA_VERSION = 8  # 2: parallel tasks have a name. 3: a parallel item can be skipped by its `when`.
# 4: a parallel block with subagents logs the full prompt of each task (`task_prompts`).
# 5: a `script_ran` event holds the `input` that the script read on stdin.
# 6: `block_type` is `visit_cap` for the question at a visit cap.
# 7: every event has the `call_id` of its call instance; a call's `block_started` has its `inputs`.
# 8: `parallel` is a task with `for_each`: its `block_type` is `task`, its `block_started` has `for_each`, and
# the `block_completed` of a job with a tier has `tier`, and the `block_started` of a one-job task that spawns a
# `fresh` job has `task_prompts`.

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
    llm: str | None  # the model that the agent named with `start --model`; absent in runs before 0.39.0
    worktree: str | None  # the git worktree that `start --worktree` made for the run; absent before 0.42.0
    session_id: str | None  # the app session that owns the run; absent in runs before 0.9.0
    mode: str
    inputs: dict[str, Any]
    status: str
    pause_reason: str | None
    pause_error: str | None
    pause_steps_shown: bool  # a packet of this pause gave its pause steps; absent in runs before 0.38.0
    current_block: str | None
    packet_issued_at: str | None
    attempts: int
    stop_blocks: int
    # `pskill wait` (absent in runs before 0.37.0): the reason of the last wait, the start of the current
    # wait, its alarm, and the start of the first wait since the last answer (or since a gap of more than
    # `wait_minutes` after the last alarm).
    wait_reason: str | None
    wait_started_at: str | None
    wait_until: str | None
    waits_since: str | None
    created_at: str
    updated_at: str
    ended_at: str | None
    outputs: dict[str, Any] | None
    final_report: str | None
    # The summary card (absent in runs before 0.43.0): the end block, its description, and its rendered `pending`
    # (None: the skill declares none). A cancelled run has no end block.
    end_block: str | None
    end_description: str | None
    final_pending: str | None


class TaskJob(TypedDict):
    """One job of the current task block: its only job, or the job of one `for_each` item."""

    item: Any
    agent: str | None
    name: str | None  # from the block's `task_name`; None shows as "task <n>"
    tier: str | None  # from the block's `tier`; None: the subagent inherits the model
    tools: str | None  # from the block's `tools`; None: the subagent gets every tool
    context: str  # `main` (the main agent does it) or `fresh` (a subagent does it)
    output: dict[str, Any] | None  # None until a valid answer arrives
    attempts: int


class SkippedTask(TypedDict):
    """One item of a fixed `for_each` list whose `when` was false, so it started no task."""

    name: str | None  # from the block's `task_name`
    when: str  # the condition, as written in skill.yaml


class Frame(TypedDict):
    """One skill on the call stack. A `call` block pushes a frame; the child's end block pops it."""

    skill_id: str
    inputs: dict[str, Any]
    steps: dict[str, Any]
    history: dict[str, list[Any]]
    visits: dict[str, int]
    current_block: str | None
    arrived_from: str | None
    arrival_reason: str | None
    tasks: list[TaskJob] | None  # the jobs of the current task block; None before 1.0.0 at a task without for_each
    skipped_tasks: list[SkippedTask] | None  # its items whose `when` was false; absent in runs before 0.11.0
    started_at: str
    goal_shown: bool  # a child skill's first packet showed its goal; absent in runs before 0.10.0
    visit_cap_question: bool  # the current block's visit cap question is open; absent in runs before 0.33.0
    extra_visits: dict[str, int]  # the rounds that "more" added to each capped block; absent before 0.33.0
    call_id: str  # the call instance, like `review#2>doubt#1`; "" for the root; absent before 0.39.0


class RunState(TypedDict):
    """`state.json`: the call stack. The last frame is the one that runs."""

    frames: list[Frame]


def frame_context(
    info: RunInfo, run_folder: Path, frame: Frame, skill_folder: Path, block_ids: Iterable[str]
) -> dict[str, Any]:
    """The names that `{{ }}` values can read in one frame of the call stack (SPEC.md section 7.1)."""
    return {
        "inputs": frame["inputs"],
        "steps": frame["steps"],
        "history": {block_id: frame["history"].get(block_id, []) for block_id in block_ids},
        "run": {"id": info["run_id"], "mode": info["mode"], "harness": info["harness"], "dir": str(run_folder)},
        "skill": {"id": frame["skill_id"], "dir": str(skill_folder)},
    }


def child_call_id(call_id: str, block: str, visit: int) -> str:
    """The call id of the child that a call block starts: `<block>#<visit>`, after the caller's own id."""
    own = f"{block}#{visit}"
    return f"{call_id}>{own}" if call_id else own


def new_frame(skill_id: str, inputs: dict[str, Any], started_at: str, call_id: str = "") -> Frame:
    return Frame(
        skill_id=skill_id,
        inputs=inputs,
        steps={},
        history={},
        visits={},
        current_block=None,
        arrived_from=None,
        arrival_reason=None,
        tasks=None,
        skipped_tasks=None,
        started_at=started_at,
        goal_shown=False,
        visit_cap_question=False,
        extra_visits={},
        call_id=call_id,
    )


def one_job_prompt(event: dict[str, Any]) -> str | None:
    """The full prompt of a one-job task's subagent: the input of its row, more than the line that spawned it."""
    prompts = event.get("task_prompts")
    if event.get("block_type") == "task" and not event.get("for_each") and prompts:
        return str(prompts[0])
    return None
