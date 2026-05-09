Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..\backend")
uv run ruff format --check .
uv run ruff check .
uv run pytest
