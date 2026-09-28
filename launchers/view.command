#!/bin/sh
# Double-click to open the pskill viewer (macOS).
cd "$(dirname "$0")/.." && exec uv run pskill.py view
