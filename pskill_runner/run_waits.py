"""`pskill wait`: the agent waits on background work, and the Stop hook stays quiet (SPEC.md section 9.2).

A wait is an alarm. It records `wait_until` in `run.json`, so the Stop hook allows the stop with no
message until then. The wait holds the run lock only to write or read `run.json`, never while it sleeps.
"""

import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from pskill_runner.engine import Run, RunError, run_folder, runner_command
from pskill_runner.project import Project
from pskill_runner.run_records import RunInfo
from pskill_runner.run_store import RunLockTimeout, parse_timestamp, read_json, run_lock, timestamp, utc_now

POLL_SECONDS = 5.0


def wait_for_run_change(
    project: Project,
    run_id: str,
    reason: str,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = utc_now,
) -> str:
    """Record a wait, then sleep until the run changes or the alarm rings. Return one line for the agent.

    Each poll takes the run lock for its read only: a lock held for minutes would block every submit.
    """
    started = clock()
    saved = start_wait(project, run_id, reason, started)
    alarm = started + timedelta(minutes=project.config.wait_minutes)
    folder = run_folder(project, run_id)
    while True:
        if not (folder / "run.json").is_file():
            return f"Run {run_id} is deleted.\n"
        info = read_when_free(folder)
        if info is not None and run_changed(info, saved):
            return change_text(project, info)
        remaining = (alarm - clock()).total_seconds()
        if remaining <= 0:
            return (
                f"{project.config.wait_minutes} minutes passed and nothing changed. If you still wait on {reason}, "
                f"run the wait again. Else continue the run: run `{runner_command(project)} current {run_id}`.\n"
            )
        sleep(min(POLL_SECONDS, remaining))


def read_when_free(folder: Path) -> RunInfo | None:
    """`run.json` read under the lock, or None when the lock stays busy past its timeout or the run is gone.

    The lock lasts a few milliseconds: on Windows, a read during an `os.replace` fails both. A long
    `script` block can hold the lock for minutes; the wait then reads again after its next sleep.
    """
    try:
        with run_lock(folder):
            return cast(RunInfo, read_json(folder / "run.json"))
    except (RunLockTimeout, FileNotFoundError):  # a run deleted after the file check: the next poll says so
        return None


def run_changed(info: RunInfo, saved: RunInfo) -> bool:
    """Something new happened: the status changed, or a submit, a resume, or another wait replaced the alarm.

    A save with nothing new (such as `pskill current`) keeps the alarm, so the wait goes on. An early end
    therefore never leaves this wait's alarm behind to silence the Stop hook.
    """
    return info["status"] != saved["status"] or info.get("wait_until") != saved["wait_until"]


def change_text(project: Project, info: RunInfo) -> str:
    run_id = info["run_id"]
    if info["status"] != "active":
        return f"Run {run_id} is now {info['status']}.\n"
    return f"Run {run_id} changed. Continue it: run `{runner_command(project)} current {run_id}`.\n"


def start_wait(project: Project, run_id: str, reason: str, now: datetime) -> RunInfo:
    """Record a wait that ends `wait_minutes` after `now`. Return the `run.json` that it saved.

    The waits of one block end after `max_wait_minutes` with no new answer: then the Stop hook counts the
    stops again, and a stuck run still pauses. A wait that starts more than `wait_minutes` after the last
    alarm starts a new count: the agent worked between the two waits.
    """
    with run_lock(run_folder(project, run_id)):
        run = Run.load(project, run_id)
        run.require_status(("active",), "wait")
        if not run.adapter.wakes_after_background_command:
            raise RunError(
                f"Run {run_id} runs in {run.info['harness']}, and {run.info['harness']} does not wake the agent when "
                f"a background command ends, so nothing would wake you after a wait. Continue the run: run "
                f"`{runner_command(project)} current {run_id}`."
            )
        waits_since = run.info.get("waits_since")
        last_alarm = run.info.get("wait_until")
        wait_length = timedelta(minutes=project.config.wait_minutes)
        if last_alarm is not None and now - parse_timestamp(last_alarm) > wait_length:
            waits_since = None  # the agent worked between the two waits, so the waits start a new count
        max_wait = timedelta(minutes=project.config.max_wait_minutes)
        if waits_since is not None and now - parse_timestamp(waits_since) >= max_wait:
            raise RunError(
                f"The waits of run {run_id} lasted {project.config.max_wait_minutes} minutes with nothing new, so "
                f"no new wait starts. Check the background work, then continue the run: run "
                f"`{runner_command(project)} current {run_id}`."
            )
        run.info["wait_reason"] = reason
        run.info["wait_started_at"] = timestamp(now)
        run.info["wait_until"] = timestamp(now + wait_length)
        run.info["waits_since"] = waits_since or timestamp(now)
        # The hook can count a stop before this write lands. `max_wait_minutes` still bounds a stuck run.
        run.info["stop_blocks"] = 0
        run.save()
    return run.info


def is_waiting(info: RunInfo, now: datetime) -> bool:
    """True while the alarm of a wait has not rung. A killed wait process holds the run only until then."""
    wait_until = info.get("wait_until")
    return info["status"] == "active" and wait_until is not None and now < parse_timestamp(wait_until)
