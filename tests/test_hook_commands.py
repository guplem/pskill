"""The hook commands that sync writes, run for real through the system shell (sh, or cmd on Windows)."""

import os
import subprocess
from pathlib import Path

import pytest

from pskill_runner import claude_code, codex
from pskill_runner.hook_settings import SHARED_HOOKS

FAKE_RUNNER = "import sys\nprint('ran:', ' '.join(sys.argv[1:]))\n"
HOOKS = [
    pytest.param(claude_code.PSKILL_HOOKS, "claude-code", id="claude-code"),
    pytest.param(codex.PSKILL_HOOKS, "codex", id="codex"),
    pytest.param(SHARED_HOOKS, "auto", id="shared"),
]


def command_of(hooks: dict[str, dict[str, object]], event: str) -> str:
    group = hooks[event]
    handlers = group["hooks"]
    assert isinstance(handlers, list)
    return str(handlers[0]["command"])


def run_command(command: str, cwd: Path, project_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run a hook command the way an agent app does: through a shell, from a folder of the project."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    return subprocess.run(
        command, shell=True, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=180
    )


def make_repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    subfolder = tmp_path / "src"
    subfolder.mkdir()
    return subfolder


@pytest.mark.parametrize(("hooks", "harness"), HOOKS)
@pytest.mark.parametrize("event", ["Stop", "SessionStart"])
def test_a_hook_does_nothing_when_the_runner_is_missing(
    tmp_path: Path, hooks: dict[str, dict[str, object]], harness: str, event: str
) -> None:
    subfolder = make_repository(tmp_path)

    result = run_command(command_of(hooks, event), cwd=subfolder, project_dir=tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(("hooks", "harness"), HOOKS)
def test_a_hook_runs_the_runner_when_it_is_there(
    tmp_path: Path, hooks: dict[str, dict[str, object]], harness: str
) -> None:
    subfolder = make_repository(tmp_path)
    (tmp_path / ".pskill").mkdir()
    (tmp_path / ".pskill" / "pskill.py").write_text(FAKE_RUNNER, encoding="utf-8")

    stop = run_command(command_of(hooks, "Stop"), cwd=subfolder, project_dir=tmp_path)
    session_start = run_command(command_of(hooks, "SessionStart"), cwd=subfolder, project_dir=tmp_path)

    assert stop.returncode == 0, stop.stderr
    assert f"ran: hook stop --harness {harness}" in stop.stdout
    assert f"ran: hook session-start --harness {harness}" in session_start.stdout


@pytest.mark.parametrize(("hooks", "harness"), HOOKS)
def test_a_hook_command_reads_the_same_in_bash_powershell_and_cmd(
    hooks: dict[str, dict[str, object]], harness: str
) -> None:
    for event in ("Stop", "SessionStart"):
        command = command_of(hooks, event)
        inner = command.split('"', 1)[1].rsplit('"', 1)[0]
        # Inside the one double-quoted argument: nothing that bash, PowerShell, or cmd would change.
        assert not any(character in inner for character in '$`\\"%!^')
