"""Tests for pskill_runner.hosted_site: the files that GitHub Pages serves for the hosted viewer."""

import runpy
import sys
import zipfile
from pathlib import Path

import pytest

from pskill_runner.hosted_site import RUNNER_ARCHIVE, build_hosted_site

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def test_the_site_holds_the_viewer_and_the_runner_without_caches(tmp_path: Path) -> None:
    site = build_hosted_site(REPOSITORY_ROOT, tmp_path / "site")

    assert {"index.html", "app.js", "hosted.js", "style.css", RUNNER_ARCHIVE} <= {path.name for path in site.iterdir()}
    with zipfile.ZipFile(site / RUNNER_ARCHIVE) as archive:
        names = archive.namelist()
    assert "pskill_runner/viewer_api.py" in names
    assert all(name.startswith("pskill_runner/") and "__pycache__" not in name for name in names)


# runpy warns that this test file has already imported the module. That is harmless here.
@pytest.mark.filterwarnings("ignore:'pskill_runner.hosted_site' found in sys.modules:RuntimeWarning")
def test_running_the_module_builds_the_site_in_the_given_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPOSITORY_ROOT)
    monkeypatch.setattr(sys, "argv", ["hosted_site.py", str(tmp_path / "_site")])

    runpy.run_module("pskill_runner.hosted_site", run_name="__main__")

    assert capsys.readouterr().out.strip() == str(tmp_path / "_site")
    assert (tmp_path / "_site" / "index.html").is_file()
