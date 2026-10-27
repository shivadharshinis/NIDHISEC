from enum import StrEnum

import sqlalchemy as sa


class UserRole(StrEnum):
    INSTITUTION = "INSTITUTION"
    BANK_OFFICER = "BANK_OFFICER"
    AICTE_OFFICIAL = "AICTE_OFFICIAL"


class FDRStatus(StrEnum):
    """AICTE review status of an FDR record.

    Bank verification progress is tracked separately (verification
    assignments and outcomes). No status is proof that an FDR is genuine.
    """

    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    REJECTED = "REJECTED"
    # AICTE's own decision, allowed only after a bank officer has recorded a
    # "confirmed" outcome. Still not independent proof of authenticity.
    ACCEPTED = "ACCEPTED"


class DocumentType(StrEnum):
    FDR_COPY = "FDR_COPY"
    BANK_LETTER = "BANK_LETTER"
    OTHER = "OTHER"


def enum_column(enum_cls: type[StrEnum]) -> sa.Enum:
    """Store enums as plain strings so new values don't require a table rebuild."""
    return sa.Enum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class AssignmentStatus(StrEnum):
    ACTIVE = "ACTIVE"          # with the bank officer
    COMPLETED = "COMPLETED"    # the officer recorded an outcome
    SUPERSEDED = "SUPERSEDED"  # reassigned to another officer
    CANCELLED = "CANCELLED"    # record returned to the institution or rejected


class VerificationOutcomeType(StrEnum):
    CONFIRMED_AGAINST_BANK_RECORDS = "CONFIRMED_AGAINST_BANK_RECORDS"
    DETAILS_MISMATCH = "DETAILS_MISMATCH"
    ADDITIONAL_INFO_REQUIRED = "ADDITIONAL_INFO_REQUIRED"
    UNABLE_TO_VERIFY = "UNABLE_TO_VERIFY"


class ScreeningRunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"  # nothing about the FDR was changed; the run can be retried


class FindingSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"


class FindingCategory(StrEnum):
    RECORD_VALIDATION = "RECORD_VALIDATION"        # the submitted record itself
    DOCUMENT_EXTRACTION = "DOCUMENT_EXTRACTION"    # what could or could not be read from documents
    DOCUMENT_CONSISTENCY = "DOCUMENT_CONSISTENCY"  # record vs values read from documents
    DUPLICATE = "DUPLICATE"                        # same or similar instrument elsewhere
    LIFECYCLE = "LIFECYCLE"                        # maturity timing; not an integrity concern


class ReviewPriority(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ScreeningDisposition(StrEnum):
    CONCERN_CONFIRMED = "CONCERN_CONFIRMED"
    NEEDS_FOLLOW_UP = "NEEDS_FOLLOW_UP"
    DISMISSED_NOT_AN_ISSUE = "DISMISSED_NOT_AN_ISSUE"


class LifecycleStatus(StrEnum):
    """Where the instrument is in its life, separate from AICTE review status."""

    ACTIVE = "ACTIVE"        # the current security deposit instrument
    PROPOSED = "PROPOSED"    # successor submitted with a renewal/replacement request, not yet in effect
    RENEWED = "RENEWED"      # superseded by a renewal (successor recorded)
    REPLACED = "REPLACED"    # superseded by a replacement (successor recorded)
    RELEASED = "RELEASED"    # release/refund recorded as completed by AICTE
    CANCELLED = "CANCELLED"  # proposed successor whose request was rejected or withdrawn


class LifecycleRequestType(StrEnum):
    RENEWAL = "RENEWAL"
    REPLACEMENT = "REPLACEMENT"
    RELEASE = "RELEASE"


class LifecycleRequestStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    APPROVED = "APPROVED"      # decision only; nothing has happened yet
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"    # explicitly recorded administrative completion
