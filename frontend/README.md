# Bab Frontend

Vite React SPA for Bab.

## Local commands

```powershell
pnpm install
pnpm dev
pnpm build
pnpm lint
pnpm test
pnpm orval
```

The Vite dev server proxies `/api/v1` and `/v1` to `http://localhost:8000`.
Run `pnpm orval` after backend OpenAPI changes while the backend server is running.
