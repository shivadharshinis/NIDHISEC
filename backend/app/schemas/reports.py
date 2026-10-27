"""Schemas for the AICTE reports snapshot. Counts and amounts only; no record content."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import LifecycleRequestStatus, LifecycleRequestType
from app.schemas.common import InstitutionBrief


class RequestCount(BaseModel):
    request_type: LifecycleRequestType
    status: LifecycleRequestStatus
    count: int


class MaturityBucket(BaseModel):
    bucket: str  # OVERDUE | DUE_0_30 | DUE_31_90 | DUE_91_365 | LATER
    label: str
    count: int
    total_amount: Decimal


class InstitutionSummary(BaseModel):
    institution: InstitutionBrief
    total_fdrs: int
    by_status: dict[str, int]
    active_instruments: int
    active_amount: Decimal
    maturing_within_30_days: int
    overdue_active: int
    open_lifecycle_requests: int


class ReportSummary(BaseModel):
    """A snapshot of the current state of records, not a history of activity."""

    as_of: date  # Indian Standard Time calendar date used for maturity buckets
    generated_at: datetime
    scope_note: str
    fdr_total: int
    fdr_by_status: dict[str, int]
    fdr_by_lifecycle: dict[str, int]
    lifecycle_requests: list[RequestCount]
    monitored_total: int
    maturity: list[MaturityBucket]
    institutions: list[InstitutionSummary]
