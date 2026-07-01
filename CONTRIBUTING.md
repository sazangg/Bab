# Contributing

Thanks for contributing to Bab.

This project is still in active build phase, so keep changes small, explicit, and easy to review.

## Development Setup

From the repository root:

```powershell
./scripts/setup.ps1
./scripts/dev.ps1
```

Open `http://127.0.0.1:5173` and sign in with the local admin credentials configured in
`backend/.env`.

## Before Sending A Change

Run:

```powershell
./scripts/check.ps1
```

For browser-level changes, also run:

```powershell
./scripts/check.ps1 -E2E
```

Live provider smoke tests are opt-in:

```powershell
./scripts/check.ps1 -Live
```

If your change touches only one area, focused tests are fine while iterating, but the final change
should pass the standard check before it is merged.

## Code Style

- Keep changes surgical.
- Do not refactor unrelated code.
- Prefer existing module boundaries and local patterns.
- Do not commit generated/runtime artifacts, local databases, logs, secrets, or `.env` files.
- Do not add compatibility layers during the current build phase unless there is a concrete
  migration requirement.

## Backend Notes

- Backend code lives under `backend/src/app`.
- Alembic migrations live under `backend/alembic`.
- Use public module facades/read models across domain boundaries.
- SQLite is for local development; PostgreSQL is the production target.

## Frontend Notes

- Frontend code lives under `frontend/src`.
- Generated API clients live under `frontend/src/shared/api/generated`.
- Regenerate clients with `pnpm orval` only after backend OpenAPI changes.
- Keep product surfaces role-aware and avoid dead actions for read-only/scoped users.

## Security

Do not open a public issue with real secrets, provider API keys, customer data, or exploitable
details. Report privately to the project maintainer first.

## License

By contributing, you agree that your contribution is licensed under the MIT License.
