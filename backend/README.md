# Bab Backend

FastAPI backend for Bab.

## Setup

```powershell
Copy-Item .env.example .env
uv sync
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste the generated Fernet key into `BAB_ENCRYPTION_KEY` in `.env`.

## Local commands

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

With `BAB_ENVIRONMENT=development`, local SQLite tables are created on startup.
Production deployments must use migrations instead.
