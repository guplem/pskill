"""Tests for the release archive and the one-command install (SPEC.md milestone M6)."""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from pskill_runner.release import build_release_archive
from pskill_runner.vendoring import vendored_file_map

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def run_python(script: Path, *arguments: str, cwd: Path, extra_environment: dict[str, str] | None = None) -> str:
    environment = {**os.environ, **(extra_environment or {})}
    environment.pop("PYTHONPATH", None)  # the script must find the runner on its own
    result = subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_the_archive_holds_exactly_the_vendored_files(tmp_path: Path) -> None:
    archive = build_release_archive(REPOSITORY_ROOT, tmp_path / "pskill.zip")

    with zipfile.ZipFile(archive) as opened:
        names = set(opened.namelist())
    assert names == set(vendored_file_map(REPOSITORY_ROOT))
    assert "pskill.py" in names and "viewer/index.html" in names


def test_init_from_the_archive_installs_a_working_runner(tmp_path: Path) -> None:
    archive = build_release_archive(REPOSITORY_ROOT, tmp_path / "pskill.zip")
    project_root = tmp_path / "project"
    project_root.mkdir()

    run_python(REPOSITORY_ROOT / "pskill.py", "init", "--from", str(archive), cwd=project_root)

    assert (project_root / ".pskill" / "pskill_runner" / "engine.py").is_file()
    assert "pskill" in run_python(project_root / ".pskill" / "pskill.py", "--version", cwd=project_root)


def test_the_entry_script_alone_downloads_the_release_and_installs_it(tmp_path: Path) -> None:
    """What `uv run https://raw.githubusercontent.com/guplem/pskill/main/pskill.py init` does."""
    archive = build_release_archive(REPOSITORY_ROOT, tmp_path / "pskill.zip")
    lone_script_folder = tmp_path / "download"
    lone_script_folder.mkdir()
    lone_script = Path(shutil.copy(REPOSITORY_ROOT / "pskill.py", lone_script_folder))
    project_root = tmp_path / "project"
    project_root.mkdir()

    run_python(lone_script, "init", cwd=project_root, extra_environment={"PSKILL_RELEASE_URL": archive.as_uri()})

    assert (project_root / ".pskill" / "pskill.py").is_file()
    assert (project_root / ".pskill" / "viewer" / "index.html").is_file()
    assert (project_root / ".claude" / "skills" / "pskill" / "SKILL.md").is_file()


def test_the_entry_script_and_the_runner_name_the_same_release_url() -> None:
    from pskill_runner.release import DEFAULT_RELEASE_URL

    entry_script = (REPOSITORY_ROOT / "pskill.py").read_text(encoding="utf-8")

    assert f'DEFAULT_RELEASE_URL = "{DEFAULT_RELEASE_URL}"' in entry_script
