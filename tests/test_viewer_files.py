"""Contract tests for the static viewer files and the launchers (their logic lives in viewer_data.py)."""

import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from pskill_runner.vendoring import vendored_file_map
from pskill_runner.viewer_data import BLOCK_TYPE_MEANINGS

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
VIEWER = REPOSITORY_ROOT / "viewer"


def test_the_page_loads_mermaid_from_a_pinned_cdn_version_with_an_integrity_hash() -> None:
    index = (VIEWER / "index.html").read_text(encoding="utf-8")

    assert re.search(r'src="https://cdn\.jsdelivr\.net/npm/mermaid@\d+\.\d+\.\d+/dist/mermaid\.min\.js"', index)
    assert 'integrity="sha384-' in index
    assert 'crossorigin="anonymous"' in index


def test_the_page_loads_its_two_fonts_from_google_fonts_with_system_fonts_as_the_fallback() -> None:
    index = (VIEWER / "index.html").read_text(encoding="utf-8")
    style = (VIEWER / "style.css").read_text(encoding="utf-8")

    assert re.search(
        r'href="https://fonts\.googleapis\.com/css2\?family=Manrope[^"]*IBM\+Plex\+Mono[^"]*display=swap"', index
    )
    assert '"Manrope", system-ui' in style
    assert '"IBM Plex Mono", ui-monospace' in style


def test_the_script_draws_the_steps_without_mermaid_and_never_inserts_run_text_as_html() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")

    assert "!window.mermaid" in script
    assert "Graph unavailable offline" in script
    assert '"step-card"' in script  # offline, the steps (or the blocks of a skill) are drawn as node-style cards
    assert "drawBlockList()" in script
    assert script.count("innerHTML") == 1  # only for Mermaid's own SVG output
    assert 'securityLevel: "strict"' in script


def test_the_panel_width_is_saved_in_local_storage_inside_try_catch() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")

    uses = script.count("localStorage")
    guarded = len(re.findall(r"try \{\n\s*(?:return )?[^\n]*localStorage", script))
    assert uses >= 2  # read and write the width
    assert guarded == uses  # a browser that blocks site data throws on every use


def test_the_markdown_and_the_json_tree_are_built_from_elements() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")

    assert "function markdown(" in script
    assert "function jsonTree(" in script
    for html_parser in ("insertAdjacentHTML", "outerHTML", "createContextualFragment", "DOMParser", "document.write"):
        assert html_parser not in script


def test_every_block_type_has_an_icon() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")
    icons = script[script.index("const BLOCK_ICONS = {") : script.index("};", script.index("const BLOCK_ICONS = {"))]

    for block_type in BLOCK_TYPE_MEANINGS:
        assert f"\n  {block_type}: [" in icons


def test_the_launchers_start_the_viewer_from_the_folder_above_them() -> None:
    for name in ("view.cmd", "view.command", "view.sh"):
        launcher = (REPOSITORY_ROOT / "launchers" / name).read_text(encoding="utf-8")
        assert "uv run pskill.py view" in launcher


def test_the_viewer_and_the_launchers_are_vendored() -> None:
    files = vendored_file_map(REPOSITORY_ROOT)

    assert {"viewer/index.html", "viewer/app.js", "viewer/style.css", "launchers/view.cmd"} <= set(files)


def test_the_view_command_serves_the_viewer_until_stopped(tmp_path: Path) -> None:
    (tmp_path / ".pskill" / "skills").mkdir(parents=True)
    process = subprocess.Popen(
        [sys.executable, str(REPOSITORY_ROOT / "pskill.py"), "view", "--port", "0", "--no-open"],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        assert process.stdout is not None
        first_line = process.stdout.readline()
        match = re.search(r"http://127\.0\.0\.1:(\d+)/", first_line)
        assert match is not None, first_line + (process.stderr.read() if process.stderr else "")
        with urllib.request.urlopen(f"{match[0]}api/runs", timeout=10) as response:
            assert response.status == 200
        with urllib.request.urlopen(match[0], timeout=10) as response:
            assert b"pskill viewer" in response.read()
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_the_skill_screen_offers_the_markdown_export_as_a_download() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")

    assert "Export as Markdown" in script
    assert "/export`" in script
    assert "exportLink.download" in script
