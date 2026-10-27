from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.fdr import FDR
    from app.models.user import User


class Institution(TimestampMixin, Base):
    """An AICTE-approved institution. Having a record here does not imply that
    the institution is required to maintain an FDR."""

    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    # Stored upper-case; unique across the portal.
    code: Mapped[str] = mapped_column(String(32), unique=True)
    contact_email: Mapped[str | None] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(500))
    state: Mapped[str | None] = mapped_column(String(100))

    users: Mapped[list["User"]] = relationship(back_populates="institution")
    fdrs: Mapped[list["FDR"]] = relationship(back_populates="institution")
