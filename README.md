# Bab

Bab is a self-hosted AI credential gateway and governance console. It centralizes upstream AI
provider credentials, gives applications scoped virtual keys, enforces access, usage limits, and
guardrails, and attributes traffic and spend across teams and projects.

Bab exposes an OpenAI-compatible gateway and native Anthropic Messages passthrough. The current V1
includes a React administration console and a FastAPI backend.

## V1 Capabilities

### Provider Governance

- Built-in catalog entries for OpenAI, OpenRouter, and Anthropic.
- Custom OpenAI-compatible providers.
- Encrypted local database-backed credential storage behind a secret-backend abstraction.
- Multiple credentials per provider with validation and health state.
- Credential pools with priority, round-robin, least-recently-used, health-based, and weighted
  selection.
- Model discovery, synchronization, aliases, capabilities, pricing, and health tests.
- Provider, credential, pool, and model impact previews.

### Workspace And Access

- Organization, team, project, and virtual-key hierarchy.
- Organization roles and scoped team/project memberships.
- Team and project administration with scoped visibility.
- Virtual-key inventory, expiration, effective-access summaries, usage, and revocation.
- Archived teams and projects stop descendant gateway traffic while preserving history.

### Policies And Guardrails

- Access policies targeting provider pools and model offerings.
- Multiple active access policies at the same scope union their routes.
- Child scopes can narrow inherited access but cannot widen it.
- Request, token, and budget limit policies with configurable windows.
- Organization, team, project, and virtual-key assignments.
- Guardrail allow/deny rules for request and response phases.
- Guardrail enforcement, dry-run assignments, simulation, events, and impact previews.

### Observability And Operations

- Scoped usage summaries, time series, records, CSV exports, and spend insights.
- Separate confirmed, estimated, and unknown spend.
- Scoped activity feed and exports.
- Signed, hash-chained administrative audit events with verification.
- Organization settings, branding, deployment URLs, and runtime defaults.
- Playground with project/key selection and no stored-secret exposure.
- API integration examples and runtime health/readiness information.

## Gateway Endpoints

Bab currently exposes:

```text
GET  /v1/models
POST /v1/chat/completions
POST /v1/responses
POST /v1/completions
POST /v1/messages
```

The first four routes provide the current OpenAI-compatible surface. `/v1/messages` provides native
Anthropic Messages passthrough; it is not an OpenAI-to-Anthropic translation layer. Embeddings are
deferred to the next version; the placeholder route is not part of the current gateway surface.

## Architecture

```text
frontend/   React 19, TypeScript, Vite, TanStack Query, shadcn/Radix
backend/    FastAPI, SQLAlchemy, Alembic, SQLite/PostgreSQL
scripts/    PowerShell development and verification helpers
```

Local development runs:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

The frontend uses relative `/api` and `/v1` paths by default. Vite proxies those paths to the local
backend, matching the recommended same-origin reverse-proxy deployment model.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Node.js 24+
- pnpm

## Local Setup

From the repository root:

```powershell
Copy-Item backend/.env.example backend/.env
uv sync --project backend
pnpm install --dir frontend
```

Update `backend/.env` before starting:

- `BAB_SECRET_KEY` must contain at least 32 characters.
- `BAB_ENCRYPTION_KEY` must be a valid Fernet key.
- Change the default administrator password.

Generate suitable values:

```powershell
uv run --project backend python -c "import secrets; print(secrets.token_urlsafe(48))"
uv run --project backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

In development mode, the backend applies pending Alembic migrations and initializes the local
organization, administrator, settings, and provider catalog. Existing local data is preserved.

## Run Locally

Use two terminals from the repository root:

```powershell
./scripts/dev-backend.ps1
```

```powershell
./scripts/dev-frontend.ps1
```

Open `http://127.0.0.1:5173` and sign in using `BAB_DEFAULT_ADMIN_EMAIL` and
`BAB_DEFAULT_ADMIN_PASSWORD`.

Apply migrations manually when needed:

```powershell
./scripts/migrate-backend.ps1
```

Useful operational endpoints:

```text
GET /health
GET /readyz
GET /api/v1/health
GET /api/v1/ready
GET /api/v1/readyz
GET /api/v1/runtime-info
```

## First Gateway Request

Use the console to:

1. Configure OpenAI, OpenRouter, Anthropic, or a custom OpenAI-compatible provider.
2. Add and validate a provider credential.
3. Create a credential pool and add the credential.
4. Synchronize or create at least one model offering.
5. Create a team and project.
6. Create an access policy with a route to the pool and model offering.
7. Assign the access policy to the project.
8. Create a virtual key under the project and capture its one-time secret.

Then send a request:

```powershell
$body = @{
  model = "your-model-alias-or-provider-model"
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

The request should appear in Usage and Activity with its team, project, key, policy, provider,
credential pool, model, status, latency, tokens, and cost information where available.

## Verification

Backend:

```powershell
./scripts/test-backend.ps1
```

Or run individual checks:

```powershell
Set-Location backend
$env:PYTHONPATH = "src"
uv run ruff check src tests
uv run pytest -q
```

Frontend:

```powershell
Set-Location frontend
pnpm format:check
pnpm lint
pnpm test
pnpm build
```

End-to-end tests:

```powershell
Set-Location frontend
pnpm e2e
```

The Playwright configuration starts isolated backend and frontend servers on dedicated ports and
uses a disposable SQLite database under `frontend/test-results`.

Backend integration tests mock upstream providers by default. Optional live OpenAI tests require:

```powershell
$env:BAB_RUN_LIVE_OPENAI_TESTS = "true"
$env:OPENAI_API_KEY = "..."
$env:BAB_LIVE_OPENAI_MODEL = "..."
```

## Production Notes

- Use PostgreSQL in production; production startup rejects SQLite.
- Set unique secret, encryption, and administrator credentials.
- Put the frontend and backend behind a same-origin reverse proxy with TLS.
- Route `/api/*`, `/v1/*`, `/health`, and `/readyz` to the backend and other paths to the frontend.
- Persist `BAB_ASSETS_DIR` or replace local assets with shared storage.
- Run Alembic migrations as part of deployment.
- Back up the database and provider-secret encryption key together.
- Retention values currently express configuration intent; automated deletion and rollup jobs are
  not part of V1.

External secret managers, SSO, full key rotation, cross-provider fallback, and automated retention
workers are planned beyond the current V1 surface.
