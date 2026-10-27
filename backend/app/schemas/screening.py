"""Schemas for advisory screening (AICTE only)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    FDRStatus,
    FindingCategory,
    FindingSeverity,
    ReviewPriority,
    ScreeningDisposition,
    ScreeningRunStatus,
)
from app.schemas.common import InstitutionBrief
from app.schemas.verification import UserBrief


class ScreeningReviewCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    disposition: ScreeningDisposition
    notes: str = Field(min_length=10, max_length=2000)


class ScreeningReviewRead(BaseModel):
    id: int
    finding_id: int
    run_number: int
    disposition: ScreeningDisposition
    notes: str
    reviewer: UserBrief
    reviewed_at: datetime


class FindingRead(BaseModel):
    id: int
    code: str
    rule_version: str
    category: FindingCategory
    severity: FindingSeverity
    title: str
    description: str
    reason: str
    field: str | None
    observed: dict[str, Any] | None
    document_id: int | None
    related_fdr_id: int | None
    match_type: str | None
    fingerprint: str
    # Human reviews of this finding in this run (oldest first; the last is current).
    reviews: list[ScreeningReviewRead]
    # Reviews of the same finding in earlier runs. Shown for context; they are
    # not automatically applied to this run.
    earlier_reviews: list[ScreeningReviewRead]


class NoLongerRaised(BaseModel):
    """A finding from the previous run that this run did not produce.

    This is an automatic difference between runs, not a human decision.
    """

    code: str
    title: str
    severity: FindingSeverity
    fingerprint: str
    previous_run_number: int
    reviewed_by_human: bool


class RunSummary(BaseModel):
    id: int
    run_number: int
    status: ScreeningRunStatus
    engine_version: str
    started_at: datetime
    completed_at: datetime
    triggered_by: UserBrief
    review_priority: ReviewPriority | None
    high_count: int
    warning_count: int
    info_count: int
    fdr_version: int
    error_code: str | None


class RunDetail(RunSummary):
    findings: list[FindingRead]
    extraction: list[dict[str, Any]]
    no_longer_raised: list[NoLongerRaised]
    is_latest: bool
    is_stale: bool


class ScreeningOverview(BaseModel):
    fdr_id: int
    advisory_notice: str
    priority_explanation: str
    latest: RunDetail | None
    runs: list[RunSummary]


class ScreeningQueueItem(BaseModel):
    fdr_id: int
    fdr_number: str
    bank_name: str
    institution: InstitutionBrief
    fdr_status: FDRStatus
    run_id: int
    run_number: int
    run_status: ScreeningRunStatus
    completed_at: datetime
    review_priority: ReviewPriority | None
    high_count: int
    warning_count: int
    info_count: int
    unreviewed_high: int
    unreviewed_warning: int
    is_stale: bool
