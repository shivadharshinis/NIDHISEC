from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DDL, BigInteger, CheckConstraint, Date, ForeignKey, Index, Integer, String, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow
from app.db.types import UTCDateTime
from app.models.enums import DocumentType, FDRStatus, LifecycleStatus, enum_column

if TYPE_CHECKING:
    from app.models.institution import Institution
    from app.models.user import User


class FDR(TimestampMixin, Base):
    """A Fixed Deposit Receipt lodged by an institution as a security deposit.

    Saving a record does not mean the FDR is authentic; that requires bank
    verification, which is a later workflow.
    """

    __tablename__ = "fdrs"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="amount_positive"),
        CheckConstraint("maturity_date > issue_date", name="maturity_after_issue"),
        # Possible-duplicate lookups match on the normalised reference first.
        Index("ix_fdrs_fdr_number_normalized", "fdr_number_normalized"),
        Index("ix_fdrs_institution_id_status", "institution_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id", ondelete="RESTRICT"))

    bank_name: Mapped[str] = mapped_column(String(150))
    bank_name_normalized: Mapped[str] = mapped_column(String(150))
    branch_name: Mapped[str | None] = mapped_column(String(150))
    ifsc_code: Mapped[str | None] = mapped_column(String(11))
    fdr_number: Mapped[str] = mapped_column(String(50))
    fdr_number_normalized: Mapped[str] = mapped_column(String(50))

    # Money is stored as integer paise to avoid floating-point rounding.
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    issue_date: Mapped[date] = mapped_column(Date)
    maturity_date: Mapped[date] = mapped_column(Date, index=True)
    remarks: Mapped[str | None] = mapped_column(String(1000))

    status: Mapped[FDRStatus] = mapped_column(enum_column(FDRStatus), default=FDRStatus.SUBMITTED, index=True)
    # Instrument lifecycle, separate from AICTE review status. Changed only by
    # completed lifecycle requests, never by maturity alone.
    lifecycle_status: Mapped[LifecycleStatus] = mapped_column(
        enum_column(LifecycleStatus), default=LifecycleStatus.ACTIVE, server_default="ACTIVE", index=True
    )
    review_remarks: Mapped[str | None] = mapped_column(String(1000))

    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    # Optimistic locking: concurrent edits raise instead of silently overwriting.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    __mapper_args__ = {"version_id_col": version}

    institution: Mapped["Institution"] = relationship(back_populates="fdrs")
    created_by: Mapped["User"] = relationship(foreign_keys=[created_by_id])
    documents: Mapped[list["FDRDocument"]] = relationship(back_populates="fdr", order_by="FDRDocument.id")

    @property
    def amount(self) -> Decimal:
        return Decimal(self.amount_paise).scaleb(-2)  # always two decimal places


class FDRDocument(Base):
    """A supporting document attached to an FDR.

    Documents are evidence: the file and its identifying fields are immutable
    and rows cannot be deleted (enforced by database triggers). A document that
    was attached by mistake is *withdrawn* with a reason; it stays on record.
    The SHA-256 hash proves the stored file is unchanged since upload. It does
    not prove the document itself is genuine.
    """

    __tablename__ = "fdr_documents"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        CheckConstraint(
            "(withdrawn_at IS NULL AND withdrawn_by_id IS NULL AND withdrawal_reason IS NULL)"
            " OR (withdrawn_at IS NOT NULL AND withdrawn_by_id IS NOT NULL AND withdrawal_reason IS NOT NULL)",
            name="withdrawal_complete",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: removing an FDR must never silently remove its evidence.
    fdr_id: Mapped[int] = mapped_column(ForeignKey("fdrs.id", ondelete="RESTRICT"), index=True)
    document_type: Mapped[DocumentType] = mapped_column(enum_column(DocumentType))
    # Sanitised display name only; never used to build a filesystem path.
    original_filename: Mapped[str] = mapped_column(String(255))
    # Detected from the file content, not taken from the client.
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    # Random opaque key into private storage; never a path or a public URL.
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    withdrawn_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    withdrawn_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    withdrawal_reason: Mapped[str | None] = mapped_column(String(500))

    fdr: Mapped[FDR] = relationship(back_populates="documents")
    uploaded_by: Mapped["User"] = relationship(foreign_keys=[uploaded_by_id])
    withdrawn_by: Mapped["User | None"] = relationship(foreign_keys=[withdrawn_by_id])


# Kept in sync with the Alembic migration that creates the same triggers.
FDR_DOCUMENT_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS fdr_documents_evidence_immutable
    BEFORE UPDATE OF fdr_id, document_type, original_filename, content_type, size_bytes, sha256,
                     storage_key, uploaded_by_id, uploaded_at ON fdr_documents
    BEGIN SELECT RAISE(ABORT, 'fdr_documents evidence fields are immutable'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fdr_documents_withdrawal_final
    BEFORE UPDATE OF withdrawn_at, withdrawn_by_id, withdrawal_reason ON fdr_documents
    WHEN OLD.withdrawn_at IS NOT NULL
    BEGIN SELECT RAISE(ABORT, 'fdr_documents withdrawal cannot be changed'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fdr_documents_no_delete BEFORE DELETE ON fdr_documents
    BEGIN SELECT RAISE(ABORT, 'fdr_documents rows cannot be deleted'); END
    """,
]

for _statement in FDR_DOCUMENT_TRIGGERS:
    event.listen(FDRDocument.__table__, "after_create", DDL(_statement).execute_if(dialect="sqlite"))
