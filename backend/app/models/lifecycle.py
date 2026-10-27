"""Lifecycle requests (renewal, replacement, release/refund) and in-app notifications.

Requests keep their identity fixed and record every transition in an
append-only event table. Notifications are de-duplicated per recipient by an
event key, so repeated checks or page loads never create copies.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DDL, ForeignKey, Index, Integer, String, UniqueConstraint, event, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow
from app.db.types import UTCDateTime
from app.models.enums import LifecycleRequestStatus, LifecycleRequestType, enum_column

if TYPE_CHECKING:
    from app.models.fdr import FDR
    from app.models.user import User

OPEN_REQUEST_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "CLARIFICATION_REQUESTED", "APPROVED")


class LifecycleRequest(TimestampMixin, Base):
    __tablename__ = "lifecycle_requests"
    __table_args__ = (
        # One open request per FDR at a time; enforced by the database.
        Index(
            "uq_lifecycle_requests_open_fdr",
            "fdr_id",
            unique=True,
            sqlite_where=text("status IN ('SUBMITTED', 'UNDER_REVIEW', 'CLARIFICATION_REQUESTED', 'APPROVED')"),
        ),
        Index("ix_lifecycle_requests_institution_status", "institution_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_type: Mapped[LifecycleRequestType] = mapped_column(enum_column(LifecycleRequestType))
    # The existing instrument the request is about. Its details are never changed by the request.
    fdr_id: Mapped[int] = mapped_column(ForeignKey("fdrs.id", ondelete="RESTRICT"), index=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id", ondelete="RESTRICT"))
    # Renewal/replacement: the new instrument, created as a separate PROPOSED FDR.
    successor_fdr_id: Mapped[int | None] = mapped_column(
        ForeignKey("fdrs.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[LifecycleRequestStatus] = mapped_column(
        enum_column(LifecycleRequestStatus), default=LifecycleRequestStatus.SUBMITTED, index=True
    )
    reason: Mapped[str] = mapped_column(String(2000))
    supporting_note: Mapped[str | None] = mapped_column(String(2000))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # Administrative reference recorded at completion (e.g. an order number). Not a payment record.
    completion_reference: Mapped[str | None] = mapped_column(String(100))

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    __mapper_args__ = {"version_id_col": version}

    fdr: Mapped["FDR"] = relationship(foreign_keys=[fdr_id])
    successor: Mapped["FDR | None"] = relationship(foreign_keys=[successor_fdr_id])
    created_by: Mapped["User"] = relationship()
    events: Mapped[list["LifecycleRequestEvent"]] = relationship(
        back_populates="request", order_by="LifecycleRequestEvent.id"
    )


class LifecycleRequestEvent(Base):
    """One transition of a lifecycle request. Append-only."""

    __tablename__ = "lifecycle_request_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("lifecycle_requests.id", ondelete="RESTRICT"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[LifecycleRequestStatus | None] = mapped_column(enum_column(LifecycleRequestStatus))
    to_status: Mapped[LifecycleRequestStatus] = mapped_column(enum_column(LifecycleRequestStatus))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    actor_role: Mapped[str] = mapped_column(String(32))
    # Visible to the institution (its own messages, AICTE messages to it).
    message: Mapped[str | None] = mapped_column(String(2000))
    # AICTE-only notes. Never returned to institutions.
    internal_note: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    request: Mapped[LifecycleRequest] = relationship(back_populates="events")
    actor: Mapped["User"] = relationship()


class Notification(Base):
    """An in-app notification for one user. Content is immutable; only read state changes."""

    __tablename__ = "notifications"
    __table_args__ = (
        # The same event never notifies the same person twice.
        UniqueConstraint("recipient_id", "dedup_key", name="uq_notifications_recipient_dedup_key"),
        Index("ix_notifications_recipient_read", "recipient_id", "read_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    event_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(500))
    # In-app path only (validated to start with "/").
    link: Mapped[str | None] = mapped_column(String(200))
    fdr_id: Mapped[int | None] = mapped_column(ForeignKey("fdrs.id", ondelete="RESTRICT"))
    dedup_key: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


# Kept in sync with the Alembic migration that creates the same triggers.
LIFECYCLE_TRIGGERS = [
    "CREATE TRIGGER IF NOT EXISTS lifecycle_requests_identity_immutable "
    "BEFORE UPDATE OF request_type, fdr_id, institution_id, successor_fdr_id, reason, created_by_id, created_at "
    "ON lifecycle_requests BEGIN SELECT RAISE(ABORT, 'lifecycle request identity is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS lifecycle_requests_final "
    "BEFORE UPDATE ON lifecycle_requests WHEN OLD.status IN ('REJECTED', 'WITHDRAWN', 'COMPLETED') "
    "BEGIN SELECT RAISE(ABORT, 'a closed lifecycle request cannot be changed'); END",
    "CREATE TRIGGER IF NOT EXISTS lifecycle_requests_no_delete BEFORE DELETE ON lifecycle_requests "
    "BEGIN SELECT RAISE(ABORT, 'lifecycle requests cannot be deleted'); END",
    "CREATE TRIGGER IF NOT EXISTS lifecycle_request_events_no_update BEFORE UPDATE ON lifecycle_request_events "
    "BEGIN SELECT RAISE(ABORT, 'lifecycle_request_events is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS lifecycle_request_events_no_delete BEFORE DELETE ON lifecycle_request_events "
    "BEGIN SELECT RAISE(ABORT, 'lifecycle_request_events is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS notifications_content_immutable "
    "BEFORE UPDATE OF recipient_id, event_type, title, body, link, fdr_id, dedup_key, created_at ON notifications "
    "BEGIN SELECT RAISE(ABORT, 'notification content is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS notifications_no_delete BEFORE DELETE ON notifications "
    "BEGIN SELECT RAISE(ABORT, 'notifications cannot be deleted'); END",
]

for _model in (LifecycleRequest, LifecycleRequestEvent, Notification):
    for _statement in LIFECYCLE_TRIGGERS:
        if f" ON {_model.__tablename__} " in _statement:
            event.listen(_model.__table__, "after_create", DDL(_statement).execute_if(dialect="sqlite"))
