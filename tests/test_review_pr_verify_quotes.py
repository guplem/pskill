"""Tests for the review-pr skill's verify_quotes.py script (no quote, no finding)."""

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parent.parent / ".pskill" / "skills" / "review-pr" / "scripts" / "verify_quotes.py"

DIFF = """\
diff --git a/calc.py b/calc.py
@@ -1,3 +1,3 @@
 def add(a, b):
-    return a + b
+    return a - b
"""


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_quotes", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def finding(quote: str) -> dict[str, object]:
    return {"file": "calc.py", "line": 2, "severity": "blocker", "summary": "Wrong operator.", "quote": quote}


def test_a_finding_whose_quote_is_in_the_diff_is_kept() -> None:
    kept = load_script().findings_with_real_quotes([finding("return a - b")], DIFF)

    assert kept == [finding("return a - b")]


def test_a_finding_whose_quote_is_not_in_the_diff_is_dropped() -> None:
    kept = load_script().findings_with_real_quotes([finding("return a * b")], DIFF)

    assert kept == []


def test_every_line_of_a_multi_line_quote_must_be_in_the_diff() -> None:
    script = load_script()

    assert script.findings_with_real_quotes([finding("def add(a, b):\n    return a - b")], DIFF) != []
    assert script.findings_with_real_quotes([finding("def add(a, b):\n    return a * b")], DIFF) == []


def test_an_empty_quote_is_dropped() -> None:
    assert load_script().findings_with_real_quotes([finding("  ")], DIFF) == []
