"""The signed-in user's own notifications. Nobody can read or change another user's."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, update

from app.api.deps import CurrentUser, DbSession
from app.db.base import utcnow
from app.models.lifecycle import Notification
from app.schemas.common import Page
from app.schemas.lifecycle import MarkAllResult, NotificationRead, UnreadCount

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Page[NotificationRead])
def list_notifications(
    user: CurrentUser,
    db: DbSession,
    unread_only: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[NotificationRead]:
    query = select(Notification).where(Notification.recipient_id == user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Notification.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return Page[NotificationRead](items=[NotificationRead.model_validate(n) for n in rows], total=total, page=page,
                                  page_size=page_size)


@router.get("/unread-count", response_model=UnreadCount)
def unread_count(user: CurrentUser, db: DbSession) -> UnreadCount:
    count = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.recipient_id == user.id, Notification.read_at.is_(None)))
    return UnreadCount(unread=count or 0)


@router.post("/{notification_id}/read", response_model=NotificationRead)
def mark_read(notification_id: int, user: CurrentUser, db: DbSession) -> Notification:
    notification = db.get(Notification, notification_id)
    # Someone else's notification is indistinguishable from a missing one.
    if notification is None or notification.recipient_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if notification.read_at is None:
        notification.read_at = utcnow()
        db.commit()
    return notification


@router.post("/read-all", response_model=MarkAllResult)
def mark_all_read(user: CurrentUser, db: DbSession) -> MarkAllResult:
    result = db.execute(
        update(Notification)
        .where(Notification.recipient_id == user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()
    return MarkAllResult(marked=result.rowcount or 0)
