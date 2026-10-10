"""Helpers for the tests of the example skills' scripts: load a script, and fake the commands that it runs."""

import importlib.util
import io
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SKILLS_FOLDER = Path(__file__).resolve().parent.parent / ".pskill" / "skills"


def load_skill_script(skill_id: str, script_name: str) -> ModuleType:
    """Import `.pskill/skills/<skill_id>/scripts/<script_name>.py` as a module.

    `uv run` puts the script's folder on sys.path, so a script imports a helper of its folder (`github_rest`) by its
    plain name. The import here does the same, and drops the helper that an earlier skill imported.
    """
    scripts_folder = SKILLS_FOLDER / skill_id / "scripts"
    spec = importlib.util.spec_from_file_location(
        f"{skill_id.replace('-', '_')}_{script_name}", scripts_folder / f"{script_name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop("github_rest", None)
    sys.path.insert(0, str(scripts_folder))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts_folder))
        sys.modules.pop("github_rest", None)
    return module


class FakeShell:
    """Answers each command of a script from tables, and records every command in order.

    A command matches the first key that its text (the words joined by spaces) starts with. A command in `failing`
    fails: `run` raises with `failure_stderr` as the error text, and `succeeds` returns False. Any other command
    succeeds with an empty output.
    """

    def __init__(self, outputs: dict[str, str] | None = None, failing: list[str] | None = None) -> None:
        self.outputs: dict[str, str] = outputs or {}
        self.failing: list[str] = failing or []
        self.commands: list[str] = []
        self.failure_stderr = "failed"

    def fails(self, text: str) -> bool:
        return any(text.startswith(prefix) for prefix in self.failing)

    def run(self, command: list[str]) -> str:
        text = " ".join(command)
        self.commands.append(text)
        if self.fails(text):
            raise subprocess.CalledProcessError(1, command, stderr=self.failure_stderr)
        return next((output for prefix, output in self.outputs.items() if text.startswith(prefix)), "")

    def succeeds(self, command: list[str]) -> bool:
        text = " ".join(command)
        self.commands.append(text)
        return not self.fails(text)

    def api(self, path: str, method: str = "GET", body: Any = None) -> Any:
        """Fake `gh_api`: record `gh api <METHOD> <path>` (with the JSON body), and parse the matching output."""
        text = f"gh api {method} {path}" + ("" if body is None else f" {json.dumps(body, sort_keys=True)}")
        self.commands.append(text)
        if self.fails(text):
            raise SystemExit(f"`{text}` failed: {self.failure_stderr}")
        output = next((output for prefix, output in self.outputs.items() if text.startswith(prefix)), "")
        return json.loads(output) if output.strip() else None

    def api_pages(self, path: str, key: str | None = None, stop: Callable[[list[Any]], bool] | None = None) -> Any:
        """Fake `gh_api_pages`: one GET of the path, whose output is one page: a list, or an object with `key`."""
        reply = self.api(path)
        if reply is None:
            return []
        return reply[key] if key is not None else reply

    def ran(self, prefix: str) -> bool:
        return any(command.startswith(prefix) for command in self.commands)


def install_shell(monkeypatch: pytest.MonkeyPatch, script: ModuleType, shell: FakeShell) -> FakeShell:
    """Route the script's `run`, `succeeds`, `gh_api`, and `gh_api_pages` helpers (the ones that it has) to the fake."""
    for name, fake in (
        ("run", shell.run),
        ("succeeds", shell.succeeds),
        ("gh_api", shell.api),
        ("gh_api_pages", shell.api_pages),
    ):
        if hasattr(script, name):
            monkeypatch.setattr(script, name, fake)
    return shell


def run_main(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], script: ModuleType, stdin: Any = None
) -> Any:
    """Run the script's `main` with `stdin` as its JSON input. Return its printed JSON."""
    monkeypatch.setattr("sys.stdin", io.StringIO("" if stdin is None else json.dumps(stdin)))
    script.main()
    return json.loads(capsys.readouterr().out)
