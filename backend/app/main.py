import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes import admin, auth, conversations, documents, google_auth, roles, users
from app.api.routes.health import router
from app.api.upload_limits import UploadLimitMiddleware
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SecureRAG API",
        version="0.1.0",
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.app_env == "production" else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    app.add_middleware(UploadLimitMiddleware)
    app.include_router(router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(google_auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(roles.router, prefix="/api/v1")
    app.include_router(documents.router, prefix="/api/v1")
    app.include_router(conversations.router, prefix="/api/v1")

    @app.middleware("http")
    async def prevent_sensitive_caching(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/v1/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # FastAPI's default errors may echo raw password input. Return locations/types only.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(item["loc"]), "type": item["type"], "msg": "Invalid value"}
                    for item in error.errors()
                ]
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        # Never include SQL/parameters or connection credentials in client responses.
        original = getattr(error, "orig", None)
        reason = str(original).lower()
        category = (
            "dns"
            if any(
                word in reason
                for word in (
                    "getaddrinfo",
                    "failed to resolve",
                    "name or service not known",
                )
            )
            else "database"
        )
        logger.warning(
            "Database request failed: type=%s category=%s sqlstate=%s",
            type(error).__name__,
            category,
            getattr(original, "sqlstate", None),
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "Database is temporarily unavailable"},
            headers={"Cache-Control": "no-store"},
        )

    return app


app = create_app()
