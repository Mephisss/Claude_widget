#!/usr/bin/env bash
# Launch the Claude Code usage widget (macOS / Linux).
set -e
cd "$(dirname "$0")"

# Prefer pythonw on macOS framework builds; fall back to python3.
PY=python3
command -v pythonw >/dev/null 2>&1 && PY=pythonw

exec "$PY" widget.py
