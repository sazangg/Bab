param(
    [switch]$E2E,
    [switch]$Format,
    [switch]$Live
)

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
    $previousLiveOpenAITests = $env:BAB_RUN_LIVE_OPENAI_TESTS
    if (-not $Live) {
        $env:BAB_RUN_LIVE_OPENAI_TESTS = "false"
    }
    Invoke-Native "uv" @("run", "ruff", "check", "src", "tests")
    Invoke-Native "uv" @("run", "pytest", "-q")
}
finally {
    if ($null -eq $previousLiveOpenAITests) {
        Remove-Item Env:\BAB_RUN_LIVE_OPENAI_TESTS -ErrorAction SilentlyContinue
    }
    else {
        $env:BAB_RUN_LIVE_OPENAI_TESTS = $previousLiveOpenAITests
    }
    Pop-Location
}

Push-Location $frontend
try {
    if ($Format) {
        Invoke-Native "pnpm" @("--config.confirmModulesPurge=false", "format:check")
    }
    Invoke-Native "pnpm" @("--config.confirmModulesPurge=false", "lint")
    Invoke-Native "pnpm" @("--config.confirmModulesPurge=false", "test", "--", "--run")
    Invoke-Native "pnpm" @("--config.confirmModulesPurge=false", "build")
    if ($E2E) {
        Invoke-Native "pnpm" @("--config.confirmModulesPurge=false", "e2e")
    }
}
finally {
    Pop-Location
}
