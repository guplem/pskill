"""The release archive: a zip of the vendored files, published on every tagged release (SPEC.md M6).

Build it with: uv run python -m pskill_runner.release dist/pskill.zip
`init` and `update` accept the archive (a file or a URL) as their source.
"""

import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from pskill_runner.vendoring import vendored_file_map

# The entry script pskill.py repeats this URL, because it must work before the runner is installed.
DEFAULT_RELEASE_URL = "https://github.com/guplem/pskill/releases/latest/download/pskill.zip"
RELEASE_URL_VARIABLE = "PSKILL_RELEASE_URL"


def release_url() -> str:
    """The latest release archive, unless PSKILL_RELEASE_URL names another one (a mirror or a pinned version)."""
    return os.environ.get(RELEASE_URL_VARIABLE, DEFAULT_RELEASE_URL)


def build_release_archive(source_root: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_path, source_path in vendored_file_map(source_root).items():
            archive.write(source_path, relative_path)
    return output_path


def is_archive_source(source: str) -> bool:
    return source.endswith(".zip") or source.startswith(("http://", "https://", "file://"))


def unpack_archive(source: str) -> Path:
    """Download (when it is a URL) and unpack a release archive. Return the unpacked folder."""
    folder = Path(tempfile.mkdtemp(prefix="pskill-release-"))
    archive_path = folder / "pskill.zip"
    if source.startswith(("http://", "https://", "file://")):
        urllib.request.urlretrieve(source, archive_path)
    else:
        archive_path.write_bytes(Path(source).read_bytes())
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(folder / "pskill")
    return folder / "pskill"


if __name__ == "__main__":
    print(build_release_archive(Path.cwd(), Path(sys.argv[1])))
