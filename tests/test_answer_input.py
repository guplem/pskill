"""Tests for pskill_runner.answer_input."""

import io
import os
import time
from pathlib import Path

import pytest

from pskill_runner.answer_input import AnswerInputError, read_answer, read_answer_file


def test_read_answer_returns_the_piped_text() -> None:
    assert read_answer(io.StringIO("status: finished\n"), timeout_s=1) == "status: finished\n"


class TerminalStream(io.StringIO):
    """A stream that says it is a terminal, as stdin is when nothing is piped in."""

    def isatty(self) -> bool:
        return True


def test_a_terminal_is_refused_without_reading_it() -> None:
    with pytest.raises(AnswerInputError, match="No answer on stdin"):
        read_answer(TerminalStream("status: finished\n"), timeout_s=1)


def test_an_empty_answer_is_an_error() -> None:
    with pytest.raises(AnswerInputError, match="No answer"):
        read_answer(io.StringIO(""), timeout_s=1)


def test_a_stream_that_never_ends_fails_after_the_timeout() -> None:
    read_end, write_end = os.pipe()
    never_ending_stream = open(read_end, encoding="utf-8")  # noqa: SIM115 (closed below, after the writer)
    started = time.monotonic()

    with pytest.raises(AnswerInputError, match="No answer"):
        read_answer(never_ending_stream, timeout_s=0.3)
    elapsed_s = time.monotonic() - started

    # Close the writing end first: the background reader then gets end-of-file and stops.
    # On Windows, closing the reading end while a thread still reads it would block.
    os.close(write_end)
    time.sleep(0.2)
    never_ending_stream.close()
    assert elapsed_s < 5


def test_read_answer_file_returns_the_file_text(tmp_path: Path) -> None:
    answer_file = tmp_path / "answer.yaml"
    answer_file.write_text("reason: it's 5 o'clock, C:\\temp costs $5\n", encoding="utf-8")

    assert read_answer_file(answer_file) == "reason: it's 5 o'clock, C:\\temp costs $5\n"


def test_read_answer_file_drops_a_byte_order_mark(tmp_path: Path) -> None:
    answer_file = tmp_path / "answer.yaml"
    answer_file.write_text("status: finished\n", encoding="utf-8-sig")

    assert read_answer_file(answer_file) == "status: finished\n"


def test_read_answer_file_refuses_a_file_that_is_not_utf8(tmp_path: Path) -> None:
    answer_file = tmp_path / "answer.yaml"
    answer_file.write_text("status: finished\n", encoding="utf-16")  # what Windows PowerShell 5.1 writes with >

    with pytest.raises(AnswerInputError, match="Save it as UTF-8 text"):
        read_answer_file(answer_file)


def test_read_answer_file_refuses_a_file_that_cannot_be_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    answer_file = tmp_path / "answer.yaml"
    answer_file.write_text("status: finished\n", encoding="utf-8")

    def locked_file(self: Path, encoding: str) -> str:
        raise PermissionError("the file is locked")

    monkeypatch.setattr(Path, "read_text", locked_file)

    with pytest.raises(AnswerInputError, match="the file is locked"):
        read_answer_file(answer_file)


def test_read_answer_file_refuses_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(AnswerInputError, match="No answer file at"):
        read_answer_file(tmp_path / "missing.yaml")


def test_read_answer_file_refuses_an_empty_file(tmp_path: Path) -> None:
    answer_file = tmp_path / "answer.yaml"
    answer_file.write_text("  \n", encoding="utf-8")

    with pytest.raises(AnswerInputError, match="is empty"):
        read_answer_file(answer_file)
