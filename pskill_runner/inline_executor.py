"""How the runner executes `script` blocks and child skills of `call` blocks.

The engine talks to an executor instead of calling subprocess directly. A real run uses
`RealExecutor`. `pskill test` uses a mock executor that returns recorded results instead
(see `skill_tests.py`), so skill tests never run real scripts or real child skills.
"""

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class ScriptResult:
    exit_code: int | None  # None when the command did not start or timed out
    stdout: str
    stderr: str
    duration_ms: int
    problem: str | None = None  # why the command did not run to its end, in plain words


@dataclass(frozen=True)
class CallResult:
    status: str
    outputs: dict[str, Any]


class InlineExecutor(Protocol):
    def run_script(
        self,
        block_id: str,
        argv: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout_s: int,
        stdin_text: str | None = None,
    ) -> ScriptResult:
        """Run one command. It reads `stdin_text` on stdin, or an empty stdin when there is none."""
        ...

    def call_result(self, block_id: str, skill_id: str, inputs: dict[str, Any]) -> CallResult | None:
        """A ready result for a call, or None to run the child skill for real."""
        ...


class RealExecutor:
    """Runs real commands and real child skills."""

    def run_script(
        self,
        block_id: str,
        argv: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout_s: int,
        stdin_text: str | None = None,
    ) -> ScriptResult:
        started = time.monotonic()
        # On Windows, a bare name such as "gh" or "npx" must be resolved to "gh.exe" or "npx.cmd" first.
        program = shutil.which(argv[0]) or argv[0]
        try:
            completed = subprocess.run(
                [program, *argv[1:]],
                cwd=cwd,
                env=env,
                input=stdin_text or "",
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                check=False,
            )
        except FileNotFoundError:
            return ScriptResult(None, "", "", elapsed_ms(started), problem=f"the command {argv[0]!r} was not found")
        except subprocess.TimeoutExpired:
            return ScriptResult(None, "", "", elapsed_ms(started), problem=f"it did not finish within {timeout_s} s")
        return ScriptResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=elapsed_ms(started),
        )

    def call_result(self, block_id: str, skill_id: str, inputs: dict[str, Any]) -> CallResult | None:
        return None


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
