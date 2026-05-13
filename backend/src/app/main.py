from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.routes.analytics import router as analytics_router
from app.api.v1.routes.audit_logs import router as audit_logs_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.limit_policies import router as limit_policies_router
from app.api.v1.routes.model_aliases import router as model_aliases_router
from app.api.v1.routes.projects import router as projects_router
from app.api.v1.routes.providers import router as providers_router
from app.api.v1.routes.proxy import router as proxy_router
from app.api.v1.routes.request_logs import router as request_logs_router
from app.api.v1.routes.setup import router as setup_router
from app.api.v1.routes.subscriptions import router as subscriptions_router
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
    app.include_router(analytics_router, prefix="/api/v1")
    app.include_router(audit_logs_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(limit_policies_router, prefix="/api/v1")
    app.include_router(model_aliases_router, prefix="/api/v1")
    app.include_router(providers_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(request_logs_router, prefix="/api/v1")
    app.include_router(setup_router, prefix="/api/v1")
    app.include_router(subscriptions_router, prefix="/api/v1")
    app.include_router(proxy_router)
    return app


app = create_app()
