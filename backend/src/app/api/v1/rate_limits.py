import structlog
from fastapi import HTTPException, Request, status

from app.core.metrics import record_rate_limit_rejection
from app.core.rate_limiter import (
    RateLimitDecision,
    RateLimitRule,
    inspect_rate_limits,
    record_rate_limit_attempt,
)

logger = structlog.get_logger(__name__)

AUTH_LOGIN = "auth_login"
AUTH_INVITE_ACCEPT = "auth_invite_accept"
AUTH_REFRESH = "auth_refresh"
PROXY_AUTH = "proxy_auth"


async def enforce_auth_login_rate_limit(*, request: Request, email: str) -> None:
    await _enforce(
        [
            RateLimitRule(AUTH_LOGIN, "ip", _client_ip(request), 20, 10 * 60),
            RateLimitRule(AUTH_LOGIN, "email", email.strip().lower(), 5, 15 * 60),
        ]
    )


async def enforce_invite_accept_rate_limit(*, request: Request, token: str) -> None:
    await _enforce(
        [
            RateLimitRule(AUTH_INVITE_ACCEPT, "ip", _client_ip(request), 20, 10 * 60),
            RateLimitRule(AUTH_INVITE_ACCEPT, "token", token, 5, 60 * 60),
        ]
    )


async def enforce_refresh_rate_limit(*, request: Request, refresh_token: str | None) -> None:
    rules = [RateLimitRule(AUTH_REFRESH, "ip", _client_ip(request), 60, 10 * 60)]
    if refresh_token:
        rules.append(RateLimitRule(AUTH_REFRESH, "token", refresh_token, 10, 60))
    await _enforce(rules)


async def preflight_proxy_auth_rate_limit(
    *,
    request: Request,
    presented_key: str | None,
) -> None:
    await _enforce(
        _proxy_rules(request=request, presented_key=presented_key),
        inspect=True,
    )


async def record_proxy_auth_failure(
    *,
    request: Request,
    presented_key: str | None,
) -> None:
    await _enforce(_proxy_rules(request=request, presented_key=presented_key))


def _proxy_rules(*, request: Request, presented_key: str | None) -> list[RateLimitRule]:
    rules = [RateLimitRule(PROXY_AUTH, "ip", _client_ip(request), 60, 60)]
    if presented_key:
        rules.append(RateLimitRule(PROXY_AUTH, "key", presented_key, 20, 60))
    return rules


async def _enforce(rules: list[RateLimitRule], *, inspect: bool = False) -> None:
    if inspect:
        decision = await inspect_rate_limits(rules)
    else:
        decision = await record_rate_limit_attempt(rules)
    if decision.allowed:
        return
    _record_rejection(decision)
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="too many requests",
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


def _record_rejection(decision: RateLimitDecision) -> None:
    record_rate_limit_rejection(
        route_group=decision.route_group,
        bucket_type=decision.bucket_type,
    )
    logger.warning(
        "rate_limit_rejected",
        route_group=decision.route_group,
        bucket_type=decision.bucket_type,
        retry_after_seconds=decision.retry_after_seconds,
        limit=decision.limit,
        window_seconds=decision.window_seconds,
    )


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
