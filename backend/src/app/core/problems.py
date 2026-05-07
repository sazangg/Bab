from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

PROBLEM_MEDIA_TYPE = "application/problem+json"

DEFAULT_PROBLEM_TYPES = {
    status.HTTP_400_BAD_REQUEST: ("urn:bab:error:bad-request", "Bad Request"),
    status.HTTP_401_UNAUTHORIZED: ("urn:bab:error:unauthorized", "Unauthorized"),
    status.HTTP_403_FORBIDDEN: ("urn:bab:error:forbidden", "Forbidden"),
    status.HTTP_404_NOT_FOUND: ("urn:bab:error:not-found", "Not Found"),
    status.HTTP_409_CONFLICT: ("urn:bab:error:conflict", "Conflict"),
    status.HTTP_413_CONTENT_TOO_LARGE: (
        "urn:bab:error:payload-too-large",
        "Payload Too Large",
    ),
    status.HTTP_422_UNPROCESSABLE_CONTENT: (
        "urn:bab:error:validation-error",
        "Validation Error",
    ),
    status.HTTP_429_TOO_MANY_REQUESTS: ("urn:bab:error:rate-limited", "Too Many Requests"),
    status.HTTP_500_INTERNAL_SERVER_ERROR: (
        "urn:bab:error:internal-server-error",
        "Internal Server Error",
    ),
}


class ProblemDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str
    instance: str


class ProblemException(Exception):
    def __init__(
        self,
        *,
        type: str,
        title: str,
        status: int,
        detail: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.type = type
        self.title = title
        self.status = status
        self.detail = detail
        self.extra = extra or {}


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemException, problem_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


async def problem_exception_handler(request: Request, exc: ProblemException) -> JSONResponse:
    return _problem_response(
        request=request,
        type=exc.type,
        title=exc.title,
        status_code=exc.status,
        detail=exc.detail,
        extra=exc.extra,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    problem_type, title = _default_problem_type(exc.status_code)
    return _problem_response(
        request=request,
        type=problem_type,
        title=title,
        status_code=exc.status_code,
        detail=_detail_to_string(exc.detail),
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    problem_type, title = _default_problem_type(status.HTTP_422_UNPROCESSABLE_CONTENT)
    return _problem_response(
        request=request,
        type=problem_type,
        title=title,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="Request validation failed",
        extra={"errors": exc.errors()},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    _ = exc
    problem_type, title = _default_problem_type(status.HTTP_500_INTERNAL_SERVER_ERROR)
    return _problem_response(
        request=request,
        type=problem_type,
        title=title,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="An unexpected error occurred",
    )


def _problem_response(
    *,
    request: Request,
    type: str,
    title: str,
    status_code: int,
    detail: str,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    problem = ProblemDetail(
        type=type,
        title=title,
        status=status_code,
        detail=detail,
        instance=request.url.path,
        **(extra or {}),
    )
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(mode="json"),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


def _default_problem_type(status_code: int) -> tuple[str, str]:
    if status_code in DEFAULT_PROBLEM_TYPES:
        return DEFAULT_PROBLEM_TYPES[status_code]

    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        phrase = "HTTP Error"

    return f"urn:bab:error:http-{status_code}", phrase


def _detail_to_string(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    return "HTTP error"
