# Bab Local Observability

This stack is local development tooling for the backend. It is not production deployment
configuration.

## Services

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000
- Tempo OTLP HTTP: http://localhost:4318/v1/traces
- Backend metrics: http://127.0.0.1:8000/metrics

Grafana local credentials are `admin` / `admin`.

## Start The Backend

Run the backend normally:

```powershell
cd D:\coding\portfolio\bab\backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Run the backend with OTLP tracing enabled:

```powershell
cd D:\coding\portfolio\bab\backend
$env:BAB_OTEL_ENABLED = "true"
$env:BAB_OTEL_EXPORTER = "otlp"
$env:BAB_OTEL_OTLP_ENDPOINT = "http://localhost:4318/v1/traces"
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Start The Stack

From the repository root:

```powershell
docker compose -f tools/observability/compose.yaml up -d
```

Prometheus scrapes the backend at `host.docker.internal:8000`, which is the Docker
Desktop host address for the backend server running on Windows.

Open Grafana at http://localhost:3000 and use the provisioned `Bab Backend Overview`
dashboard in the `Bab` folder. The Prometheus and Tempo datasources are provisioned
automatically.

## Generate Basic Traffic

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/health"
Invoke-WebRequest -Uri "http://127.0.0.1:8000/metrics"
```

In Prometheus, query:

```text
bab_http_requests_total
```

With tracing enabled, traces should appear in Grafana Explore using the Tempo datasource
after backend requests are made.

## Stop The Stack

```powershell
docker compose -f tools/observability/compose.yaml down
```

Remove local observability volumes only when intentionally resetting local telemetry data:

```powershell
docker compose -f tools/observability/compose.yaml down -v
```
