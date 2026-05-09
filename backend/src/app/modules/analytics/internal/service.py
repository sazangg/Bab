from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.analytics.internal import repository
from app.modules.analytics.schemas import (
    AnalyticsRecentRequest,
    AnalyticsSummaryResponse,
    AnalyticsTimeSeriesPoint,
    AnalyticsTopKey,
    AnalyticsTotals,
)
from app.modules.request_logs.internal.models import RequestLog


async def get_summary(
    *,
    scope: Scope,
    days: int,
    recent_limit: int,
    db: AsyncSession,
) -> AnalyticsSummaryResponse:
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    request_logs = await repository.list_request_logs_since(org_id=scope.org_id, since=since, db=db)
    key_ids = {request_log.virtual_key_id for request_log in request_logs}
    keys_by_id = await repository.list_virtual_keys_by_id(
        org_id=scope.org_id,
        key_ids=key_ids,
        db=db,
    )

    return AnalyticsSummaryResponse(
        totals=_build_totals(request_logs),
        recent_requests=_build_recent_requests(request_logs, recent_limit),
        top_keys=_build_top_keys(request_logs, keys_by_id),
        time_series=_build_time_series(request_logs),
    )


def _build_totals(request_logs: list[RequestLog]) -> AnalyticsTotals:
    request_count = len(request_logs)
    success_count = sum(1 for request_log in request_logs if request_log.http_status < 400)
    latency_total = sum(request_log.latency_ms for request_log in request_logs)

    return AnalyticsTotals(
        request_count=request_count,
        success_count=success_count,
        error_count=request_count - success_count,
        prompt_tokens=sum(request_log.prompt_tokens or 0 for request_log in request_logs),
        completion_tokens=sum(request_log.completion_tokens or 0 for request_log in request_logs),
        total_tokens=sum(request_log.total_tokens or 0 for request_log in request_logs),
        average_latency_ms=round(latency_total / request_count) if request_count else None,
    )


def _build_recent_requests(
    request_logs: list[RequestLog],
    recent_limit: int,
) -> list[AnalyticsRecentRequest]:
    return [
        AnalyticsRecentRequest(
            id=request_log.id,
            project_id=request_log.project_id,
            virtual_key_id=request_log.virtual_key_id,
            provider_id=request_log.provider_id,
            requested_model=request_log.requested_model,
            provider_model=request_log.provider_model,
            http_status=request_log.http_status,
            latency_ms=request_log.latency_ms,
            total_tokens=request_log.total_tokens,
            error_code=request_log.error_code,
            created_at=request_log.created_at,
        )
        for request_log in request_logs[:recent_limit]
    ]


def _build_top_keys(
    request_logs: list[RequestLog],
    keys_by_id: dict[UUID, object],
) -> list[AnalyticsTopKey]:
    requests_by_key: dict[UUID, int] = defaultdict(int)
    tokens_by_key: dict[UUID, int] = defaultdict(int)

    for request_log in request_logs:
        requests_by_key[request_log.virtual_key_id] += 1
        tokens_by_key[request_log.virtual_key_id] += request_log.total_tokens or 0

    sorted_key_ids = sorted(
        requests_by_key,
        key=lambda key_id: (requests_by_key[key_id], tokens_by_key[key_id]),
        reverse=True,
    )

    return [
        AnalyticsTopKey(
            virtual_key_id=key_id,
            key_name=getattr(keys_by_id.get(key_id), "name", "Unknown key"),
            request_count=requests_by_key[key_id],
            total_tokens=tokens_by_key[key_id],
        )
        for key_id in sorted_key_ids[:5]
    ]


def _build_time_series(request_logs: list[RequestLog]) -> list[AnalyticsTimeSeriesPoint]:
    requests_by_bucket: dict[datetime, int] = defaultdict(int)
    tokens_by_bucket: dict[datetime, int] = defaultdict(int)

    for request_log in request_logs:
        bucket = request_log.created_at.astimezone(UTC).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        requests_by_bucket[bucket] += 1
        tokens_by_bucket[bucket] += request_log.total_tokens or 0

    return [
        AnalyticsTimeSeriesPoint(
            bucket=bucket,
            request_count=requests_by_bucket[bucket],
            total_tokens=tokens_by_bucket[bucket],
        )
        for bucket in sorted(requests_by_bucket)
    ]
