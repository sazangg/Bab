# Bab

Bab is a self-hosted, OpenAI-compatible AI gateway for business teams. It centralizes provider
credentials, groups them into credential pools, grants access through allocations, and records
append-only usage for proxy attribution.

The local development setup runs as two separate apps:

- FastAPI backend on `http://127.0.0.1:8000`
- Vite React frontend on `http://127.0.0.1:5173`

## Prerequisites

- Python 3.13+
- uv
- Node.js 24+
- pnpm

## First Run

```powershell
Copy-Item backend/.env.example backend/.env
uv sync --project backend
pnpm install --dir frontend
```

Update `backend/.env` before starting the backend. `BAB_SECRET_KEY` must be at least
32 characters. `BAB_ENCRYPTION_KEY` must be a Fernet key.

Generate a Fernet key:

```powershell
uv run --project backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

In `BAB_ENVIRONMENT=development`, the backend creates local SQLite tables on startup. This is a
temporary development bootstrap until migrations are wired.

## Run Locally

Use two terminals:

```powershell
./scripts/dev-backend.ps1
./scripts/dev-frontend.ps1
```

Then open `http://127.0.0.1:5173` and sign in with the development credentials configured for the
local environment.

## Current Product Surface

- Providers define upstream OpenAI-compatible endpoints and model offerings.
- Credential pools group provider credentials for routing.
- Teams own projects.
- Allocations grant projects access to provider pools and model offerings.
- Virtual keys are issued per project and resolve through allocations.
- Proxy requests append usage records with the resolved org, team, project, allocation, pool,
  provider, credential, and model chain.

## Checks

```powershell
./scripts/test-backend.ps1
pnpm --dir frontend format:check
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build
```

Smoke check local servers:

```powershell
./scripts/smoke-local.ps1
```

## Manual Proxy Smoke

1. Start both apps.
2. Sign in locally.
3. Create an OpenAI-compatible provider with:
   - Base URL like `https://api.openai.com/v1`
   - A real provider API key
4. Create or select a credential pool for that provider.
5. Register or sync a model offering.
6. Create a team and project.
7. Create a project allocation that points to the provider pool and model offering.
8. Create a virtual key for the project allocation.
9. Send a non-streaming request to Bab:

```powershell
$body = @{
  model = "gpt-5.4-mini"
  messages = @(@{ role = "user"; content = "Say hello from Bab." })
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/v1/chat/completions" `
  -Headers @{ Authorization = "Bearer bab-sk-your-virtual-key" } `
  -ContentType "application/json" `
  -Body $body
```

The backend should route through the allocation and append a usage record.
