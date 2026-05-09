Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..\backend")
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
