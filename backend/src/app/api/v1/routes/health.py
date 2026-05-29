from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.database import engine
from app.core.migrations import get_migration_state

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness_check(response: Response) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "database": {"ok": False},
        "migrations": {"ok": False},
    }

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001 - readiness should report dependency state.
        checks["database"] = {"ok": False, "error": exc.__class__.__name__}

    try:
        migration_state = await get_migration_state(engine)
        checks["migrations"] = {
            "ok": bool(migration_state["is_current"]),
            **migration_state,
        }
    except Exception as exc:  # noqa: BLE001 - readiness should report dependency state.
        checks["migrations"] = {"ok": False, "error": exc.__class__.__name__}

    ready = all(check["ok"] for check in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "not_ready", "checks": checks}
