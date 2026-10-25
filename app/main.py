"""FastAPI application: API under `/api`, the built SPA everywhere else."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.routers import health, imports
from app.schemas.upload import UploadRejected
from app.services.importer import sweep_stuck_imports
from app.settings import get_settings

log = logging.getLogger(__name__)

API_PREFIX = "/api"
_API_SEGMENT = API_PREFIX.lstrip("/")

# HTTP status -> error `code` for errors that are not raised by our own code
# with an explicit code (see `_docs/api.md` -> *Codes*).
_STATUS_CODES = {
    400: "INVALID_FIELD",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "FILE_TOO_LARGE",
    500: "INTERNAL_ERROR",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup crash recovery (`_docs/architecture.md`, step 5). Runs in `app` only.

    A database that is down at startup must not stop the app: the failure is
    logged by exception type only (the message can carry the DSN) and
    `/api/health` reports `degraded`.
    """
    try:
        sweep_stuck_imports()
    except Exception as exc:  # noqa: BLE001
        log.warning("startup sweep skipped: %s", type(exc).__name__)
    yield


def error_response(
    status_code: int, code: str, message: str, details: list | None = None
) -> JSONResponse:
    """The one error shape of `_docs/api.md`."""
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "details": details or []},
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Catalog Import Watchtower",
        version=get_settings().app_version,
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(imports.router, prefix=API_PREFIX)

    @app.exception_handler(UploadRejected)
    async def upload_rejected_handler(request: Request, exc: UploadRejected) -> Response:
        return error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            detail = exc.detail
            return error_response(
                exc.status_code, detail["code"], detail.get("message", ""), detail.get("details")
            )
        code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").lower()
        return error_response(exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> Response:
        # No request ever ends in 422 (`_docs/api.md` -> *Errors*). A malformed
        # path parameter (an import id that is not an integer >= 1) names no
        # resource, so it is a 404; anything else is a 400.
        errors = exc.errors()
        if any(error.get("loc", ())[:1] == ("path",) for error in errors):
            return error_response(404, "NOT_FOUND", "no such resource")
        details = [
            {"loc": [str(part) for part in error.get("loc", ())], "message": str(error.get("msg"))}
            for error in errors
        ]
        return error_response(400, "INVALID_FIELD", "request validation failed", details)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        # Without this, Starlette answers a crash with `text/plain "Internal Server
        # Error"`, outside the one error shape. The exception is still re-raised to
        # the server log by Starlette after this response is sent; the message here
        # stays generic so nothing internal leaks to the client.
        return error_response(500, "INTERNAL_ERROR", "internal error")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        """History fallback: files from the bundle when they exist, `index.html` otherwise."""
        if full_path == _API_SEGMENT or full_path.startswith(_API_SEGMENT + "/"):
            return error_response(404, "NOT_FOUND", f"no API route at /{full_path}")

        static_dir: Path = get_settings().static_dir
        if full_path:
            candidate = (static_dir / full_path).resolve()
            if candidate.is_file() and static_dir.resolve() in candidate.parents:
                return FileResponse(candidate)

        index = static_dir / "index.html"
        if not index.is_file():
            return error_response(
                404,
                "NOT_FOUND",
                "frontend bundle not built; run `npm run build` in web/ or use the Docker image",
            )
        return FileResponse(index, media_type="text/html")

    return app


app = create_app()
