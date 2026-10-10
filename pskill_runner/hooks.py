"""The logic of the two harness hooks (SPEC.md section 9.2), independent of any harness format.

- Stop: while a run of this session has an open block, keep the agent working, at most
  `stop_hook_max_blocks` times in a row. Then allow the stop and pause the run, so a stuck agent never
  loops forever. Another session in the same checkout stops freely. While a `pskill wait` runs, allow the
  stop with no message and no count.
- Session start: refresh stale skill stubs. It lists no runs: a run of another live session would invite
  the new session to take it over. `pskill runs --open` lists them.
"""

from pskill_runner.adapters import adapter_for
from pskill_runner.engine import list_runs, register_stop_attempt
from pskill_runner.project import Project
from pskill_runner.run_records import RunInfo
from pskill_runner.run_store import utc_now
from pskill_runner.run_waits import is_waiting
from pskill_runner.skill_loader import load_catalog
from pskill_runner.stubs import RUNNER, StubError, sync_stubs


def stop_hook_reason(project: Project, harness: str, session_id: str | None = None) -> str | None:
    """Why the agent must not stop yet, or None to allow the stop.

    A run holds only the session that owns it. A run with no owner, or a hook with no session id, holds
    every session of the harness, as before 0.9.0.
    """
    active_runs = [
        info
        for info in list_runs(project)
        if info["harness"] == harness and info["status"] == "active" and holds_session(info, session_id)
    ]
    if not active_runs:
        return None
    run_id = active_runs[0]["run_id"]
    # Only a harness that wakes the agent after a background command gets the wait: elsewhere nothing would
    # wake the agent, so the run would stay active and idle instead of pausing.
    can_wait = adapter_for(harness).wakes_after_background_command
    if can_wait and is_waiting(active_runs[0], utc_now()):
        return None
    if not register_stop_attempt(project, run_id):
        return None
    reason = (
        f"pskill run {run_id} has an open block. Continue it: run `{RUNNER} current {run_id}` and follow the "
        f"packet. If the user asked to stop, run `{RUNNER} pause {run_id}` instead."
    )
    if not can_wait:
        return reason
    return (
        f"{reason}\n"
        f'If you wait on background work, run `{RUNNER} wait {run_id} --reason "<what you wait on>"` in the '
        "background, then end your turn."
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
