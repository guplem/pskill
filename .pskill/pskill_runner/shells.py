"""The shell forms of a command that sends text on stdin (SPEC.md section 7.3).

Both forms are literal: the shell changes nothing inside the text (no quote, `$`, or backtick handling).
"""

import os
import sys
from collections.abc import Mapping

HEREDOC_MARKER = "PSKILL"


def detect_shell(environment: Mapping[str, str] | None = None, platform: str | None = None) -> str:
    """Return "bash" or "powershell": the shell that most likely runs the agent's commands."""
    environment = os.environ if environment is None else environment
    platform = sys.platform if platform is None else platform
    if not platform.startswith("win"):
        return "bash"
    return "bash" if "MSYSTEM" in environment else "powershell"


def stdin_command(shell: str, command: str, text: str) -> str:
    """Build `command` with `text` on its stdin, in the given shell's literal form."""
    if shell == "powershell":
        # The first statement makes Windows PowerShell 5.1 send UTF-8 instead of ASCII.
        return f"$OutputEncoding = [System.Text.UTF8Encoding]::new($false); @'\n{text}\n'@ | {command}"
    return f"{command} <<'{HEREDOC_MARKER}'\n{text}\n{HEREDOC_MARKER}"
