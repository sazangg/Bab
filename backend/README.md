# Bab Backend

FastAPI backend for Bab.

Most contributors should use the root scripts from the repository root:

```powershell
./scripts/setup.ps1
./scripts/dev.ps1
./scripts/check.ps1
./scripts/test-backend-redis.ps1
./scripts/build.ps1
```

## Local Commands

If you need to work directly inside `backend/`:

```powershell
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
uv run ruff check src tests
uv run pytest -q
uv build
```

With `BAB_ENVIRONMENT=development`, startup applies pending Alembic migrations and seeds the default
local organization, admin user, settings, and provider catalog when the database is empty.

Production deployments should run `uv run alembic upgrade head` before starting the app and should
use PostgreSQL, not SQLite.

## Environment

Start from:

```powershell
Copy-Item .env.example .env
```

Then replace local defaults before non-local use:

- `BAB_SECRET_KEY`
- `BAB_ENCRYPTION_KEY`
- `BAB_DEFAULT_ADMIN_PASSWORD`

Generate suitable values:

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

For production, apply migrations and run the one-shot bootstrap with the final production
environment:

```powershell
uv run alembic upgrade head
uv run python -m app.cli bootstrap --organization-name "Example Organization" --admin-email "owner@example.com"
```

Bootstrap refuses any database that already contains an organization or user. Production web
startup does not seed data.

Encryption-key rotation is offline:

1. Stop backend workers.
2. Back up the database.
3. Set `BAB_NEW_ENCRYPTION_KEY`.
4. Run `uv run python -m app.cli rotate-encryption-key`.
5. Replace `BAB_ENCRYPTION_KEY` with the new value.
6. Remove `BAB_NEW_ENCRYPTION_KEY`.
7. Restart and validate provider credentials.

## Authentication Rate Limiting

Rate limiting is disabled by default. Set `BAB_RATE_LIMIT_ENABLED=true` and provide
`BAB_REDIS_URL` using `redis://`, `rediss://`, or `unix://`. Redis is included in
readiness while enabled. `BAB_RATE_LIMIT_FAIL_CLOSED` defaults to `true` for
request-time storage failures.

Current fixed limits:

| Route group | Bucket | Limit |
| --- | --- | --- |
| Login | IP | 20 attempts / 10 minutes |
| Login | normalized email | 5 attempts / 15 minutes |
| Invite acceptance | IP | 20 attempts / 10 minutes |
| Invite acceptance | token | 5 attempts / 1 hour |
| Refresh | IP | 60 attempts / 10 minutes |
| Refresh | token | 10 attempts / 1 minute |
| Invalid proxy authentication | IP | 60 failures / 1 minute |
| Invalid proxy authentication | key | 20 failures / 1 minute |

Only proxy authentication failures consume proxy buckets. Client IP is the direct
socket peer. Deployments behind a reverse proxy must configure trusted proxy
handling deliberately; the application does not trust forwarded headers.

## Provider Runtime State

`BAB_PROVIDER_RUNTIME_STATE_BACKEND` selects provider circuit and concurrency ownership:

- `memory` (default) is process-local and suitable only for one backend worker.
- `redis` shares circuit state and provider concurrency permits across workers and
  requires `BAB_REDIS_URL`. Redis is readiness-critical in this mode.

Circuit state is ephemeral and uses bounded Redis TTLs. Redis provider concurrency
uses token-safe expiring permits, so a stopped worker eventually releases capacity.

## Redis Integration Tests

Normal backend tests do not require Redis, Docker, or any network service. Real Redis
integration tests are optional and use the test-only `BAB_TEST_REDIS_URL`, not the
runtime `BAB_REDIS_URL`.

From the repository root:

```powershell
./scripts/test-backend-redis.ps1
```

The script starts disposable `redis:7-alpine` with Docker Compose on host port 16379,
sets `BAB_TEST_REDIS_URL=redis://127.0.0.1:16379/15`, runs the focused backend Redis
tests, flushes DB 15 before and after the run, and removes the container by default.
Use `-Port 6379` only if that host port is free. Use `-KeepRunning` only when you
want to inspect or reuse the local test service.

These tests validate Redis-backed rate limiter and provider runtime behavior. They do
not store app development data and do not use committed secrets or persistent Docker
volumes.
