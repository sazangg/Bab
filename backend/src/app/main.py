from fastapi import FastAPI

from app.api.v1.routes.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="Bab API")
    app.include_router(health_router, prefix="/api/v1")
    return app


app = create_app()
