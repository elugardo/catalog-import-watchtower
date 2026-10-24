"""FastAPI application: API under `/api`, the built SPA everywhere else."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.routers import health
from app.settings import get_settings

API_PREFIX = "/api"

# HTTP status -> error `code` for errors that are not raised by our own code
# with an explicit code (see `_docs/api.md` -> *Codes*).
_STATUS_CODES = {
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    422: "INVALID_FIELD",
    500: "INTERNAL_ERROR",
}


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
    )

    app.include_router(health.router, prefix=API_PREFIX)

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
        return error_response(422, "INVALID_FIELD", "request validation failed", list(exc.errors()))

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        """History fallback: files from the bundle when they exist, `index.html` otherwise."""
        if full_path == API_PREFIX.lstrip("/") or full_path.startswith(
            API_PREFIX.lstrip("/") + "/"
        ):
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
