"""FastAPI application entry point.

Run from the `backend` directory:
    uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app import __version__
from app.api.router import api_router
from app.core.config import get_settings
from app.core.security import get_jwt_secret
from app.core.upload_limit import UploadSizeLimitMiddleware
from app.db.session import engine
from app.services.document_storage import storage_root

logger = logging.getLogger("nidhisec")
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Fail fast if the token signing key is missing outside development.
    get_jwt_secret()
    storage_root()  # create the private document store if needed
    # The schema is managed by Alembic (`alembic upgrade head`), not created here.
    if not inspect(engine).has_table("alembic_version"):
        logger.warning("Database schema is not initialised. Run `alembic upgrade head` in the backend folder.")
    yield
    engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description=settings.app_description,
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Added before CORS so that CORS wraps it and early 411/413 responses keep CORS headers.
app.add_middleware(
    UploadSizeLimitMiddleware,
    max_file_bytes=settings.max_upload_bytes,
    path_pattern=rf"{settings.api_prefix}/fdrs/\d+/documents",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith(settings.api_prefix) and not request.url.path.startswith(f"{settings.api_prefix}/docs"):
        # API responses may contain personal or financial data; never cache them.
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(StaleDataError)
async def stale_data_handler(_request: Request, _exc: StaleDataError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "This record was changed by someone else. Reload it and try again."},
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_request: Request, exc: IntegrityError) -> JSONResponse:
    logger.warning("Integrity error: %s", exc.orig)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "The request conflicts with existing data."},
    )


app.include_router(api_router, prefix=settings.api_prefix)
