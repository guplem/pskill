"""The logic of the two harness hooks (SPEC.md section 9.2), independent of any harness format.

- Stop: while a run has an open block, keep the agent working, at most `stop_hook_max_blocks` times in
  a row. Then allow the stop and pause the run, so a stuck agent never loops forever.
- Session start: refresh stale skill stubs, then list the unfinished runs. Never resume a run by itself.
"""

from pskill_runner.engine import list_runs, register_stop_attempt
from pskill_runner.project import Project
from pskill_runner.run_records import UNFINISHED_STATUSES
from pskill_runner.skill_loader import load_catalog
from pskill_runner.stubs import RUNNER, StubError, sync_stubs

LISTED_RUNS_LIMIT = 3


def stop_hook_reason(project: Project, harness: str) -> str | None:
    """Why the agent must not stop yet, or None to allow the stop."""
    active_runs = [info for info in list_runs(project) if info["harness"] == harness and info["status"] == "active"]
    if not active_runs:
        return None
    run_id = active_runs[0]["run_id"]
    if not register_stop_attempt(project, run_id):
        return None
    return (
        f"pskill run {run_id} has an open block. Continue it: run `{RUNNER} current {run_id}` and follow the "
        f"packet. If the user asked to stop, run `{RUNNER} pause {run_id}` instead."
    )


def session_start_text(project: Project) -> str:
    """The context for a new session. An empty text means that nothing needs attention."""
    lines = stub_refresh_lines(project) + open_run_lines(project)
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
        names = ", ".join(sorted({change.path.parent.name for change in changes}))
        lines.append(f"pskill: updated {len(changes)} stubs ({names}).")
    return lines


def open_run_lines(project: Project) -> list[str]:
    open_runs = [info for info in list_runs(project) if info["status"] in UNFINISHED_STATUSES]
    if not open_runs:
        return []
    lines = ["pskill: unfinished runs in this checkout:"]
    for info in open_runs[:LISTED_RUNS_LIMIT]:
        run_id = info["run_id"]
        block = info["current_block"] or "-"
        lines.append(
            f"- {run_id}  {info['skill_id']}  {block}  {info['status']}  (continue: `{RUNNER} current {run_id}`)"
        )
    if len(open_runs) > LISTED_RUNS_LIMIT:
        hidden = len(open_runs) - LISTED_RUNS_LIMIT
        lines.append(f"Run `{RUNNER} runs --open` for the other {hidden}.")
    return lines
