Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$backendHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health"
$setupStatus = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/setup/status"
$frontend = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -UseBasicParsing

[PSCustomObject]@{
    backend = $backendHealth.status
    setup_required = $setupStatus.setup_required
    frontend_status = $frontend.StatusCode
}
