import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: dict | None = None, headers: dict | None = None
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers


def _envelope(status: int, code: str, message: str, details: dict, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details}},
        headers=headers,
    )


def _http_code(status: int) -> str:
    return {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(status, f"HTTP_{status}")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _envelope(exc.status, exc.code, exc.message, exc.details, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(422, "VALIDATION_ERROR", "Request validation failed",
                         {"errors": jsonable_encoder(exc.errors())})

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _envelope(exc.status_code, _http_code(exc.status_code), str(exc.detail), {},
                         headers=getattr(exc, "headers", None))

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        # A constraint lost a race the service could not name (specific cases are mapped earlier).
        logger.warning("Database constraint conflict on %s %s", request.method, request.url.path, exc_info=exc)
        return _envelope(409, "CONFLICT", "The request conflicts with current data", {})

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception", exc_info=exc)
        return _envelope(500, "INTERNAL_ERROR", "Internal server error", {})
