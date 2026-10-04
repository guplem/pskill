# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "jinja2>=3.1",
#     "jsonschema>=4.21",
#     "pyyaml>=6",
#     "ruamel-yaml>=0.18",
# ]
# ///
"""Entry point of the pskill runner. A project runs it with: uv run .pskill/pskill.py <command>

A project commits only this file. Its pin (the three PSKILL_ lines) names one release of the runner.
The first call on a computer downloads that release once into a cache for the user, checks its
sha256, and unpacks it. Every later call runs the cached copy, with no network. `pskill update`
moves the pin. In the pskill repository, the runner package sits next to this file instead.
"""

import hashlib
import io
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

# The pin. `pskill init` and `pskill update` write these three lines. No version means the latest
# release (the first install runs this file alone, from a URL). "dev" runs the pskill checkout that
# holds this project: only the pskill repository uses it.
PSKILL_VERSION = ""
PSKILL_URL = ""
PSKILL_SHA256 = ""

# pskill_runner/release.py and pskill_runner/install.py hold the same values; tests check that they are equal.
DEFAULT_RELEASE_URL = "https://github.com/guplem/pskill/releases/latest/download/pskill.zip"
CACHE_VARIABLE = "PSKILL_CACHE_DIR"


def cache_root() -> Path:
    """Where the downloaded releases live: one folder per user, outside every project."""
    if os.environ.get(CACHE_VARIABLE):
        return Path(os.environ[CACHE_VARIABLE])
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "pskill"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "pskill"


def download(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url) as response:
            return bytes(response.read())
    except OSError as error:
        sys.exit(f"pskill: could not download the runner from {url}: {error}")


def pinned_runner() -> Path:
    """The cached release of the pin. Download, check, and unpack it the first time."""
    folder = cache_root() / f"{PSKILL_VERSION}-{PSKILL_SHA256[:12]}"
    if (folder / "pskill_runner").is_dir():
        return folder
    data = download(PSKILL_URL)
    if hashlib.sha256(data).hexdigest() != PSKILL_SHA256:
        sys.exit(f"pskill: the download from {PSKILL_URL} does not match the pinned sha256, so it never runs.")
    folder.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{folder.name}-", dir=folder.parent))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(staging)
    try:
        staging.rename(folder)  # atomic: a parallel call sees the whole folder or none of it
    except OSError:  # another call unpacked the same release first
        shutil.rmtree(staging, ignore_errors=True)
    return folder


def latest_runner() -> Path:
    """The latest release, in a temp folder: only the first install runs this file with no pin."""
    url = os.environ.get("PSKILL_RELEASE_URL", DEFAULT_RELEASE_URL)
    print(f"pskill: this script has no pinned runner, so it downloads the latest one from {url}", file=sys.stderr)
    folder = Path(tempfile.mkdtemp(prefix="pskill-"))
    with zipfile.ZipFile(io.BytesIO(download(url))) as archive:
        archive.extractall(folder)
    return folder


def runner_folder() -> Path:
    if PSKILL_VERSION == "dev":
        return Path(__file__).resolve().parent.parent
    return pinned_runner() if PSKILL_VERSION else latest_runner()


def runner_main() -> Callable[[], int]:
    try:
        from pskill_runner.cli import main
    except ModuleNotFoundError as error:
        if error.name != "pskill_runner":
            raise
        sys.path.insert(0, str(runner_folder()))
        from pskill_runner.cli import main
    return main


if __name__ == "__main__":
    sys.exit(runner_main()())
