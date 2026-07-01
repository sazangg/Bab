# Bab Frontend

Vite React SPA for Bab.

Most contributors should use the root scripts from the repository root:

```powershell
./scripts/setup.ps1
./scripts/dev.ps1
./scripts/check.ps1
./scripts/build.ps1
```

## Local Commands

If you need to work directly inside `frontend/`:

```powershell
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1
pnpm build
pnpm lint
pnpm test -- --run
pnpm e2e
pnpm orval
```

The Vite dev server proxies `/api/v1`, `/assets`, and `/v1` to `http://localhost:8000`. The
frontend-owned `/api-docs` route intentionally stays inside Vite.

Run `pnpm orval` after backend OpenAPI changes while the backend server is running.
