"""Tests for the `pskill.py` entry script."""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from pskill_runner.install import CACHE_VARIABLE, DEV_PIN, Pin, cache_folder, pin_entry_script
from pskill_runner.release import build_release_archive

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


# --- the pinned entry script of a project (SPEC.md D20) ------------------------------------------


def run_entry(script: Path, *arguments: str, cache: Path) -> subprocess.CompletedProcess[str]:
    """Run an entry script like a project does: alone, with no runner next to it."""
    environment = {**os.environ, CACHE_VARIABLE: str(cache)}
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=script.parent,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def pinned_project_script(tmp_path: Path, pin: Pin) -> Path:
    script = tmp_path / "project" / ".pskill" / "pskill.py"
    script.parent.mkdir(parents=True)
    script.write_text(pin_entry_script(ENTRY_SCRIPT.read_text(encoding="utf-8"), pin), encoding="utf-8")
    return script


def release_pin(tmp_path: Path) -> tuple[Pin, Path]:
    from pskill_runner import __version__

    archive = build_release_archive(REPOSITORY_ROOT, tmp_path / "release" / "pskill.zip")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return Pin(version=__version__, url=archive.as_uri(), sha256=digest), archive


def test_a_pinned_script_downloads_its_release_once_and_then_runs_from_the_cache(tmp_path: Path) -> None:
    from pskill_runner import __version__

    pin, archive = release_pin(tmp_path)
    script = pinned_project_script(tmp_path, pin)
    cache = tmp_path / "cache"

    first = run_entry(script, "--version", cache=cache)
    archive.unlink()  # no download is possible now
    second = run_entry(script, "--version", cache=cache)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == f"pskill {__version__}"
    assert (cache_folder(pin, cache) / "pskill_runner" / "cli.py").is_file()
    assert sorted(path.name for path in cache.iterdir()) == [cache_folder(pin, cache).name]


def test_a_download_that_does_not_match_the_pinned_hash_never_runs(tmp_path: Path) -> None:
    pin, _ = release_pin(tmp_path)
    script = pinned_project_script(tmp_path, Pin(pin.version, pin.url, "0" * 64))
    cache = tmp_path / "cache"

    result = run_entry(script, "--version", cache=cache)

    assert result.returncode != 0
    assert "does not match" in result.stderr
    assert not cache_folder(Pin(pin.version, pin.url, "0" * 64), cache).exists()


def test_a_failed_download_names_the_url(tmp_path: Path) -> None:
    pin, archive = release_pin(tmp_path)
    archive.unlink()
    script = pinned_project_script(tmp_path, pin)

    result = run_entry(script, "--version", cache=tmp_path / "cache")

    assert result.returncode != 0
    assert "could not download" in result.stderr
    assert pin.url in result.stderr


def test_the_dev_pin_runs_the_checkout_that_holds_the_project(tmp_path: Path) -> None:
    from pskill_runner import __version__

    checkout = tmp_path / "checkout"
    shutil.copytree(REPOSITORY_ROOT / "pskill_runner", checkout / "pskill_runner")
    script = checkout / ".pskill" / "pskill.py"
    script.parent.mkdir(parents=True)
    script.write_text(pin_entry_script(ENTRY_SCRIPT.read_text(encoding="utf-8"), DEV_PIN), encoding="utf-8")

    result = run_entry(script, "--version", cache=tmp_path / "cache")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"pskill {__version__}"
    assert not (tmp_path / "cache").exists()
