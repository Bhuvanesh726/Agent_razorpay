#!/usr/bin/env bash
# Thin wrapper — the real logic lives in demo.py (shared with demo.ps1 so
# there's one source of truth for the HTTP orchestration and HMAC signing).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -x "$SCRIPT_DIR/venv/Scripts/python.exe" ]; then
  PYTHON="$SCRIPT_DIR/venv/Scripts/python.exe"  # Windows venv layout (git-bash)
else
  PYTHON="$SCRIPT_DIR/venv/bin/python"  # native Unix venv layout
fi

"$PYTHON" "$SCRIPT_DIR/demo.py" "$@"
