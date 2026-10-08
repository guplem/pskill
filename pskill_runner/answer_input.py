"""Read the agent's answer from stdin without ever hanging, or from a file (SPEC.md section 7.3)."""

import threading
from pathlib import Path
from typing import TextIO

DEFAULT_TIMEOUT_S = 10.0


class AnswerInputError(Exception):
    """No usable answer arrived on stdin or in the answer file."""


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


def read_answer_file(path: Path) -> str:
    """Read the answer from a file, for `submit --file`. A byte order mark at the start is dropped."""
    if not path.is_file():
        raise AnswerInputError(f"No answer file at {path}. Write the answer there first.")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (UnicodeDecodeError, OSError) as error:  # for example UTF-16, which Windows PowerShell 5.1 writes
        raise AnswerInputError(f"Could not read the answer file {path} ({error}). Save it as UTF-8 text.") from error
    if not text.strip():
        raise AnswerInputError(f"The answer file {path} is empty. Write the answer there first.")
    return text
