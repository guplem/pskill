"""`pskill wait`: the agent waits on background work, and the Stop hook stays quiet (SPEC.md section 9.2).

A wait is an alarm. It records `wait_until` in `run.json`, so the Stop hook allows the stop with no
message until then. The wait holds the run lock only to change `run.json`, never while it sleeps.
"""

from datetime import datetime, timedelta

from pskill_runner.engine import Run, run_folder
from pskill_runner.project import Project
from pskill_runner.run_store import run_lock, timestamp


def start_wait(project: Project, run_id: str, reason: str, now: datetime) -> str:
    """Record a wait that ends `wait_minutes` after `now`. Return the `updated_at` that it saved."""
    with run_lock(run_folder(project, run_id)):
        run = Run.load(project, run_id)
        run.info["wait_reason"] = reason
        run.info["wait_started_at"] = timestamp(now)
        run.info["wait_until"] = timestamp(now + timedelta(minutes=project.config.wait_minutes))
        run.info["waits_since"] = run.info.get("waits_since") or timestamp(now)
        run.save()
    return run.info["updated_at"]
