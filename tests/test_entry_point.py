"""Tests for the `pskill.py` entry script."""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
ENTRY_SCRIPT = REPOSITORY_ROOT / "pskill.py"


def read_script_dependencies(script_text: str) -> list[str]:
    """Return the dependencies declared in the script's PEP 723 metadata block."""
    block = re.search(r"^# /// script\n(?P<body>(?:#.*\n)+?)# ///$", script_text, re.MULTILINE)
    assert block is not None, "pskill.py has no PEP 723 metadata block"
    toml_text = "\n".join(line.removeprefix("#").removeprefix(" ") for line in block["body"].splitlines())
    dependencies: list[str] = tomllib.loads(toml_text)["dependencies"]
    return dependencies


def test_version_flag_prints_the_package_version() -> None:
    from pskill_runner import __version__

    result = subprocess.run(
        [sys.executable, str(ENTRY_SCRIPT), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"pskill {__version__}"


def test_script_dependencies_match_the_project_dependencies() -> None:
    script_dependencies = read_script_dependencies(ENTRY_SCRIPT.read_text(encoding="utf-8"))
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert sorted(script_dependencies) == sorted(pyproject["project"]["dependencies"])


def test_the_project_version_equals_the_runner_version() -> None:
    from pskill_runner import __version__

    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == __version__
