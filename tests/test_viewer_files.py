"""Contract tests for the static viewer files (their logic lives in viewer_data.py)."""

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from pskill_runner.release import release_file_map
from pskill_runner.skill_schema import BLOCK_SCHEMAS
from pskill_runner.viewer_data import BLOCK_TYPE_MEANINGS

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
VIEWER = REPOSITORY_ROOT / "viewer"


def test_the_page_loads_mermaid_from_a_pinned_cdn_version_with_an_integrity_hash() -> None:
    index = (VIEWER / "index.html").read_text(encoding="utf-8")

    assert re.search(r'src="https://cdn\.jsdelivr\.net/npm/mermaid@\d+\.\d+\.\d+/dist/mermaid\.min\.js"', index)
    assert 'integrity="sha384-' in index
    assert 'crossorigin="anonymous"' in index


def test_the_page_maps_the_elk_layout_to_a_pinned_cdn_version_with_a_hash_per_file() -> None:
    index = (VIEWER / "index.html").read_text(encoding="utf-8")
    script = (VIEWER / "app.js").read_text(encoding="utf-8")
    import_map = json.loads(index.split('<script type="importmap">', 1)[1].split("</script>", 1)[0])

    entry = import_map["imports"]["mermaid-layout-elk"]
    assert re.fullmatch(r"https://cdn\.jsdelivr\.net/npm/@mermaid-js/layout-elk@\d+\.\d+\.\d+/dist/[\w.-]+\.mjs", entry)
    assert entry in import_map["integrity"]
    assert all(value.startswith("sha384-") for value in import_map["integrity"].values())
    assert 'import("mermaid-layout-elk")' in script
    assert '() => "dagre"' in script  # without ELK, Mermaid's own layout draws the graph
    assert '"elk.layered.priority.straightness"' in script  # the main line stays straight


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


def test_the_viewer_is_in_the_release() -> None:
    files = release_file_map(REPOSITORY_ROOT)

    assert {"viewer/index.html", "viewer/app.js", "viewer/style.css"} <= set(files)


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


def test_the_arrow_tips_use_a_theme_color() -> None:
    style = (VIEWER / "style.css").read_text(encoding="utf-8")

    assert ".layer .arrowMarkerPath {\n  fill: var(--muted) !important;" in style


def test_every_block_field_has_a_help_entry() -> None:
    help_script = (VIEWER / "field_help.js").read_text(encoding="utf-8")
    help_entries = set(re.findall(r"^  (\w+): \{$", help_script, re.MULTILINE))
    block_fields = {field for schema in BLOCK_SCHEMAS.values() for field in schema["properties"]}

    assert block_fields - help_entries == set()


def test_every_fact_of_the_skill_screen_has_a_help_entry() -> None:
    help_script = (VIEWER / "field_help.js").read_text(encoding="utf-8")
    fact_map = help_script.split("export const FACT_FIELDS = {", 1)[1]
    mapped_facts = set(re.findall(r'^  "?([\w ]+?)"?: "\w+",$', fact_map, re.MULTILINE))
    fact_names = set(
        re.findall(
            r'facts\.append\(\["([^"]+)"',
            (REPOSITORY_ROOT / "pskill_runner" / "skill_view.py").read_text(encoding="utf-8"),
        )
    )

    assert fact_names - mapped_facts == set()


def test_a_help_button_opens_a_dialog_with_the_details() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")

    assert 'import { FACT_FIELDS, FIELD_HELP } from "./field_help.js";' in script
    assert "dialog.showModal()" in script
    assert "node.title = help.short" in script


def test_the_node_that_the_panel_shows_gets_a_ring_that_beats_mermaid_styles() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")
    style = (VIEWER / "style.css").read_text(encoding="utf-8")
    selection_rule = style.split(".layer g.node.is-selected circle {", 1)[1].split("}", 1)[0]

    assert script.count("markSelection();") >= 5  # the graph, both card lists, a node click, and a task click
    assert "var(--ink)" in selection_rule
    assert "!important" in selection_rule  # Mermaid scopes its own drop-shadow by id
    assert ".step-card.is-selected" in style


def test_the_skills_list_shows_the_internal_skills_in_their_own_section() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")

    assert 'skill.invocation === "internal"' in script
    assert '"Internal skills"' in script


def test_the_viewer_has_two_tabs_runs_and_the_content_of_one_project() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")

    assert '["Runs", "#/", ["runs", "run"]]' in script
    assert '["Content", contentHref(view.lastPlace), ["content", "skill", "agent"]]' in script
    assert 'if (hosted) tabs.push(["Folders", "#/folders", ["folders"]]);' in script
    # Each route names its project, so a run or a skill opens in the right folder.
    assert "return `#/run/${encodedPath(place, runId)}`;" in script


def test_the_viewer_has_an_agent_screen_with_an_editor() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")

    assert "/api/agents/" in script
    assert 'element("textarea"' in script


def test_a_name_that_leads_to_another_skill_or_agent_is_a_link_with_an_arrow() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")
    style = (VIEWER / "style.css").read_text(encoding="utf-8")

    assert "function entityLink(" in script
    assert ".entity-link::after" in style


def test_the_panel_has_a_close_button_and_escape_clears_the_selection() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")
    style = (VIEWER / "style.css").read_text(encoding="utf-8")

    assert '() => selectNode(null), "panel-close")' in script
    assert 'event.key === "Escape"' in script
    assert ".panel-close {\n  position: sticky;" in style  # it stays reachable while the panel scrolls


def test_a_block_reference_lights_up_its_block_on_the_canvas() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")
    style = (VIEWER / "style.css").read_text(encoding="utf-8")

    assert r"const BLOCK_REFERENCE = /\b(steps|history)\." in script
    assert "linkReferences(view.parts.panel, shownNode());" in script
    assert "referencedNodes(edge.when, edge.source)" in script  # an edge of the canvas lights up what it reads
    assert ".layer g.cluster.is-referenced > rect {" in style  # a call frame lights up too
    assert "--ref:" in style


def test_the_skill_screen_can_collapse_its_child_skills() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")

    assert 'switchControl("Collapse sub-skills", view.collapsed, toggleChildSkills)' in script
    assert 'control.setAttribute("role", "switch");' in script
    assert "view.detail?.collapsed_canvas" in script
    assert 'localStorage.getItem(EXPANDED_KEY) !== "true"' in script  # collapsed unless the user expanded


def test_without_a_local_server_the_page_is_the_hosted_viewer() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")
    hosted = (VIEWER / "hosted.js").read_text(encoding="utf-8")

    assert 'hosted = await import("./hosted.js");' in script  # only when /api/version does not answer
    assert "window.showDirectoryPicker(" in hosted
    assert "indexedDB.open(DATABASE" in hosted  # the picked folders survive a reload
    assert "answer_get, answer_post" in hosted  # the same API code as the local server
    assert "WORKTREE_HOMES" in hosted  # the worktrees of each clone are found too


def test_the_page_maps_pyodide_to_a_pinned_cdn_version_with_a_hash_per_module() -> None:
    index = (VIEWER / "index.html").read_text(encoding="utf-8")
    hosted = (VIEWER / "hosted.js").read_text(encoding="utf-8")
    import_map = json.loads(index.split('<script type="importmap">', 1)[1].split("</script>", 1)[0])

    entry = import_map["imports"]["pyodide"]
    match = re.fullmatch(r"https://cdn\.jsdelivr\.net/pyodide/v(\d+\.\d+\.\d+)/full/pyodide\.mjs", entry)
    assert match is not None
    assert {entry, entry.replace("pyodide.mjs", "pyodide.asm.mjs")} <= set(import_map["integrity"])
    assert 'await import("pyodide")' in hosted


def test_the_viewer_cancels_a_run_and_deletes_finished_runs_after_asking() -> None:
    script = (VIEWER / "app.js").read_text(encoding="utf-8")

    assert 'button("Cancel run", cancelOpenRun, "tool danger")' in script
    assert 'button("Delete run", deleteOpenRun, "tool danger")' in script
    assert (
        "const finished = runs.filter((run) => !UNFINISHED.includes(run.status));" in script
    )  # cleanup keeps the open ones
    assert script.count("window.confirm(") >= 4  # the editor's block delete, and the three run actions
