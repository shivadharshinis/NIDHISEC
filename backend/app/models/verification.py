"""Bank verification workflow: assignments, officer outcomes and AICTE review decisions.

All three tables are history: rows are never deleted, outcomes and decisions
are never edited, and an assignment can only move once from ACTIVE to a final
state. Database triggers enforce this. A bank officer's outcome is their
recorded attestation; NidhiSec has no connection to bank systems, so an outcome
is not independent proof that an FDR is genuine.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DDL, JSON, CheckConstraint, ForeignKey, Index, Integer, String, event, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.db.types import UTCDateTime
from app.models.enums import AssignmentStatus, FDRStatus, VerificationOutcomeType, enum_column

if TYPE_CHECKING:
    from app.models.fdr import FDR
    from app.models.user import User

# How an outcome was obtained. Only manual officer attestation exists; there
# is no bank-system integration.
OUTCOME_METHOD_OFFICER_ATTESTATION = "OFFICER_ATTESTATION"


class VerificationAssignment(Base):
    __tablename__ = "verification_assignments"
    __table_args__ = (
        # At most one ACTIVE assignment per FDR, enforced by the database so
        # that concurrent requests cannot create two.
        Index(
            "uq_verification_assignments_active_fdr",
            "fdr_id",
            unique=True,
            sqlite_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_verification_assignments_officer_status", "bank_officer_id", "status"),
        CheckConstraint(
            "(status = 'ACTIVE' AND ended_at IS NULL AND ended_by_id IS NULL AND end_reason IS NULL)"
            " OR (status = 'COMPLETED' AND ended_at IS NOT NULL)"
            " OR (status IN ('SUPERSEDED', 'CANCELLED') AND ended_at IS NOT NULL"
            " AND ended_by_id IS NOT NULL AND end_reason IS NOT NULL)",
            name="end_fields_match_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fdr_id: Mapped[int] = mapped_column(ForeignKey("fdrs.id", ondelete="RESTRICT"), index=True)
    bank_officer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    assigned_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    assigned_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    # Instructions from AICTE to the officer. Not shown to institutions.
    assignment_note: Mapped[str | None] = mapped_column(String(1000))
    # Set when this assignment replaces an earlier one (reassignment chain).
    previous_assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("verification_assignments.id", ondelete="RESTRICT")
    )

    status: Mapped[AssignmentStatus] = mapped_column(enum_column(AssignmentStatus), default=AssignmentStatus.ACTIVE)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    ended_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    end_reason: Mapped[str | None] = mapped_column(String(1000))

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    __mapper_args__ = {"version_id_col": version}

    fdr: Mapped["FDR"] = relationship()
    bank_officer: Mapped["User"] = relationship(foreign_keys=[bank_officer_id])
    assigned_by: Mapped["User"] = relationship(foreign_keys=[assigned_by_id])
    ended_by: Mapped["User | None"] = relationship(foreign_keys=[ended_by_id])
    outcome: Mapped["VerificationOutcome | None"] = relationship(back_populates="assignment", uselist=False)


class VerificationOutcome(Base):
    """A bank officer's recorded result for one assignment. Append-only."""

    __tablename__ = "verification_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    # One outcome per assignment; a second submission violates this constraint.
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("verification_assignments.id", ondelete="RESTRICT"), unique=True
    )
    fdr_id: Mapped[int] = mapped_column(ForeignKey("fdrs.id", ondelete="RESTRICT"), index=True)
    officer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    outcome: Mapped[VerificationOutcomeType] = mapped_column(enum_column(VerificationOutcomeType))
    notes: Mapped[str] = mapped_column(String(2000))
    # Optional reference in the bank's own records (e.g. a ledger or letter number).
    bank_reference: Mapped[str | None] = mapped_column(String(100))
    # IDs of FDR documents the officer relied on, as they existed at submission.
    evidence_document_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    method: Mapped[str] = mapped_column(String(32), default=OUTCOME_METHOD_OFFICER_ATTESTATION)
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    assignment: Mapped[VerificationAssignment] = relationship(back_populates="outcome")
    officer: Mapped["User"] = relationship(foreign_keys=[officer_id])


class ReviewDecision(Base):
    """An AICTE review decision on an FDR. Append-only and separate from bank outcomes."""

    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    fdr_id: Mapped[int] = mapped_column(ForeignKey("fdrs.id", ondelete="RESTRICT"), index=True)
    decided_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    previous_status: Mapped[FDRStatus] = mapped_column(enum_column(FDRStatus))
    new_status: Mapped[FDRStatus] = mapped_column(enum_column(FDRStatus))
    # Shown to the institution.
    message_to_institution: Mapped[str | None] = mapped_column(String(1000))
    # AICTE-only notes. Never shown to institutions or bank officers.
    internal_notes: Mapped[str | None] = mapped_column(String(2000))
    # The bank outcome that was current when the decision was made, if any.
    reviewed_outcome_id: Mapped[int | None] = mapped_column(
        ForeignKey("verification_outcomes.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    decided_by: Mapped["User"] = relationship(foreign_keys=[decided_by_id])


# Kept in sync with the Alembic migration that creates the same triggers.
VERIFICATION_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS verification_assignments_identity_immutable
    BEFORE UPDATE OF fdr_id, bank_officer_id, assigned_by_id, assigned_at, assignment_note,
                     previous_assignment_id ON verification_assignments
    BEGIN SELECT RAISE(ABORT, 'verification assignment identity is immutable'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS verification_assignments_final
    BEFORE UPDATE ON verification_assignments WHEN OLD.status != 'ACTIVE'
    BEGIN SELECT RAISE(ABORT, 'a closed verification assignment cannot be changed'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS verification_assignments_no_delete BEFORE DELETE ON verification_assignments
    BEGIN SELECT RAISE(ABORT, 'verification assignments cannot be deleted'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS verification_outcomes_no_update BEFORE UPDATE ON verification_outcomes
    BEGIN SELECT RAISE(ABORT, 'verification outcomes are append-only'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS verification_outcomes_no_delete BEFORE DELETE ON verification_outcomes
    BEGIN SELECT RAISE(ABORT, 'verification outcomes are append-only'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS review_decisions_no_update BEFORE UPDATE ON review_decisions
    BEGIN SELECT RAISE(ABORT, 'review decisions are append-only'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS review_decisions_no_delete BEFORE DELETE ON review_decisions
    BEGIN SELECT RAISE(ABORT, 'review decisions are append-only'); END
    """,
]

_TRIGGER_TABLES: dict[str, Any] = {
    "verification_assignments": VerificationAssignment.__table__,
    "verification_outcomes": VerificationOutcome.__table__,
    "review_decisions": ReviewDecision.__table__,
}
for _statement in VERIFICATION_TRIGGERS:
    _table = next(name for name in _TRIGGER_TABLES if f" ON {name}" in _statement)
    event.listen(_TRIGGER_TABLES[_table], "after_create", DDL(_statement).execute_if(dialect="sqlite"))
