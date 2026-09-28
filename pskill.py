# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "jinja2>=3.1",
#     "jsonschema>=4.21",
#     "pyyaml>=6",
# ]
# ///
"""Entry point of the pskill runner. Run it with: uv run pskill.py <command>

Python puts this file's folder on the import path, so the `pskill_runner` package next to it is
importable without an install step. For the first install, this file can also run alone, straight
from a URL: then it downloads the latest release archive and runs the runner from there.
"""

import os
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

# pskill_runner/release.py holds the same URL; a test checks that they are equal.
DEFAULT_RELEASE_URL = "https://github.com/guplem/pskill/releases/latest/download/pskill.zip"


def download_runner() -> Path:
    """Download and unpack the release archive into a temp folder. Return that folder."""
    url = os.environ.get("PSKILL_RELEASE_URL", DEFAULT_RELEASE_URL)
    print(f"pskill: the runner is not next to this script, so it downloads it from {url}", file=sys.stderr)
    folder = Path(tempfile.mkdtemp(prefix="pskill-"))
    archive_path = folder / "pskill.zip"
    urllib.request.urlretrieve(url, archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(folder / "pskill")
    return folder / "pskill"


def runner_main() -> Callable[[], int]:
    try:
        from pskill_runner.cli import main
    except ModuleNotFoundError as error:
        if error.name != "pskill_runner":
            raise
        sys.path.insert(0, str(download_runner()))
        from pskill_runner.cli import main
    return main


if __name__ == "__main__":
    sys.exit(runner_main()())
