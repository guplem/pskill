"""The hosted viewer for GitHub Pages: the viewer files, plus the runner as `pskill_runner.zip` (SPEC.md 14.3).

Build it with: uv run python -m pskill_runner.hosted_site _site
The page finds no local server, so it loads `pskill_runner.zip` into Pyodide and answers its API in the browser.
"""

import shutil
import sys
import zipfile
from pathlib import Path

from pskill_runner.release import release_file_map

RUNNER_ARCHIVE = "pskill_runner.zip"


def build_hosted_site(source_root: Path, output_folder: Path) -> Path:
    """Copy `viewer/` to the site's root, and pack `pskill_runner/` next to it, without caches."""
    files = release_file_map(source_root)
    output_folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_folder / RUNNER_ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_path, source_path in files.items():
            if relative_path.startswith("pskill_runner/"):
                archive.write(source_path, relative_path)
            elif relative_path.startswith("viewer/"):
                target = output_folder / relative_path.removeprefix("viewer/")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_path, target)
    return output_folder


if __name__ == "__main__":
    print(build_hosted_site(Path.cwd(), Path(sys.argv[1])))
