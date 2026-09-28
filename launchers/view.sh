#!/bin/sh
# Run to open the pskill viewer (Linux).
cd "$(dirname "$0")/.." && exec uv run pskill.py view
