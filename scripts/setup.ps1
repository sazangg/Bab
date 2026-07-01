param(
    [switch]$ForceEnv
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backend = Join-Path $repo "backend"
$frontend = Join-Path $repo "frontend"
$envPath = Join-Path $backend ".env"
$envExamplePath = Join-Path $backend ".env.example"

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

function New-FernetKey {
    $bytes = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

if ($ForceEnv -or -not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath $envExamplePath -Destination $envPath -Force
    $generatedEncryptionKey = New-FernetKey
    $envContent = Get-Content -Raw -LiteralPath $envPath
    $envContent = $envContent -replace "(?m)^BAB_ENCRYPTION_KEY=.*$", "BAB_ENCRYPTION_KEY=$generatedEncryptionKey"
    Set-Content -LiteralPath $envPath -Value $envContent -NoNewline
    Write-Host "Created backend/.env from backend/.env.example."
    Write-Host "Before production use, replace BAB_SECRET_KEY, BAB_ENCRYPTION_KEY, and BAB_DEFAULT_ADMIN_PASSWORD."
}

Push-Location $backend
try {
    Invoke-Native "uv" @("sync")
}
finally {
    Pop-Location
}

Push-Location $frontend
try {
    Invoke-Native "pnpm" @("--config.confirmModulesPurge=false", "install", "--frozen-lockfile")
}
finally {
    Pop-Location
}

Write-Host "Setup complete. Start the app with: ./scripts/dev.ps1"
