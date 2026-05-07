from fastapi import FastAPI

from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.setup import router as setup_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.problems import install_problem_handlers


def create_app() -> FastAPI:
    configure_logging(environment=settings.environment)
    app = FastAPI(title="Bab API")
    install_problem_handlers(app)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(setup_router, prefix="/api/v1")
    return app


app = create_app()
