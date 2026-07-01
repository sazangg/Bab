param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [switch]$Install,
    [switch]$SkipMigrations
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backend = Join-Path $repo "backend"
$frontend = Join-Path $repo "frontend"
$envPath = Join-Path $backend ".env"
$envExamplePath = Join-Path $backend ".env.example"

function Receive-JobOutput {
    param(
        [System.Management.Automation.Job]$Job,
        [string]$Prefix
    )

    Receive-Job -Job $Job | ForEach-Object {
        Write-Host "[$Prefix] $_"
    }
}

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

if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath $envExamplePath -Destination $envPath
    Write-Host "Created backend/.env from backend/.env.example."
    Write-Host "Review backend/.env before using this outside local development."
}

if ($Install) {
    & (Join-Path $PSScriptRoot "setup.ps1")
}

if (-not $SkipMigrations) {
    Push-Location $backend
    try {
        Invoke-Native "uv" @("run", "alembic", "upgrade", "head")
    }
    finally {
        Pop-Location
    }
}

$frontendJob = $null
$backendJob = Start-Job -Name "bab-backend" -ScriptBlock {
    param($Path, $Port)
    Set-Location $Path
    uv run uvicorn app.main:app --host 127.0.0.1 --port $Port --reload
} -ArgumentList $backend, $BackendPort

try {
    $healthUrl = "http://127.0.0.1:$BackendPort/api/v1/health"
    $started = $false
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        Receive-JobOutput -Job $backendJob -Prefix "backend"
        if ($backendJob.State -ne "Running") {
            throw "Backend process exited with state $($backendJob.State)."
        }
        try {
            Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2 | Out-Null
            $started = $true
            break
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $started) {
        throw "Backend did not become healthy at $healthUrl."
    }

    $frontendJob = Start-Job -Name "bab-frontend" -ScriptBlock {
    param($Path, $Port)
    Set-Location $Path
    pnpm --config.confirmModulesPurge=false dev --host 127.0.0.1 --port $Port
} -ArgumentList $frontend, $FrontendPort

    Write-Host "Backend:  http://127.0.0.1:$BackendPort"
    Write-Host "Frontend: http://127.0.0.1:$FrontendPort"
    Write-Host "Press Ctrl+C to stop both processes."

    while ($true) {
        Receive-JobOutput -Job $backendJob -Prefix "backend"
        Receive-JobOutput -Job $frontendJob -Prefix "frontend"

        if ($backendJob.State -ne "Running") {
            throw "Backend process exited with state $($backendJob.State)."
        }
        if ($frontendJob.State -ne "Running") {
            throw "Frontend process exited with state $($frontendJob.State)."
        }

        Start-Sleep -Milliseconds 500
    }
}
finally {
    foreach ($job in @($backendJob, $frontendJob)) {
        if ($null -ne $job) {
            Stop-Job -Job $job -ErrorAction SilentlyContinue
            Receive-Job -Job $job -ErrorAction SilentlyContinue | Out-Null
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        }
    }
}
