"""Domain exceptions + FastAPI handlers (backend_design_prd 에러 코드 표)."""
from __future__ import annotations

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class LLPError(Exception):
    """Base domain error mapped to a structured ErrorResponse."""

    status_code = 400
    error_code = "LLP_ERROR"

    def __init__(self, message: str, details=None):
        super().__init__(message)
        self.message = message
        self.details = details


class SchemaValidationError(LLPError):
    """Missing required field such as inputs_hash / method_ver (FR-1 → 422)."""

    status_code = 422
    error_code = "SCHEMA_VALIDATION_FAILED"


class AppendOnlyViolation(LLPError):
    """Attempt to mutate an append-only L1 row (NFR-4)."""

    status_code = 409
    error_code = "APPEND_ONLY_VIOLATION"


class NotFoundError(LLPError):
    status_code = 404
    error_code = "NOT_FOUND"


class ConflictError(LLPError):
    status_code = 409
    error_code = "CONFLICT"


class FusionError(LLPError):
    status_code = 400
    error_code = "FUSION_ERROR"


async def llp_error_handler(_request: Request, exc: LLPError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message, "details": exc.details},
    )


# Map HTTP status codes (from HTTPException, e.g. auth/RBAC in deps.py) to error codes
# so every error response shares the ErrorResponse envelope, not FastAPI's {"detail": ...}.
_STATUS_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
}


async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Normalise HTTPException (incl. auth/RBAC 401/403) into the ErrorResponse envelope."""
    error_code = _STATUS_ERROR_CODES.get(exc.status_code, "HTTP_ERROR")
    detail = exc.detail
    message = detail if isinstance(detail, str) else "request failed"
    details = None if isinstance(detail, str) else detail
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": error_code, "message": message, "details": details},
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Normalise request validation failures (422) into the ErrorResponse envelope."""
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "request validation failed",
            "details": jsonable_encoder(exc.errors()),
        },
    )
