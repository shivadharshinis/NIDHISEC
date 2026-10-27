"""Advisory FDR screening: runs, findings and human reviews.

Screening never changes an FDR, its documents or its workflow state. Every
run is kept; findings and reviews are append-only (enforced by database
triggers). A review records a person's judgement; a finding that simply does
not appear in a later run is *not* a review.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DDL, JSON, ForeignKey, Integer, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.db.types import UTCDateTime
from app.models.enums import (
    FindingCategory,
    FindingSeverity,
    ReviewPriority,
    ScreeningDisposition,
    ScreeningRunStatus,
    enum_column,
)

if TYPE_CHECKING:
    from app.models.user import User


class ScreeningRun(Base):
    __tablename__ = "screening_runs"
    __table_args__ = (UniqueConstraint("fdr_id", "run_number", name="uq_screening_runs_fdr_run_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fdr_id: Mapped[int] = mapped_column(ForeignKey("fdrs.id", ondelete="RESTRICT"), index=True)
    # 1, 2, 3... per FDR; unique, so concurrent runs cannot both claim a number.
    run_number: Mapped[int] = mapped_column(Integer)
    engine_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[ScreeningRunStatus] = mapped_column(enum_column(ScreeningRunStatus))
    triggered_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    # What was screened, so later changes make the run visibly stale.
    fdr_version: Mapped[int] = mapped_column(Integer)
    documents_fingerprint: Mapped[str] = mapped_column(String(64))
    review_priority: Mapped[ReviewPriority | None] = mapped_column(enum_column(ReviewPriority))
    high_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    info_count: Mapped[int] = mapped_column(Integer, default=0)
    # Per-document extraction summary: status, method, pages and the extracted
    # field values with short source snippets. Full document text is never stored.
    extraction: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Generic failure code for FAILED runs (no stack traces or document content).
    error_code: Mapped[str | None] = mapped_column(String(64))

    triggered_by: Mapped["User"] = relationship()
    findings: Mapped[list["ScreeningFinding"]] = relationship(back_populates="run", order_by="ScreeningFinding.id")


class ScreeningFinding(Base):
    __tablename__ = "screening_findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("screening_runs.id", ondelete="RESTRICT"), index=True)
    code: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(16))
    category: Mapped[FindingCategory] = mapped_column(enum_column(FindingCategory))
    severity: Mapped[FindingSeverity] = mapped_column(enum_column(FindingSeverity))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(1000))
    reason: Mapped[str] = mapped_column(String(1000))
    field: Mapped[str | None] = mapped_column(String(64))
    observed: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("fdr_documents.id", ondelete="RESTRICT"))
    related_fdr_id: Mapped[int | None] = mapped_column(ForeignKey("fdrs.id", ondelete="RESTRICT"))
    match_type: Mapped[str | None] = mapped_column(String(32))
    # Identifies "the same finding" across runs, to show earlier human reviews.
    fingerprint: Mapped[str] = mapped_column(String(200), index=True)

    run: Mapped[ScreeningRun] = relationship(back_populates="findings")
    reviews: Mapped[list["ScreeningReview"]] = relationship(back_populates="finding", order_by="ScreeningReview.id")


class ScreeningReview(Base):
    """An authorised person's judgement on a finding. Append-only; the latest one is current."""

    __tablename__ = "screening_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("screening_findings.id", ondelete="RESTRICT"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    disposition: Mapped[ScreeningDisposition] = mapped_column(enum_column(ScreeningDisposition))
    notes: Mapped[str] = mapped_column(String(2000))
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    finding: Mapped[ScreeningFinding] = relationship(back_populates="reviews")
    reviewer: Mapped["User"] = relationship()


# Kept in sync with the Alembic migration that creates the same triggers.
SCREENING_TABLES = ("screening_runs", "screening_findings", "screening_reviews")
SCREENING_TRIGGERS = [
    statement
    for table in SCREENING_TABLES
    for statement in (
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END",
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END",
    )
]

for _model in (ScreeningRun, ScreeningFinding, ScreeningReview):
    for _statement in SCREENING_TRIGGERS:
        if f" ON {_model.__tablename__} " in _statement:
            event.listen(_model.__table__, "after_create", DDL(_statement).execute_if(dialect="sqlite"))
