"""Transport adapters for structured PersonAgent errors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from personagent.domain.exceptions import (
    ErrorCategory,
    ErrorSeverity,
    InvalidRequestError,
    PersonAgentError,
    ensure_personagent_error,
)

logger = structlog.get_logger(__name__)


def install_error_handlers(app: FastAPI) -> None:
    """Install centralized JSON error handlers on a FastAPI app."""

    @app.exception_handler(PersonAgentError)
    async def handle_personagent_error(
        request: Request,
        exc: PersonAgentError,
    ) -> JSONResponse:
        logger.warning(
            "personagent_api_error",
            code=exc.code,
            category=exc.category.value,
            status=exc.http_status,
            retryable=exc.retryable,
            correlation_id=exc.correlation_id,
            path=str(request.url.path),
        )
        return json_error_response(exc)

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        error = http_exception_to_error(exc)
        logger.warning(
            "http_api_error",
            code=error.code,
            category=error.category.value,
            status=error.http_status,
            retryable=error.retryable,
            correlation_id=error.correlation_id,
            path=str(request.url.path),
        )
        return json_error_response(error)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        error = InvalidRequestError(
            "Request validation failed.",
            code="request.validation_failed",
            http_status=422,
            metadata={"errors": exc.errors()},
            cause=exc,
        )
        logger.warning(
            "request_validation_failed",
            correlation_id=error.correlation_id,
            path=str(request.url.path),
        )
        return json_error_response(error)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        error = ensure_personagent_error(exc)
        logger.exception(
            "unhandled_api_error",
            code=error.code,
            category=error.category.value,
            status=error.http_status,
            correlation_id=error.correlation_id,
            path=str(request.url.path),
        )
        return json_error_response(error)


def json_error_response(error: PersonAgentError) -> JSONResponse:
    """Return a compatibility-preserving JSON error response."""
    envelope = error.to_envelope()
    return JSONResponse(
        status_code=error.http_status,
        content={
            "detail": error.user_message,
            "error": envelope,
        },
    )


def http_exception_to_error(exc: HTTPException) -> PersonAgentError:
    """Convert FastAPI HTTPException into a structured domain error."""
    detail = exc.detail
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        raw = detail["error"]
        return PersonAgentError(
            str(raw.get("message") or raw.get("detail") or exc.status_code),
            code=str(raw.get("code") or _code_for_http_status(exc.status_code)),
            category=str(raw.get("category") or _category_for_http_status(exc.status_code)),
            severity=str(raw.get("severity") or ErrorSeverity.ERROR.value),
            http_status=exc.status_code,
            retryable=bool(raw.get("retryable", False)),
            metadata=_metadata_from_headers(exc.headers),
        )
    message = str(detail) if detail is not None else f"HTTP {exc.status_code}"
    return PersonAgentError(
        message,
        code=_code_for_http_status(exc.status_code),
        category=_category_for_http_status(exc.status_code),
        severity=ErrorSeverity.ERROR,
        http_status=exc.status_code,
        retryable=exc.status_code in {408, 409, 429, 500, 502, 503, 504},
        metadata=_metadata_from_headers(exc.headers),
    )


def error_event(
    exc: BaseException,
    *,
    status_code: int | None = None,
    default_message: str = "Unexpected internal error.",
) -> dict[str, Any]:
    """Serialize an exception for SSE/WebSocket streams."""
    if isinstance(exc, HTTPException):
        error = http_exception_to_error(exc)
    else:
        error = ensure_personagent_error(exc, default_message=default_message)
    if status_code is not None and not isinstance(exc, PersonAgentError):
        error.http_status = status_code
    envelope = error.to_envelope()
    return {
        "event": "error",
        "error": envelope["message"],
        "error_detail": envelope,
        "status": envelope["status"],
    }


def tool_error_metadata(error: PersonAgentError) -> dict[str, Any]:
    """Return metadata payload embedded in ToolResult.metadata."""
    return {"error": error.to_envelope()}


def _code_for_http_status(status_code: int) -> str:
    if status_code == 400:
        return "request.invalid"
    if status_code == 401:
        return "auth.required"
    if status_code == 403:
        return "auth.forbidden"
    if status_code == 404:
        return "request.not_found"
    if status_code == 409:
        return "request.conflict"
    if status_code == 413:
        return "request.too_large"
    if status_code == 422:
        return "request.validation_failed"
    if status_code == 429:
        return "request.rate_limited"
    if status_code == 504:
        return "system.timeout"
    if 500 <= status_code <= 599:
        return "system.internal_error"
    return "request.error"


def _category_for_http_status(status_code: int) -> str:
    if status_code in {401, 403}:
        return str(ErrorCategory.AUTH.value)
    if status_code >= 500:
        return str(ErrorCategory.SYSTEM.value)
    return str(ErrorCategory.REQUEST.value)


def _metadata_from_headers(headers: Mapping[str, str] | None) -> dict[str, Any]:
    if not headers:
        return {}
    retry_after = headers.get("retry-after") or headers.get("Retry-After")
    return {"retry_after": retry_after} if retry_after else {}


__all__ = [
    "error_event",
    "http_exception_to_error",
    "install_error_handlers",
    "json_error_response",
    "tool_error_metadata",
]
