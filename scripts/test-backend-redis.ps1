param(
    [int]$Port = 16379,
    [switch]$KeepRunning
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backend = Join-Path $repo "backend"
$composeFile = Join-Path $repo "tools\redis\compose.yaml"
$projectName = "bab-redis-tests"
$testRedisUrl = "redis://127.0.0.1:$Port/15"

function Invoke-Checked {
    param(
        [string]$Command,
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE."
    }
}

function Invoke-RedisCli {
    param([string[]]$Arguments)

    & docker @(
        "compose",
        "-p",
        $projectName,
        "-f",
        $composeFile,
        "exec",
        "-T",
        "redis",
        "redis-cli"
    ) @Arguments
}

function Wait-Redis {
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        $ping = Invoke-RedisCli @("ping") 2>$null
        if ($LASTEXITCODE -eq 0 -and ($ping -join "").Trim() -eq "PONG") {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "Redis did not become ready."
}

function Clear-TestRedis {
    Invoke-RedisCli @("-n", "15", "FLUSHDB") | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to clear Redis test DB 15."
    }
}

$previousTestRedisUrl = $env:BAB_TEST_REDIS_URL
$previousTestRedisPort = $env:BAB_TEST_REDIS_PORT
$exitCode = 0
$redisStarted = $false

try {
    $env:BAB_TEST_REDIS_PORT = [string]$Port
    Invoke-Checked "docker" @(
        "compose",
        "-p",
        $projectName,
        "-f",
        $composeFile,
        "up",
        "-d"
    )
    Wait-Redis
    $redisStarted = $true
    Clear-TestRedis

    $env:BAB_TEST_REDIS_URL = $testRedisUrl
    Push-Location $backend
    try {
        & uv run pytest tests/modules/test_provider_circuit_breaker.py -q
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
catch {
    Write-Error $_
    $exitCode = 1
}
finally {
    if ($redisStarted) {
        try {
            Clear-TestRedis
        }
        catch {
            Write-Warning $_
            if ($exitCode -eq 0) {
                $exitCode = 1
            }
        }
    }

    if ($null -eq $previousTestRedisUrl) {
        Remove-Item Env:\BAB_TEST_REDIS_URL -ErrorAction SilentlyContinue
    }
    else {
        $env:BAB_TEST_REDIS_URL = $previousTestRedisUrl
    }
    if ($null -eq $previousTestRedisPort) {
        Remove-Item Env:\BAB_TEST_REDIS_PORT -ErrorAction SilentlyContinue
    }
    else {
        $env:BAB_TEST_REDIS_PORT = $previousTestRedisPort
    }

    if (-not $KeepRunning) {
        try {
            Invoke-Checked "docker" @(
                "compose",
                "-p",
                $projectName,
                "-f",
                $composeFile,
                "down",
                "-v",
                "--remove-orphans"
            )
        }
        catch {
            Write-Warning $_
            if ($exitCode -eq 0) {
                $exitCode = 1
            }
        }
    }
}

exit $exitCode
