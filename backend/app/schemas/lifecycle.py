"""Schemas for lifecycle requests, maturity tracking, notifications and dashboards."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import FDRStatus, LifecycleRequestStatus, LifecycleRequestType, LifecycleStatus
from app.schemas.common import InstitutionBrief
from app.schemas.fdr import FDRCreate

_INPUT = ConfigDict(str_strip_whitespace=True, extra="forbid")


# ---------- requests ----------


class LifecycleRequestCreate(BaseModel):
    model_config = _INPUT

    request_type: LifecycleRequestType
    # The FDR version the institution was looking at; a mismatch means it changed meanwhile.
    fdr_version: int = Field(ge=1)
    reason: str = Field(min_length=20, max_length=2000)
    supporting_note: str | None = Field(default=None, max_length=2000)
    # New instrument details: required for renewal/replacement, not allowed for release.
    successor: FDRCreate | None = None

    @model_validator(mode="after")
    def successor_matches_type(self) -> Self:
        if self.request_type == LifecycleRequestType.RELEASE and self.successor is not None:
            raise ValueError("A release request does not take new instrument details")
        if self.request_type != LifecycleRequestType.RELEASE and self.successor is None:
            raise ValueError("Renewal and replacement requests need the new instrument's details")
        return self


LifecycleAction = Literal["START_REVIEW", "REQUEST_CLARIFICATION", "APPROVE", "REJECT", "COMPLETE", "RESPOND", "WITHDRAW"]


class LifecycleTransition(BaseModel):
    model_config = _INPUT

    action: LifecycleAction
    version: int = Field(ge=1)
    # Shown to the institution (or, for RESPOND/WITHDRAW, written by it).
    message: str | None = Field(default=None, min_length=10, max_length=2000)
    # AICTE-only notes.
    internal_note: str | None = Field(default=None, max_length=2000)
    # COMPLETE only: an administrative reference such as an order number. Not a payment record.
    completion_reference: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9 /.\-]*$")


# ---------- responses ----------


class FDRBrief(BaseModel):
    id: int
    fdr_number: str
    bank_name: str
    amount: Decimal
    issue_date: date
    maturity_date: date
    status: FDRStatus
    lifecycle_status: LifecycleStatus


class LifecycleEventRead(BaseModel):
    id: int
    action: str
    from_status: LifecycleRequestStatus | None
    to_status: LifecycleRequestStatus
    actor_name: str
    actor_role: str
    message: str | None
    internal_note: str | None  # always None for institution users
    created_at: datetime


class LifecycleRequestRead(BaseModel):
    id: int
    request_type: LifecycleRequestType
    status: LifecycleRequestStatus
    institution: InstitutionBrief
    fdr: FDRBrief
    successor: FDRBrief | None
    reason: str
    supporting_note: str | None
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None
    completed_at: datetime | None
    completion_reference: str | None
    version: int


class LifecycleRequestDetail(LifecycleRequestRead):
    events: list[LifecycleEventRead]
    allowed_actions: list[str]
    completion_blockers: list[str]


class EligibilityRead(BaseModel):
    allowed: bool
    reasons: list[str]


class FDRLifecycle(BaseModel):
    fdr_id: int
    fdr_version: int
    lifecycle_status: LifecycleStatus
    maturity_date: date
    days_to_maturity: int
    eligibility: dict[LifecycleRequestType, EligibilityRead]
    # Requests about this FDR, and the request (if any) that proposed it as a successor.
    requests: list[LifecycleRequestRead]
    proposed_by_request: LifecycleRequestRead | None
    rules: dict[str, int | bool]


class MaturityItem(BaseModel):
    fdr_id: int
    fdr_number: str
    bank_name: str
    institution: InstitutionBrief
    status: FDRStatus
    lifecycle_status: LifecycleStatus
    maturity_date: date
    days_remaining: int  # negative = days overdue
    state: Literal["MATURED", "DUE", "NOT_DUE"]
    alert_window: int | None
    open_request_type: LifecycleRequestType | None


class LifecycleCheckResult(BaseModel):
    checked: int
    due: int
    matured: int
    skipped: int
    notifications_created: int
    date: date


# ---------- notifications ----------


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    title: str
    body: str
    link: str | None
    fdr_id: int | None
    created_at: datetime
    read_at: datetime | None


class UnreadCount(BaseModel):
    unread: int


class MarkAllResult(BaseModel):
    marked: int


# ---------- dashboard ----------


class DashboardSummary(BaseModel):
    """Role-scoped counts computed from the database. Fields a role cannot see are None."""

    role: str
    as_of: date
    fdr_by_status: dict[str, int] | None = None
    fdr_by_lifecycle: dict[str, int] | None = None
    maturing_within_30_days: int | None = None
    overdue_active: int | None = None
    clarifications_requiring_action: int | None = None
    lifecycle_requests_open: dict[str, int] | None = None
    lifecycle_requests_awaiting_decision: dict[str, int] | None = None
    lifecycle_requests_awaiting_completion: int | None = None
    verification_active: int | None = None
    verification_outcomes_awaiting_decision: int | None = None
    screening_unreviewed_high: int | None = None
    screening_unreviewed_warning: int | None = None
    cases_awaiting_action: int | None = None
    cases_completed: int | None = None
    cases_closed_other: int | None = None
    unread_notifications: int
