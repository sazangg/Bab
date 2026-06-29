from fastapi import APIRouter, Response

from app.core.metrics import metrics_response

router = APIRouter(tags=["metrics"], include_in_schema=False)


@router.get("/metrics", include_in_schema=False)
def get_metrics() -> Response:
    return metrics_response()
