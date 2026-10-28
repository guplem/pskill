"""The logic of the two harness hooks (SPEC.md section 9.2), independent of any harness format.

- Stop: while a run of this session has an open block, keep the agent working, at most
  `stop_hook_max_blocks` times in a row. Then pause the run and allow the stop, so a stuck agent never
  loops forever. When that pause has `on_pause` steps, the hook blocks that stop once more, with the
  pause packet. Another session in the same checkout stops freely. A worktree run (SPEC.md 7.8) holds the
  session that owns it from the checkout too, though its record lives in its worktree. While a `pskill wait`
  runs, and the harness wakes the agent after a background command (Claude Code), allow the stop with no
  message and no count.
- Session start: refresh stale skill stubs. It lists no runs: a run of another live session would invite
  the new session to take it over. `pskill runs --open` lists them.
"""

from pskill_runner.adapters import adapter_for
from pskill_runner.engine import list_runs, register_stop_attempt, unshown_pause_packet
from pskill_runner.project import Project
from pskill_runner.run_records import RunInfo
from pskill_runner.run_store import utc_now
from pskill_runner.run_waits import is_waiting
from pskill_runner.skill_loader import load_catalog
from pskill_runner.stubs import RUNNER, StubError, sync_stubs
from pskill_runner.worktrees import worktree_projects


def stop_hook_reason(project: Project, harness: str, session_id: str | None = None) -> str | None:
    """Why the agent must not stop yet, or None to allow the stop.

    A run holds only the session that owns it. A run with no owner, or a hook with no session id, holds
    every session of the harness, as before 0.9.0.
    """
    held = held_runs(project, harness, session_id)
    if not held:
        return None
    run_project, info = held[0]
    run_id = info["run_id"]
    # Only a harness that wakes the agent after a background command gets the wait: elsewhere nothing would
    # wake the agent, so the run would stay active and idle instead of pausing.
    can_wait = adapter_for(harness).wakes_after_background_command
    if can_wait and is_waiting(info, utc_now()):
        return None
    if not register_stop_attempt(run_project, run_id):
        return give_up_reason(run_project, run_id)
    folder = "" if run_project is project else f"It works in the folder `{run_project.root.as_posix()}`. "
    reason = (
        f"pskill run {run_id} has an open block. {folder}Continue it: run `{RUNNER} current {run_id}` and follow "
        f"the packet. If the user asked to stop, run `{RUNNER} pause {run_id}` instead."
    )
    if not can_wait:
        return reason
    return (
        f"{reason}\n"
        f'If you wait on background work, run `{RUNNER} wait {run_id} --reason "<what you wait on>"` in the '
        "background, then end your turn."
    )


def held_runs(project: Project, harness: str, session_id: str | None) -> list[tuple[Project, RunInfo]]:
    """The active runs of the harness that hold the session, each with the project that holds it, newest first.

    A run in a worktree of this checkout holds only the session that owns it: an unowned run there belongs to
    no session of the checkout, and other sessions share it.
    """
    runs = [(project, info) for info in list_runs(project) if holds_session(info, session_id)]
    for tree_project in worktree_projects(project):
        runs += [
            (tree_project, info)
            for info in list_runs(tree_project)
            if session_id is not None and info.get("session_id") == session_id
        ]
    active = [(owner, info) for owner, info in runs if info["harness"] == harness and info["status"] == "active"]
    return sorted(active, key=lambda pair: pair[1]["updated_at"], reverse=True)


def give_up_reason(project: Project, run_id: str) -> str | None:
    """The stop that paused the run passes, unless the pause has steps: then it is blocked once more, with them.

    The run is paused now, so the next stop passes and nothing loops. This also covers a run whose waits used up
    `max_wait_minutes`: its stops count again, and the same pause follows.
    """
    packet = unshown_pause_packet(project, run_id)
    if packet is None:
        return None
    return (
        f"pskill run {run_id} is paused: the agent ended its turn with an open block, several times. Do its pause "
        f"steps now, then end your turn.\n\n{packet}"
    )


def holds_session(info: RunInfo, session_id: str | None) -> bool:
    owner = info.get("session_id")
    return session_id is None or owner is None or owner == session_id


def session_start_text(project: Project) -> str:
    """The context for a new session. An empty text means that nothing needs attention."""
    lines = stub_refresh_lines(project)
    return "\n".join(lines) + "\n" if lines else ""


def stub_refresh_lines(project: Project) -> list[str]:
    catalog = load_catalog(project.skills_folder, project.agents_folder)
    skill_folders = [folder for folder in sorted(project.skills_folder.glob("*")) if (folder / "skill.yaml").is_file()]
    broken = [folder.name for folder in skill_folders if folder.name not in catalog.skills]
    lines = [
        f"pskill: the skill {name!r} does not load, so its stub was not refreshed. Run `{RUNNER} validate {name}`."
        for name in broken
    ]
    try:
        changes = sync_stubs(project, catalog, check_only=False, protected_names=set(broken))
    except StubError as error:
        return [*lines, f"pskill: {error}"]
    if changes:
        names = ", ".join(sorted({change.skill for change in changes}))
        lines.append(f"pskill: updated {len(changes)} stubs ({names}).")
    return lines
