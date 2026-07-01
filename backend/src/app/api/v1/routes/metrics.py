import secrets

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.config import settings
from app.core.metrics import metrics_response

router = APIRouter(tags=["metrics"], include_in_schema=False)


@router.get("/metrics", include_in_schema=False)
def get_metrics(request: Request) -> Response:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="metrics not found")
    _require_metrics_access(request)
    return metrics_response()


def _require_metrics_access(request: Request) -> None:
    token = settings.metrics_bearer_token
    if token is None:
        return
    authorization = request.headers.get("authorization")
    scheme, _, presented_token = (authorization or "").partition(" ")
    if (
        scheme != "Bearer"
        or not presented_token
        or not secrets.compare_digest(presented_token, token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="metrics authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
