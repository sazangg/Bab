# Bab

Bab is a self-hosted AI credential gateway and governance console. It centralizes upstream AI
provider credentials, gives applications scoped virtual keys, enforces access, usage limits, and
guardrails, and attributes traffic and spend across teams and projects.

Bab exposes an OpenAI-compatible gateway plus native Anthropic Messages passthrough. The current V1
ships a React administration console and a FastAPI backend.

## Product Surface

### Provider Governance

- Built-in catalog entries for OpenAI, OpenRouter, and Anthropic.
- Custom OpenAI-compatible providers.
- Encrypted local database-backed credential storage behind a secret-backend abstraction.
- Provider credentials, credential pools, pool membership, validation, health state, and impact
  previews.
- Provider model discovery, metadata synchronization, capabilities, pricing, and readiness.
- Credential routing with priority, round-robin, least-recently-used, health-based, and weighted
  selection modes.

### Workspace And Access

- Organization, team, project, and virtual-key hierarchy.
- Organization roles and scoped team/project memberships.
- Team and project administration with scoped visibility.
- Virtual-key inventory, expiration, effective-access summaries, usage, and revocation.
- Archived teams and projects stop descendant gateway traffic while preserving history.

### Policies And Guardrails

- Access policies expose public model names that route to provider pools and provider model offerings.
- Multiple active access policies at the same scope union their routes.
- Child scopes can narrow inherited access but cannot widen it.
- Request, token, and budget limit policies with configurable windows.
- Organization, team, project, and virtual-key assignments.
- Guardrail allow/deny rules for request and response phases.
- Guardrail enforcement, dry-run assignments, simulation, events, and impact previews.

### Operations And Observability

- Usage summaries, time series, records, CSV exports, and spend insights.
- Gateway request history with trace detail.
- Scoped activity feed and exports.
- Signed, hash-chained administrative audit events with verification.
- Organization settings, branding, deployment URLs, and runtime defaults.
- Playground with project/key selection and no stored-secret exposure.
- Structured logs, Prometheus metrics, OpenTelemetry tracing, and local observability tooling.

## Gateway Endpoints

```text
GET  /v1/models
POST /v1/chat/completions
POST /v1/responses
POST /v1/completions
POST /v1/messages
```

The first four routes provide the current OpenAI-compatible surface. `/v1/messages` provides native
Anthropic Messages passthrough; it is not an OpenAI-to-Anthropic translation layer. Embeddings are
deferred to a later version.

## Repository Layout

```text
backend/    FastAPI, SQLAlchemy, Alembic, SQLite/PostgreSQL
frontend/   React 19, TypeScript, Vite, TanStack Query, shadcn/Radix
scripts/    PowerShell setup, dev, check, and build entry points
tools/      Local observability, performance, Redis test, and SonarQube tooling
```

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Node.js 24+
- [pnpm](https://pnpm.io/)
- PowerShell for the root scripts
- Docker, only for optional Redis integration tests

## Quick Start

From the repository root:

```powershell
./scripts/setup.ps1
./scripts/dev.ps1
```

`setup.ps1` installs backend and frontend dependencies. If `backend/.env` does not exist, it creates
one from `backend/.env.example`.

`dev.ps1` runs Alembic migrations, starts the backend, waits for backend health, then starts the
frontend.

Local URLs:

```text
Frontend: http://127.0.0.1:5173
Backend:  http://127.0.0.1:8000
```

Sign in with `BAB_DEFAULT_ADMIN_EMAIL` and `BAB_DEFAULT_ADMIN_PASSWORD` from `backend/.env`.

Before any non-local use, replace:

- `BAB_SECRET_KEY`
- `BAB_ENCRYPTION_KEY`
- `BAB_DEFAULT_ADMIN_PASSWORD`

Generate suitable secrets:

```powershell
cd backend
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

For a fresh production database, run migrations and the one-shot owner bootstrap with the final
production environment:

```powershell
cd backend
uv run alembic upgrade head
uv run python -m app.cli bootstrap --organization-name "Example Organization" --admin-email "owner@example.com"
```

Run bootstrap once. It refuses databases that already contain any organization or user, and normal
production web startup never seeds data.

To rotate `BAB_ENCRYPTION_KEY`, stop backend workers, back up the database, set
`BAB_NEW_ENCRYPTION_KEY`, run `uv run python -m app.cli rotate-encryption-key`, replace
`BAB_ENCRYPTION_KEY` with the new value, remove `BAB_NEW_ENCRYPTION_KEY`, then restart and validate
provider credentials.

## Scripts

```powershell
./scripts/setup.ps1          # install dependencies and create backend/.env if missing
./scripts/dev.ps1            # migrate, start backend, then start frontend
./scripts/dev.ps1 -Install   # run setup first, then start dev servers
./scripts/dev.ps1 -SkipMigrations
./scripts/check.ps1          # backend ruff/tests plus frontend lint/tests/build
./scripts/check.ps1 -Format  # also run the frontend Prettier check
./scripts/check.ps1 -E2E     # also run Playwright E2E
./scripts/check.ps1 -Live    # also allow live provider smoke tests when env vars are set
./scripts/test-backend-redis.ps1  # run optional backend Redis integration tests in Docker
./scripts/build.ps1          # build backend wheel/sdist and frontend static assets
```

The old separate backend/frontend/migration wrappers were intentionally consolidated into these
entry points.

## First Gateway Request

Use the console to:

1. Configure OpenAI, OpenRouter, Anthropic, or a custom OpenAI-compatible provider.
2. Add and validate a provider credential.
3. Create a credential pool and add the credential.
4. Synchronize or create at least one provider model offering.
5. Create a team and project.
6. Create an access policy with a public model name that routes to the pool and provider model
   offering.
7. Assign the access policy to the project.
8. Create a virtual key under the project and capture its one-time secret.

Then send a request:

```powershell
$body = @{
  model = "your-policy-public-model"
  messages = @(
    @{ role = "user"; content = "Reply with hello from Bab." }
  )
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/v1/chat/completions" `
  -Headers @{ Authorization = "Bearer bab-your-virtual-key" } `
  -ContentType "application/json" `
  -Body $body
```

The request model is the public model name exposed by the assigned access policy.

## Build And Deployment Options

Current build command:

```powershell
./scripts/build.ps1
```

Outputs:

```text
backend/dist/     Python package artifacts
frontend/dist/    Vite static frontend build
```

Recommended deployment shape:

- PostgreSQL database.
- FastAPI backend served by Uvicorn/Gunicorn or an equivalent ASGI runtime.
- Frontend static assets served by a reverse proxy or static host.
- Same-origin reverse proxy routing:
  - `/api/v1/*`, `/v1/*`, `/health`, `/readyz`, `/metrics` to the backend;
  - all other paths to the frontend.
- TLS at the reverse proxy.
- Persistent `BAB_ASSETS_DIR` or shared object storage for uploaded assets.
- Alembic migrations run before backend startup.

SQLite is for local development and single-process testing. Production startup rejects SQLite.

The next packaging milestone should be a deliberate Docker/Compose production profile with
PostgreSQL and a reverse proxy. It is not included here because deployment packaging deserves its own
small design pass.

## Verification

Run the standard local check:

```powershell
./scripts/check.ps1
```

Run E2E as well:

```powershell
./scripts/check.ps1 -E2E
```

The Playwright configuration starts isolated backend and frontend servers on dedicated ports and
uses a disposable SQLite database under `frontend/test-results`.

Optional live OpenAI integration tests require:

```powershell
$env:BAB_RUN_LIVE_OPENAI_TESTS = "true"
$env:OPENAI_API_KEY = "..."
$env:BAB_LIVE_OPENAI_MODEL = "..."
```

Optional Redis integration tests do not run during the normal suite. To validate the real Redis
rate-limiter and provider runtime paths, run:

```powershell
./scripts/test-backend-redis.ps1
```

The script starts disposable `redis:7-alpine` with Docker Compose on host port 16379, sets
`BAB_TEST_REDIS_URL=redis://127.0.0.1:16379/15`, flushes Redis DB 15 before and after the focused
backend Redis tests, and tears the service down unless `-KeepRunning` is passed. Use `-Port 6379`
only if that host port is free. `BAB_REDIS_URL` is runtime configuration; `BAB_TEST_REDIS_URL` is
test-only.

## Local Operations Tooling

- Observability stack: `tools/observability`
- SQLite performance harness: `tools/performance`
- Redis integration test service: `tools/redis`
- SonarQube baseline tooling: `tools/sonarqube`

These are local development aids, not production deployment manifests.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Bab is released under the [MIT License](LICENSE).

The practical requirement is simple: use Bab for any purpose, but keep the copyright and license
notice with copies or substantial portions of the project so the project and author are credited.
