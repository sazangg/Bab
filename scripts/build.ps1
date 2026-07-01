Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backend = Join-Path $repo "backend"
$frontend = Join-Path $repo "frontend"

function Invoke-Native {
    param(
        [string]$Command,
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE."
    }
}

Push-Location $backend
try {
    Invoke-Native "uv" @("build")
}
finally {
    Pop-Location
}

Push-Location $frontend
try {
    Invoke-Native "pnpm" @("--config.confirmModulesPurge=false", "build")
}
finally {
    Pop-Location
}

Write-Host "Backend package: backend/dist"
Write-Host "Frontend static build: frontend/dist"
