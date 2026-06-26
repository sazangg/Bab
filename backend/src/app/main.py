from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.routes.activity import router as activity_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.gateway_history import router as gateway_history_router
from app.api.v1.routes.guardrails import router as guardrails_router
from app.api.v1.routes.health import root_router as root_health_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.policies import router as policies_router
from app.api.v1.routes.projects import router as projects_router
from app.api.v1.routes.providers import router as providers_router
from app.api.v1.routes.proxy import router as proxy_router
from app.api.v1.routes.settings import router as settings_router
from app.api.v1.routes.teams import router as teams_router
from app.api.v1.routes.usage import router as usage_router
from app.api.v1.routes.virtual_keys import router as virtual_keys_router
from app.core.bootstrap import create_development_database, ensure_default_workspace
from app.core.config import settings, validate_runtime_settings
from app.core.database import engine
from app.core.logging import configure_logging
from app.core.migrations import run_database_migrations
from app.core.problems import install_problem_handlers
from app.core.request_context import request_context_middleware


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validate_runtime_settings()
    if settings.environment == "development":
        await create_development_database()
        await run_database_migrations(engine)
        await ensure_default_workspace()
    yield


def create_app() -> FastAPI:
    configure_logging(environment=settings.environment)
    Path(settings.assets_dir).mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Bab API", lifespan=lifespan)
    app.middleware("http")(request_context_middleware)
    install_problem_handlers(app)
    app.include_router(activity_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(gateway_history_router, prefix="/api/v1")
    app.include_router(guardrails_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(policies_router, prefix="/api/v1")
    app.include_router(providers_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(settings_router, prefix="/api/v1")
    app.include_router(teams_router, prefix="/api/v1")
    app.include_router(usage_router, prefix="/api/v1")
    app.include_router(virtual_keys_router, prefix="/api/v1")
    app.include_router(root_health_router)
    app.include_router(proxy_router)
    app.mount("/assets", StaticFiles(directory=settings.assets_dir), name="assets")
    return app


app = create_app()
