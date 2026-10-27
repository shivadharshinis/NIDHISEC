"""Top-level API router. Register new feature routers here."""

from fastapi import APIRouter

from app.api.routes import (
    audit_logs,
    auth,
    dashboard,
    documents,
    fdrs,
    health,
    institutions,
    lifecycle,
    notifications,
    screening,
    verification,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(fdrs.router)
api_router.include_router(documents.router)
api_router.include_router(verification.router)
api_router.include_router(screening.router)
api_router.include_router(lifecycle.router)
api_router.include_router(notifications.router)
api_router.include_router(dashboard.router)
api_router.include_router(institutions.router)
api_router.include_router(audit_logs.router)
