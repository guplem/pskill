# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "jinja2>=3.1",
#     "jsonschema>=4.21",
#     "pyyaml>=6",
# ]
# ///
"""Entry point of the pskill runner. Run it with: uv run pskill.py <command>

Python puts this file's folder on the import path, so the `pskill_runner`
package next to it is importable without an install step.
"""

import sys

from pskill_runner.cli import main

if __name__ == "__main__":
    sys.exit(main())
