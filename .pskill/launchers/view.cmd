@echo off
rem Double-click to open the pskill viewer (Windows).
cd /d "%~dp0.."
uv run pskill.py view
pause
