from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Confirm the API is running and the database is reachable."""
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except SQLAlchemyError:
        database = "error"

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        service=settings.app_name,
        description=settings.app_description,
        version=__version__,
        environment=settings.environment,
        database=database,
        timestamp=datetime.now(timezone.utc),
    )
