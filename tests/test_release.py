"""Tests for the release archive and the one-command install (SPEC.md milestone M6)."""

import os
import runpy
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from pskill_runner.release import (
    DEFAULT_RELEASE_URL,
    RELEASE_URL_VARIABLE,
    build_release_archive,
    is_archive_source,
    release_url,
    unpack_archive,
)
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
    entry_script = (REPOSITORY_ROOT / "pskill.py").read_text(encoding="utf-8")

    assert f'DEFAULT_RELEASE_URL = "{DEFAULT_RELEASE_URL}"' in entry_script


def test_the_release_url_is_the_latest_release_unless_the_variable_names_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RELEASE_URL_VARIABLE, raising=False)
    assert release_url() == DEFAULT_RELEASE_URL

    monkeypatch.setenv(RELEASE_URL_VARIABLE, "https://example.com/pskill-1.0.zip")
    assert release_url() == "https://example.com/pskill-1.0.zip"


def test_an_archive_source_is_a_zip_file_or_a_url() -> None:
    assert is_archive_source("dist/pskill.zip")
    assert is_archive_source("https://example.com/download")
    assert is_archive_source("file:///tmp/pskill")
    assert not is_archive_source("../pskill")


def test_unpack_archive_reads_a_local_file_and_a_file_url(tmp_path: Path) -> None:
    archive = build_release_archive(REPOSITORY_ROOT, tmp_path / "pskill.zip")

    for source in (str(archive), archive.as_uri()):
        unpacked = unpack_archive(source)

        assert unpacked.name == "pskill"
        assert set(vendored_file_map(unpacked)) == set(vendored_file_map(REPOSITORY_ROOT))
        shutil.rmtree(unpacked.parent)


# runpy warns that this test file has already imported the module. That is harmless here.
@pytest.mark.filterwarnings("ignore:'pskill_runner.release' found in sys.modules:RuntimeWarning")
def test_running_the_module_builds_the_archive_at_the_given_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output_path = tmp_path / "dist" / "pskill.zip"
    monkeypatch.chdir(REPOSITORY_ROOT)
    monkeypatch.setattr(sys, "argv", ["release.py", str(output_path)])

    runpy.run_module("pskill_runner.release", run_name="__main__")

    assert capsys.readouterr().out.strip() == str(output_path)
    with zipfile.ZipFile(output_path) as opened:
        assert set(opened.namelist()) == set(vendored_file_map(REPOSITORY_ROOT))
