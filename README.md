# Bab

Bab is a self-hosted OpenAI-compatible LLM gateway. The local development setup runs as
two separate apps:

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

## Run Locally

Use two terminals:

```powershell
./scripts/dev-backend.ps1
./scripts/dev-frontend.ps1
```

Then open `http://127.0.0.1:5173`. On a fresh local database, the app redirects to
`/setup` to create the first admin.

In `BAB_ENVIRONMENT=development`, the backend creates local SQLite tables on startup.
This is only a temporary development bootstrap until Alembic migrations are wired.

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

## Manual Provider Smoke

1. Start both apps.
2. Complete first admin setup.
3. Create an OpenAI-compatible provider with:
   - Base URL like `https://api.openai.com/v1`
   - A real provider API key
4. Create a project.
5. Grant that project access to the provider and one model.
6. Create a virtual key for the project.
7. Send a non-streaming request to Bab:

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

Request logs and analytics should update in the frontend.
