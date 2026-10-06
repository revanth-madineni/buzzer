import structlog
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

logger = structlog.get_logger()


class BuzzerError(Exception):
    """Base application error."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        extra: dict | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        # Extra body fields (T8), merged after `error`/`message` and never overriding them.
        self.extra = extra
        super().__init__(message)


class NotFoundError(BuzzerError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__("NOT_FOUND", message, status.HTTP_404_NOT_FOUND)


class ForbiddenError(BuzzerError):
    def __init__(self, message: str = "Forbidden"):
        super().__init__("FORBIDDEN", message, status.HTTP_403_FORBIDDEN)


class UnauthorizedError(BuzzerError):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__("UNAUTHORIZED", message, status.HTTP_401_UNAUTHORIZED)


class ConflictError(BuzzerError):
    def __init__(self, message: str = "Conflict"):
        super().__init__("CONFLICT", message, status.HTTP_409_CONFLICT)


class ImageInUseError(BuzzerError):
    """409 IMAGE_IN_USE with the uses the caller may see (T8 §4.6)."""

    def __init__(self, usage: list[dict], hidden_usage_count: int):
        total = len({u["question_id"] for u in usage}) + hidden_usage_count
        super().__init__(
            "IMAGE_IN_USE",
            f"Image is used by {total} question(s)",
            status.HTTP_409_CONFLICT,
            extra={"usage": usage, "hidden_usage_count": hidden_usage_count},
        )


MYSQL_DEADLOCK = 1213
DEADLOCK_MESSAGE = "The server was busy; please try again"


def is_deadlock(exc: BaseException) -> bool:
    """True for a MySQL deadlock (errno 1213), however the driver wrapped it."""
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", None) or ()
    return bool(args) and args[0] == MYSQL_DEADLOCK


def error_body(exc: BuzzerError) -> dict:
    body = {"error": exc.code, "message": exc.message}
    for key, value in (exc.extra or {}).items():
        body.setdefault(key, value)
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BuzzerError)
    async def buzzer_error_handler(request: Request, exc: BuzzerError) -> JSONResponse:
        logger.warning(
            "app_error", code=exc.code, message=exc.message, path=str(request.url)
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc),
        )

    @app.exception_handler(DBAPIError)
    async def db_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
        # T8 §4.0: the image locking scans can still deadlock under concurrent
        # replaces/moves. MySQL has already rolled the transaction back, so nothing
        # was written; tell the client to retry instead of a generic 500.
        if is_deadlock(exc):
            logger.warning("db_deadlock", path=str(request.url))
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"error": "CONFLICT", "message": DEADLOCK_MESSAGE},
            )
        logger.error("unhandled_error", exc_info=exc, path=str(request.url))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning("validation_error", errors=exc.errors(), path=str(request.url))
        # exc.errors() can embed non-JSON-serializable objects (e.g. Pydantic v2 puts the
        # raw exception in a field-validator error's `ctx`), so this must go through
        # jsonable_encoder the same way FastAPI's own default handler does -- passing it
        # straight to JSONResponse crashes with a generic 500 that hides the real error.
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "VALIDATION_ERROR",
                "detail": jsonable_encoder(exc.errors()),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_error", exc_info=exc, path=str(request.url))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            },
        )
