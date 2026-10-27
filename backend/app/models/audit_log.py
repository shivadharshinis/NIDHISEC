from datetime import datetime
from typing import Any

from sqlalchemy import DDL, JSON, ForeignKey, Index, Integer, String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.db.types import UTCDateTime


class AuditLog(Base):
    """Append-only record of security-relevant actions.

    Actor details are snapshotted so entries stay meaningful if a user changes.
    UPDATE and DELETE are blocked by database triggers.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    actor_email: Mapped[str | None] = mapped_column(String(254))
    actor_name: Mapped[str | None] = mapped_column(String(150))
    actor_role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    # Institution the affected record belongs to, for scoping audit views.
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id", ondelete="RESTRICT"))
    summary: Mapped[str] = mapped_column(String(500))
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))


# Kept in sync with the Alembic migration that creates the same triggers.
AUDIT_LOG_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS audit_logs_no_update BEFORE UPDATE ON audit_logs
    BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_logs_no_delete BEFORE DELETE ON audit_logs
    BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END
    """,
]

for _statement in AUDIT_LOG_TRIGGERS:
    event.listen(AuditLog.__table__, "after_create", DDL(_statement).execute_if(dialect="sqlite"))
