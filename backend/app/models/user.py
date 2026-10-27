from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.types import UTCDateTime
from app.models.enums import UserRole, enum_column

if TYPE_CHECKING:
    from app.models.institution import Institution


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Institution users must belong to exactly one institution; other roles must not.
        CheckConstraint(
            "(role = 'INSTITUTION' AND institution_id IS NOT NULL)"
            " OR (role != 'INSTITUTION' AND institution_id IS NULL)",
            name="institution_matches_role",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150))
    # Stored lower-case; unique login identifier.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    # Argon2id hash. Never serialised in API responses.
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(enum_column(UserRole))
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    institution: Mapped["Institution | None"] = relationship(back_populates="users")
