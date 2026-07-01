from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.core.migrations import get_migration_state
from app.core.problems import ProblemException
from app.core.redis_client import ping_redis

router = APIRouter(tags=["health"])
root_router = APIRouter(tags=["health"])


class RuntimeMigrationSummary(BaseModel):
    ok: bool
    current_revision: str | None = None
    head_revision: str | None = None
    error: str | None = None


class RuntimeInfoResponse(BaseModel):
    app_name: str
    app_version: str
    environment: str
    migrations: RuntimeMigrationSummary


@router.get("/health")
@root_router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness_check() -> dict[str, Any]:
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

    if (
        settings.rate_limit_enabled
        or settings.provider_runtime_state_backend == "redis"
    ):
        try:
            await ping_redis()
            checks["redis"] = {"ok": True}
        except Exception as exc:  # noqa: BLE001 - readiness reports dependency state.
            checks["redis"] = {
                "ok": False,
                "error": exc.__class__.__name__,
            }

    ready = all(check["ok"] for check in checks.values())
    if not ready:
        raise ProblemException(
            problem_type="urn:bab:error:not-ready",
            title="Service Unavailable",
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is not ready",
            extra={"readiness_status": "not_ready", "checks": checks},
        )
    return {"status": "ready", "checks": checks}


@router.get("/readyz")
@root_router.get("/readyz")
async def readiness_probe() -> dict[str, Any]:
    return await readiness_check()


@router.get(
    "/runtime-info",
    response_model=RuntimeInfoResponse,
    response_model_exclude={"migrations": {"error"}},
)
async def runtime_info() -> RuntimeInfoResponse:
    try:
        migration_state = await get_migration_state(engine)
        migrations = {
            "ok": bool(migration_state["is_current"]),
            "current_revision": migration_state["current_revision"],
            "head_revision": migration_state["head_revision"],
        }
    except Exception as exc:  # noqa: BLE001 - runtime info should not expose internals.
        migrations = {"ok": False, "error": exc.__class__.__name__}

    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "environment": settings.environment,
        "migrations": migrations,
    }
