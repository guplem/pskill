"""Tests for pskill_runner.inline_executor: running real commands."""

import os
import sys
from pathlib import Path

from pskill_runner.inline_executor import RealExecutor


def test_a_command_that_ends_gives_its_exit_code_and_output(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(4)"]

    result = RealExecutor().run_script("check", argv, tmp_path, dict(os.environ), timeout_s=30)

    assert (result.exit_code, result.stdout, result.stderr, result.problem) == (4, "out\n", "err\n", None)


def test_a_command_that_does_not_exist_is_a_problem_not_a_crash(tmp_path: Path) -> None:
    argv = ["pskill-no-such-command", "--help"]

    result = RealExecutor().run_script("check", argv, tmp_path, dict(os.environ), timeout_s=30)

    assert result.exit_code is None
    assert result.problem == "the command 'pskill-no-such-command' was not found"


def test_a_command_reads_the_given_text_on_stdin(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"]

    result = RealExecutor().run_script("check", argv, tmp_path, dict(os.environ), timeout_s=30, stdin_text="hello")

    assert result.stdout == "HELLO\n"


def test_a_command_without_stdin_text_reads_an_empty_stdin(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"]

    result = RealExecutor().run_script("check", argv, tmp_path, dict(os.environ), timeout_s=30)

    assert result.stdout == "''\n"
