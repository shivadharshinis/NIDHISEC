from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import DbSession, require_roles
from app.models import AuditLog, UserRole
from app.schemas.audit import AuditLogRead
from app.schemas.common import Page
from app.schemas.fdr import IST

router = APIRouter(
    prefix="/audit-logs",
    tags=["audit"],
    dependencies=[Depends(require_roles(UserRole.AICTE_OFFICIAL))],
)


@router.get("", response_model=Page[AuditLogRead])
def list_audit_logs(
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    action: Annotated[str | None, Query(max_length=64)] = None,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: int | None = None,
    actor_email: Annotated[str | None, Query(max_length=254)] = None,
    date_from: Annotated[date | None, Query(description="Inclusive, Indian Standard Time")] = None,
    date_to: Annotated[date | None, Query(description="Inclusive, Indian Standard Time")] = None,
) -> Page[AuditLogRead]:
    """Read-only, AICTE-only view of the audit trail. There is no endpoint to modify entries."""
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(AuditLog.entity_id == entity_id)
    if actor_email:
        query = query.where(AuditLog.actor_email == actor_email.strip().lower())
    if date_from:
        query = query.where(AuditLog.created_at >= datetime.combine(date_from, time.min, IST))
    if date_to:
        query = query.where(AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min, IST))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return Page[AuditLogRead](
        items=[AuditLogRead.model_validate(row) for row in rows], total=total, page=page, page_size=page_size
    )
