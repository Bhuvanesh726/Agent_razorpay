#!/usr/bin/env pwsh
# Thin wrapper — the real logic lives in demo.py (shared with demo.sh so
# there's one source of truth for the HTTP orchestration and HMAC signing).
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$scriptDir\venv\Scripts\python.exe" "$scriptDir\demo.py" @args
exit $LASTEXITCODE
