"""Tests for the release archive and the one-command install (SPEC.md milestone M6)."""

import io
import os
import runpy
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from pskill_runner import __version__
from pskill_runner.install import CACHE_VARIABLE, read_pin
from pskill_runner.release import (
    DEFAULT_RELEASE_URL,
    RELEASE_URL_VARIABLE,
    ReleaseError,
    build_release_archive,
    read_release,
    release_file_map,
    release_url,
    release_version,
)

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


def zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def test_the_archive_holds_the_runner_the_viewer_and_the_guide(tmp_path: Path) -> None:
    archive = build_release_archive(REPOSITORY_ROOT, tmp_path / "pskill.zip")

    with zipfile.ZipFile(archive) as opened:
        names = set(opened.namelist())
    assert names == set(release_file_map(REPOSITORY_ROOT))
    assert {"pskill.py", "AUTHORING.md", "pskill_runner/cli.py", "viewer/index.html"} <= names
    assert not any("__pycache__" in name for name in names)


def test_a_folder_without_the_runner_is_not_a_source(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="not a pskill source"):
        release_file_map(tmp_path)


def test_init_from_the_archive_installs_a_working_pinned_runner(tmp_path: Path) -> None:
    archive = build_release_archive(REPOSITORY_ROOT, tmp_path / "pskill.zip")
    project_root = tmp_path / "project"
    project_root.mkdir()
    cache = {CACHE_VARIABLE: str(tmp_path / "cache")}

    run_python(REPOSITORY_ROOT / "pskill.py", "init", "--from", str(archive), cwd=project_root, extra_environment=cache)

    assert not (project_root / ".pskill" / "pskill_runner").exists()
    version = run_python(project_root / ".pskill" / "pskill.py", "--version", cwd=project_root, extra_environment=cache)
    assert version.strip() == f"pskill {__version__}"


def test_the_entry_script_alone_downloads_the_release_and_installs_it(tmp_path: Path) -> None:
    """What `uv run https://raw.githubusercontent.com/guplem/pskill/main/pskill.py init` does."""
    archive = build_release_archive(REPOSITORY_ROOT, tmp_path / "pskill.zip")
    lone_script_folder = tmp_path / "download"
    lone_script_folder.mkdir()
    lone_script = Path(shutil.copy(REPOSITORY_ROOT / "pskill.py", lone_script_folder))
    project_root = tmp_path / "project"
    project_root.mkdir()
    environment = {RELEASE_URL_VARIABLE: archive.as_uri(), CACHE_VARIABLE: str(tmp_path / "cache")}

    run_python(lone_script, "init", cwd=project_root, extra_environment=environment)

    pin = read_pin((project_root / ".pskill" / "pskill.py").read_text(encoding="utf-8"))
    assert pin.version == __version__
    assert pin.url == archive.as_uri()
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


def test_a_release_is_read_from_a_path_or_a_file_url(tmp_path: Path) -> None:
    archive = build_release_archive(REPOSITORY_ROOT, tmp_path / "pskill.zip")

    assert read_release(str(archive)) == archive.read_bytes()
    assert read_release(archive.as_uri()) == archive.read_bytes()


def test_the_version_comes_from_the_runner_inside_the_archive(tmp_path: Path) -> None:
    archive = build_release_archive(REPOSITORY_ROOT, tmp_path / "pskill.zip")

    assert release_version(archive.read_bytes()) == __version__


@pytest.mark.parametrize(
    "data",
    [b"not a zip file", zip_bytes({"README.md": "hello"}), zip_bytes({"pskill_runner/__init__.py": "# empty\n"})],
    ids=["not a zip", "no runner", "no version"],
)
def test_an_archive_without_a_runner_version_is_not_a_release(data: bytes) -> None:
    with pytest.raises(ReleaseError, match="not a pskill release"):
        release_version(data)


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
        assert set(opened.namelist()) == set(release_file_map(REPOSITORY_ROOT))
