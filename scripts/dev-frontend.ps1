Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..\frontend")
pnpm dev --host 127.0.0.1
