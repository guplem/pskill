"""Tests for pskill_runner.answer_input."""

import io
import os
import time

import pytest

from pskill_runner.answer_input import AnswerInputError, read_answer


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
