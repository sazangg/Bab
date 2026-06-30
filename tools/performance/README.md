# Bab SQLite Performance Harness

This harness measures the current backend against a disposable SQLite database and a local
OpenAI-compatible provider. Generated databases, credentials, k6 summaries, WAL/SHM files,
and uploaded assets stay under ignored `.runtime` or `results` directories.

## Prerequisites

- Docker Desktop
- the backend `uv` environment
- ports 8000, 8080, 9090, 3000, 3200, and 4318 available

All commands below start from the repository root unless stated otherwise.

## Reset And Migrate

The reset command contains an explicit absolute target check and removes only the benchmark
database and its SQLite sidecars.

```powershell
$repo = (Get-Location).Path
$runtime = (New-Item -ItemType Directory -Force (Join-Path $repo "tools/performance/.runtime")).FullName
$database = Join-Path $runtime "bab-performance.db"
$expectedDatabase = Join-Path $repo "tools/performance/.runtime/bab-performance.db"
if ([IO.Path]::GetFullPath($database) -ne [IO.Path]::GetFullPath($expectedDatabase)) {
    throw "Unexpected benchmark database path: $database"
}
Remove-Item -LiteralPath $database, "$database-wal", "$database-shm" -Force -ErrorAction SilentlyContinue

cd backend
$databaseUrlPath = $database.Replace("\", "/")
$env:DATABASE_URL = "sqlite+aiosqlite:///$databaseUrlPath"
$env:BAB_SECRET_KEY = "benchmark-secret-key-with-at-least-32-characters"
$env:BAB_ENCRYPTION_KEY = "mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw="
$env:BAB_DEFAULT_ADMIN_EMAIL = "benchmark-admin@example.com"
$env:BAB_DEFAULT_ADMIN_PASSWORD = "benchmark-admin-password"
uv run alembic upgrade head
cd ..
```

## Start Services And Backend

```powershell
docker compose -f tools/performance/compose.yaml up -d
docker compose -f tools/observability/compose.yaml up -d

cd backend
$env:BAB_ALLOW_PRIVATE_PROVIDER_URLS = "true"
$env:BAB_ASSETS_DIR = (Join-Path $runtime "assets")
$env:BAB_OTEL_ENABLED = "true"
$env:BAB_OTEL_EXPORTER = "otlp"
$env:BAB_OTEL_OTLP_ENDPOINT = "http://127.0.0.1:4318/v1/traces"
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Keep that terminal running. The provider stub defaults to a fixed 20 ms response delay.

## Seed

In another terminal:

```powershell
cd backend
uv run python ../tools/performance/seed.py
```

Defaults: 10 teams, 30 projects, 500 virtual keys, 10,000 usage records, 10,000 gateway
requests, and 10,000 route attempts. The script rejects database paths outside the benchmark
runtime directory. Reset before rerunning; seeding is intentionally not idempotent.

## Run

The load generator is pinned to `grafana/k6:1.0.0`.

```powershell
$mounts = @(
    "-v", "${PWD}/tools/performance/k6:/scripts:ro",
    "-v", "${PWD}/tools/performance/.runtime:/runtime:ro"
)
docker run --rm --add-host host.docker.internal:host-gateway $mounts grafana/k6:1.0.0 run /scripts/smoke.js

docker run --rm --add-host host.docker.internal:host-gateway `
    -e VUS=10 -e DURATION=60s $mounts `
    grafana/k6:1.0.0 run /scripts/gateway.js
```

Use `control_plane.js`, `gateway.js`, or `mixed.js`; set `VUS` and `DURATION`. Run a 15-second
warm-up before a measured 60-second profile. Mixed traffic is four gateway requests followed
by one usage-summary request per iteration (80/20 by request count).

## SQLite Evidence

```powershell
cd backend
uv run python ../tools/performance/inspect_sqlite.py
```

This reports library/database information, active pragmas, row counts, indexes, and
representative `EXPLAIN QUERY PLAN` output without changing database settings.

## SQLite Concurrency

The application enables foreign keys, WAL, a 5-second busy timeout, and FULL synchronous
durability on each SQLite connection. Gateway persistence uses a process-local async
coordinator for short write-and-commit units only. It does not guard provider calls or
read-only reporting, and it coordinates only one backend process. Multi-worker or sustained
high-throughput deployments should use PostgreSQL instead of extending this mechanism.

## Cleanup

Stop the backend with Ctrl+C, then:

```powershell
docker compose -f tools/performance/compose.yaml down
docker compose -f tools/observability/compose.yaml down
Remove-Item -LiteralPath tools/performance/.runtime, tools/performance/results `
    -Recurse -Force -ErrorAction SilentlyContinue
```

The observability command preserves its named volumes. Use its documented `down -v` command
only when intentionally deleting local telemetry.
