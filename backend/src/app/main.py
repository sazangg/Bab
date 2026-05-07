from fastapi import FastAPI

from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.setup import router as setup_router


def create_app() -> FastAPI:
    app = FastAPI(title="Bab API")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(setup_router, prefix="/api/v1")
    return app


app = create_app()
