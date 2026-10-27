"""Schemas for bank verification assignments, outcomes and AICTE review decisions."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AssignmentStatus, FDRStatus, LifecycleStatus, VerificationOutcomeType
from app.schemas.common import InstitutionBrief
from app.schemas.document import DocumentRead

_INPUT = ConfigDict(str_strip_whitespace=True, extra="forbid")


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str


# ---------- requests ----------


class AssignmentCreate(BaseModel):
    model_config = _INPUT

    bank_officer_id: int
    # The FDR version the official was looking at; a mismatch means the record changed.
    fdr_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=1000)


class AssignmentReassign(BaseModel):
    model_config = _INPUT

    bank_officer_id: int
    version: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=1000)


class OutcomeSubmit(BaseModel):
    model_config = _INPUT

    version: int = Field(ge=1)
    outcome: VerificationOutcomeType
    notes: str = Field(min_length=20, max_length=2000)
    bank_reference: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9 /.\-]*$")
    evidence_document_ids: list[int] = Field(default_factory=list, max_length=50)


# ---------- responses ----------


class OutcomeRead(BaseModel):
    """A bank officer's recorded attestation. Not independent proof of authenticity."""

    id: int
    assignment_id: int
    outcome: VerificationOutcomeType
    notes: str
    bank_reference: str | None
    evidence_documents: list[DocumentRead]
    method: str
    submitted_by: UserBrief
    submitted_at: datetime


class AssignmentRead(BaseModel):
    id: int
    fdr_id: int
    status: AssignmentStatus
    bank_officer: UserBrief
    assigned_by: UserBrief
    assigned_at: datetime
    assignment_note: str | None
    previous_assignment_id: int | None
    ended_at: datetime | None
    ended_by: UserBrief | None
    end_reason: str | None
    version: int
    outcome: OutcomeRead | None


class ReviewDecisionRead(BaseModel):
    id: int
    previous_status: FDRStatus
    new_status: FDRStatus
    message_to_institution: str | None
    internal_notes: str | None
    reviewed_outcome_id: int | None
    decided_by: UserBrief
    decided_at: datetime


VerificationState = Literal["NOT_ASSIGNED", "IN_PROGRESS", "OUTCOME_RECORDED"]


class VerificationHistory(BaseModel):
    """Full verification and review history of one FDR (AICTE only)."""

    fdr_id: int
    fdr_status: FDRStatus
    fdr_version: int
    state: VerificationState
    can_assign: bool
    can_accept: bool
    active_assignment: AssignmentRead | None
    assignments: list[AssignmentRead]
    decisions: list[ReviewDecisionRead]


class AssignmentQueueItem(BaseModel):
    id: int
    status: AssignmentStatus
    fdr_id: int
    fdr_number: str
    bank_name: str
    institution: InstitutionBrief
    bank_officer: UserBrief
    assigned_at: datetime
    ended_at: datetime | None
    outcome: VerificationOutcomeType | None


class CaseFDRView(BaseModel):
    """The FDR details a bank officer needs to check against bank records, and nothing more."""

    id: int
    institution: InstitutionBrief
    bank_name: str
    branch_name: str | None
    ifsc_code: str | None
    fdr_number: str
    amount: Decimal
    issue_date: date
    maturity_date: date


class BankCaseSummary(BaseModel):
    id: int
    status: AssignmentStatus
    assigned_at: datetime
    ended_at: datetime | None
    fdr_number: str
    bank_name: str
    institution: InstitutionBrief
    outcome: VerificationOutcomeType | None


class BankCase(BaseModel):
    """A bank officer's view of one of their own assignments.

    FDR details and documents are included only while the assignment is
    active. Reassignment reasons and AICTE notes are not included.
    """

    id: int
    status: AssignmentStatus
    version: int
    assigned_at: datetime
    assignment_note: str | None
    ended_at: datetime | None
    fdr_number: str
    bank_name: str
    institution: InstitutionBrief
    fdr: CaseFDRView | None
    documents: list[DocumentRead]
    outcome: OutcomeRead | None
    can_submit_outcome: bool


class AwaitingDecisionItem(BaseModel):
    """An FDR whose bank outcome awaits an AICTE decision (AICTE only)."""

    fdr_id: int
    fdr_number: str
    bank_name: str
    institution: InstitutionBrief
    fdr_status: FDRStatus
    lifecycle_status: LifecycleStatus
    # The most recent bank outcome: what the decision is about.
    outcome_id: int
    outcome: VerificationOutcomeType
    outcome_submitted_at: datetime
    officer: UserBrief
    assignment_id: int
