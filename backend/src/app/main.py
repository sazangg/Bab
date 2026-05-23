from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.routes.activity import router as activity_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.projects import router as projects_router
from app.api.v1.routes.providers import router as providers_router
from app.api.v1.routes.proxy import router as proxy_router
from app.api.v1.routes.teams import router as teams_router
from app.api.v1.routes.usage import router as usage_router
from app.core.bootstrap import create_development_database, ensure_default_workspace
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.problems import install_problem_handlers


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.environment == "development":
        await create_development_database()
        await ensure_default_workspace()
    yield


def create_app() -> FastAPI:
    configure_logging(environment=settings.environment)
    app = FastAPI(title="Bab API", lifespan=lifespan)
    install_problem_handlers(app)
    app.include_router(activity_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(providers_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(teams_router, prefix="/api/v1")
    app.include_router(usage_router, prefix="/api/v1")
    app.include_router(proxy_router)
    return app


app = create_app()
