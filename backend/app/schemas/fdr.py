"""Request/response schemas for FDR records."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.models.enums import FDRStatus, LifecycleStatus, UserRole
from app.schemas.common import InstitutionBrief
from app.schemas.document import DocumentRead

# Indian Standard Time has no DST, so a fixed offset is exact.
IST = timezone(timedelta(hours=5, minutes=30))

MAX_AMOUNT = Decimal("10000000000.00")  # ₹1,000 crore sanity ceiling
MAX_TENURE_YEARS = 10

BANK_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9 .,&()'\-]*$"
BRANCH_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 .,&()'/\-]*$"
FDR_NUMBER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 /.\-]*$"
IFSC_PATTERN = r"^[A-Z]{4}0[A-Z0-9]{6}$"


def today_ist() -> date:
    return datetime.now(IST).date()


def _add_years(start: date, years: int) -> date:
    try:
        return start.replace(year=start.year + years)
    except ValueError:  # 29 February
        return start.replace(year=start.year + years, day=28)


def fdr_date_errors(issue_date: date, maturity_date: date) -> list[tuple[str, str]]:
    """Business rules for FDR dates, shared by create and update. Returns (field, message) pairs."""
    errors: list[tuple[str, str]] = []
    if issue_date > today_ist():
        errors.append(("issue_date", "Issue date cannot be in the future"))
    if maturity_date <= issue_date:
        errors.append(("maturity_date", "Maturity date must be after the issue date"))
    elif maturity_date > _add_years(issue_date, MAX_TENURE_YEARS):
        errors.append(("maturity_date", f"FDR tenure cannot exceed {MAX_TENURE_YEARS} years"))
    return errors


def _blank_to_none(value: object) -> object:
    return None if isinstance(value, str) and not value.strip() else value


Amount = Annotated[Decimal, Field(gt=0, le=MAX_AMOUNT, max_digits=13, decimal_places=2)]
BankName = Annotated[str, Field(min_length=2, max_length=150, pattern=BANK_NAME_PATTERN)]
FdrNumber = Annotated[str, Field(min_length=3, max_length=50, pattern=FDR_NUMBER_PATTERN)]
# Optional text: blank input is stored as NULL rather than an empty string.
Branch = Annotated[
    Annotated[str, Field(max_length=150, pattern=BRANCH_PATTERN)] | None, BeforeValidator(_blank_to_none)
]
Remarks = Annotated[Annotated[str, Field(max_length=1000)] | None, BeforeValidator(_blank_to_none)]
IfscCode = Annotated[Annotated[str, Field(pattern=IFSC_PATTERN)] | None, BeforeValidator(_blank_to_none)]


class _FDRInputBase(BaseModel):
    # extra="forbid" blocks mass assignment of fields such as institution_id or status.
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator("ifsc_code", mode="before", check_fields=False)
    @classmethod
    def uppercase_ifsc(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class FDRCreate(_FDRInputBase):
    bank_name: BankName
    branch_name: Branch = None
    ifsc_code: IfscCode = None
    fdr_number: FdrNumber
    amount: Amount
    issue_date: date
    maturity_date: date
    remarks: Remarks = None

    # Field-level validators so each error is reported against its own field.
    @field_validator("issue_date")
    @classmethod
    def issue_not_in_future(cls, value: date) -> date:
        if value > today_ist():
            raise ValueError("Issue date cannot be in the future")
        return value

    @field_validator("maturity_date")
    @classmethod
    def maturity_consistent_with_issue(cls, value: date, info: ValidationInfo) -> date:
        issue_date = info.data.get("issue_date")
        if issue_date is not None:
            for field, message in fdr_date_errors(issue_date, value):
                if field == "maturity_date":
                    raise ValueError(message)
        return value


class FDRUpdate(_FDRInputBase):
    """Fields an institution may correct while its record is open for edits.

    `version` must match the stored record; a mismatch means someone else
    changed it first and the request is rejected rather than overwriting.
    """

    version: int = Field(ge=1)
    bank_name: BankName | None = None
    branch_name: Branch = None
    ifsc_code: IfscCode = None
    fdr_number: FdrNumber | None = None
    amount: Amount | None = None
    issue_date: date | None = None
    maturity_date: date | None = None
    remarks: Remarks = None

    @model_validator(mode="after")
    def check_required_not_cleared(self) -> Self:
        for name in ("bank_name", "fdr_number", "amount", "issue_date", "maturity_date"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be cleared")
        if self.model_fields_set <= {"version"}:
            raise ValueError("No fields to update")
        return self


ReviewStatus = Literal[
    FDRStatus.UNDER_REVIEW, FDRStatus.CLARIFICATION_REQUESTED, FDRStatus.REJECTED, FDRStatus.ACCEPTED
]


class FDRReview(BaseModel):
    """AICTE review decision. Not a confirmation of authenticity.

    `review_remarks` is the message shown to the institution; `internal_notes`
    are visible to AICTE officials only.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    version: int = Field(ge=1)
    status: ReviewStatus
    review_remarks: Remarks = None
    internal_notes: Annotated[Annotated[str, Field(max_length=2000)] | None, BeforeValidator(_blank_to_none)] = None

    @model_validator(mode="after")
    def remarks_required_for_outcomes(self) -> Self:
        needs_message = {FDRStatus.CLARIFICATION_REQUESTED, FDRStatus.REJECTED}
        if self.status in needs_message and not self.review_remarks:
            raise ValueError("Remarks are required when requesting clarification or rejecting")
        return self


class FDRListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    institution: InstitutionBrief
    bank_name: str
    branch_name: str | None
    ifsc_code: str | None
    fdr_number: str
    amount: Decimal
    issue_date: date
    maturity_date: date
    status: FDRStatus
    lifecycle_status: LifecycleStatus
    possible_duplicate: bool = False
    version: int
    created_at: datetime
    updated_at: datetime


class DuplicateMatch(BaseModel):
    id: int
    institution: InstitutionBrief
    bank_name: str
    fdr_number: str
    status: FDRStatus
    created_at: datetime
    same_institution: bool


class DuplicateReview(BaseModel):
    """Possible duplicates share a normalised FDR reference and bank.

    A match is a prompt for human review, not a finding of fraud. Institution
    users only see details of matches within their own institution.
    """

    flagged: bool
    match_count: int
    matches: list[DuplicateMatch]
    hidden_match_count: int


class FDRDetail(FDRListItem):
    remarks: str | None
    review_remarks: str | None
    created_by_name: str
    documents: list[DocumentRead]
    duplicate_review: DuplicateReview
    can_edit: bool
    can_review: bool
    can_upload_documents: bool
    # Coarse bank-verification progress; outcome details are AICTE-only.
    verification_state: Literal["NOT_ASSIGNED", "IN_PROGRESS", "OUTCOME_RECORDED"]


class FDRSummary(BaseModel):
    total: int
    by_status: dict[FDRStatus, int]
    possible_duplicates: int
    maturing_within_90_days: int
    matured: int


class FDRHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    action: str
    summary: str
    actor_name: str | None
    actor_role: UserRole | None
    changes: dict | None
