"""Tests for pskill_runner.shells."""

from pskill_runner.shells import detect_shell, stdin_command


def test_bash_is_used_outside_windows() -> None:
    assert detect_shell(environment={}, platform="linux") == "bash"
    assert detect_shell(environment={}, platform="darwin") == "bash"


def test_git_bash_on_windows_uses_the_bash_form() -> None:
    assert detect_shell(environment={"MSYSTEM": "MINGW64"}, platform="win32") == "bash"


def test_other_windows_shells_use_the_powershell_form() -> None:
    assert detect_shell(environment={}, platform="win32") == "powershell"


def test_the_bash_form_is_a_literal_heredoc() -> None:
    command = stdin_command("bash", "uv run .pskill/pskill.py submit r-1", "status: finished\nplan: |\n  a $b `c`")

    assert command == ("uv run .pskill/pskill.py submit r-1 <<'PSKILL'\nstatus: finished\nplan: |\n  a $b `c`\nPSKILL")


def test_the_powershell_form_is_a_literal_here_string_with_utf8() -> None:
    command = stdin_command("powershell", "uv run .pskill/pskill.py submit r-1", "status: finished")

    assert command == (
        "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); @'\n"
        "status: finished\n"
        "'@ | uv run .pskill/pskill.py submit r-1"
    )
