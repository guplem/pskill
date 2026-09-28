"""Read the agent's answer from stdin, without ever hanging (SPEC.md section 7.3)."""

import threading
from typing import TextIO

DEFAULT_TIMEOUT_S = 10.0


class AnswerInputError(Exception):
    """No usable answer arrived on stdin."""


def read_answer(stream: TextIO, timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    """Read all of stdin. Fail at once on a terminal, and after `timeout_s` when no data arrives."""
    if stream.isatty():
        raise AnswerInputError("No answer on stdin. Send the answer in the same command, as the packet shows.")
    result: list[str] = []
    reader = threading.Thread(target=lambda: result.append(stream.read()), daemon=True)
    reader.start()
    reader.join(timeout_s)
    if reader.is_alive():
        raise AnswerInputError(f"No answer arrived on stdin within {timeout_s:g} s. Send it as the packet shows.")
    if not result or not result[0].strip():
        raise AnswerInputError("No answer on stdin. Send the answer in the same command, as the packet shows.")
    return result[0]
