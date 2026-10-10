"""`pskill wait`: the agent waits on background work, and the Stop hook stays quiet (SPEC.md section 9.2).

A wait is an alarm. It records `wait_until` in `run.json`, so the Stop hook allows the stop with no
message until then. The wait holds the run lock only to change `run.json`, never while it sleeps.\n"""

import time
from collections.abc import Callable
from datetime import datetime, timedelta

from pskill_runner.engine import Run, RunError, read_run_info, run_folder, runner_command
from pskill_runner.project import Project
from pskill_runner.run_records import RunInfo
from pskill_runner.run_store import parse_timestamp, run_lock, timestamp, utc_now

POLL_SECONDS = 5.0


def wait_for_run_change(
    project: Project,
    run_id: str,
    reason: str,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = utc_now,
) -> str:
    """Record a wait, then sleep until the run changes or the alarm rings. Return one line for the agent.

    It reads `run.json` with no lock: the file is always replaced whole, and a lock held for minutes would
    block every submit.
    """
    started = clock()
    saved = start_wait(project, run_id, reason, started)
    alarm = started + timedelta(minutes=project.config.wait_minutes)
    while True:
        info = read_run_info(project, run_id)
        if run_changed(info, saved):
            return change_text(project, info)
        remaining = (alarm - clock()).total_seconds()
        if remaining <= 0:
            return (
                f"{project.config.wait_minutes} minutes passed and nothing changed. If you still wait on {reason}, "
                f"run the wait again. Else continue the run: run `{runner_command(project)} current {run_id}`.\n"
            )
        sleep(min(POLL_SECONDS, remaining))


def run_changed(info: RunInfo, saved: RunInfo) -> bool:
    """Another command saved the run. An answer also clears the alarm, in case it saved in the same millisecond."""
    return (info["status"], info["updated_at"], info.get("wait_until")) != (
        saved["status"],
        saved["updated_at"],
        saved["wait_until"],
    )


def change_text(project: Project, info: RunInfo) -> str:
    run_id = info["run_id"]
    if info["status"] != "active":
        return f"Run {run_id} is now {info['status']}.\n"
    return f"Run {run_id} changed. Continue it: run `{runner_command(project)} current {run_id}`.\n"


def start_wait(project: Project, run_id: str, reason: str, now: datetime) -> RunInfo:
    """Record a wait that ends `wait_minutes` after `now`. Return the `run.json` that it saved.

    The waits of one block end after `max_wait_minutes` with no new answer: then the Stop hook counts the
    stops again, and a stuck run still pauses.
    """
    with run_lock(run_folder(project, run_id)):
        run = Run.load(project, run_id)
        run.require_status(("active",), "wait")
        waits_since = run.info.get("waits_since")
        max_wait = timedelta(minutes=project.config.max_wait_minutes)
        if waits_since is not None and now - parse_timestamp(waits_since) >= max_wait:
            raise RunError(
                f"The waits of run {run_id} lasted {project.config.max_wait_minutes} minutes with nothing new, so "
                f"no new wait starts. Check the background work, then continue the run: run "
                f"`{runner_command(project)} current {run_id}`."
            )
        run.info["wait_reason"] = reason
        run.info["wait_started_at"] = timestamp(now)
        run.info["wait_until"] = timestamp(now + timedelta(minutes=project.config.wait_minutes))
        run.info["waits_since"] = waits_since or timestamp(now)
        run.save()
    return run.info
