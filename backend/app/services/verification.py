"""Bank verification rules: who may see a case, eligibility, transitions and serialisation."""

from datetime import datetime, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    FDR,
    AssignmentStatus,
    FDRDocument,
    FDRStatus,
    LifecycleStatus,
    ReviewDecision,
    User,
    UserRole,
    VerificationAssignment,
    VerificationOutcome,
    VerificationOutcomeType,
)
from app.schemas.common import InstitutionBrief
from app.schemas.verification import (
    AssignmentQueueItem,
    AssignmentRead,
    BankCaseSummary,
    OutcomeRead,
    ReviewDecisionRead,
    UserBrief,
    VerificationState,
)
from app.services.audit import AuditAction, record_audit
from app.services.documents import to_document_read

# AICTE may hand a record to a bank officer while it is with AICTE.
ASSIGNABLE_STATUSES = {FDRStatus.SUBMITTED, FDRStatus.UNDER_REVIEW}

NOT_ASSIGNED_TO_YOU = "This verification case is not assigned to you."


def active_assignment(db: Session, fdr_id: int) -> VerificationAssignment | None:
    return db.scalars(
        select(VerificationAssignment).where(
            VerificationAssignment.fdr_id == fdr_id, VerificationAssignment.status == AssignmentStatus.ACTIVE
        )
    ).one_or_none()


def latest_outcome(db: Session, fdr_id: int) -> VerificationOutcome | None:
    return db.scalars(
        select(VerificationOutcome).where(VerificationOutcome.fdr_id == fdr_id).order_by(VerificationOutcome.id.desc())
    ).first()


def verification_state(db: Session, fdr: FDR) -> VerificationState:
    if active_assignment(db, fdr.id) is not None:
        return "IN_PROGRESS"
    outcome = latest_outcome(db, fdr.id)
    # An outcome that predates a return to the institution is no longer current.
    if outcome is not None and fdr.status in (FDRStatus.UNDER_REVIEW, FDRStatus.ACCEPTED):
        return "OUTCOME_RECORDED"
    return "NOT_ASSIGNED"


def can_accept(db: Session, fdr: FDR) -> bool:
    """AICTE may accept only after the current bank outcome is a confirmation."""
    if fdr.status != FDRStatus.UNDER_REVIEW or active_assignment(db, fdr.id) is not None:
        return False
    outcome = latest_outcome(db, fdr.id)
    return outcome is not None and outcome.outcome == VerificationOutcomeType.CONFIRMED_AGAINST_BANK_RECORDS


def awaiting_decision_conditions() -> list:
    """FDRs whose bank outcome is awaiting an AICTE decision.

    The single definition used by both the dashboard count and the review
    queue: under review, still an active or proposed instrument, a bank outcome
    recorded after the last AICTE review decision, and no verification case open.
    """
    last_decision = (
        select(func.max(ReviewDecision.decided_at)).where(ReviewDecision.fdr_id == FDR.id).correlate(FDR).scalar_subquery()
    )
    # Correlated to FDR only, so these work inside queries that also join outcomes or assignments.
    newer_outcome = (
        select(VerificationOutcome.id)
        .where(
            VerificationOutcome.fdr_id == FDR.id,
            VerificationOutcome.submitted_at > func.coalesce(last_decision, "1900-01-01"),
        )
        .correlate(FDR)
        .exists()
    )
    open_case = (
        select(VerificationAssignment.id)
        .where(VerificationAssignment.fdr_id == FDR.id, VerificationAssignment.status == AssignmentStatus.ACTIVE)
        .correlate(FDR)
        .exists()
    )
    return [
        FDR.status == FDRStatus.UNDER_REVIEW,
        FDR.lifecycle_status.in_([LifecycleStatus.ACTIVE, LifecycleStatus.PROPOSED]),
        newer_outcome,
        ~open_case,
    ]


def officer_active_assignment(db: Session, officer: User, fdr_id: int) -> VerificationAssignment | None:
    return db.scalars(
        select(VerificationAssignment).where(
            VerificationAssignment.fdr_id == fdr_id,
            VerificationAssignment.bank_officer_id == officer.id,
            VerificationAssignment.status == AssignmentStatus.ACTIVE,
        )
    ).one_or_none()


def deny_bank_officer(db: Session, request: Request | None, officer: User, *, fdr_id: int | None, attempted: str,
                      assignment_id: int | None = None, status_code: int = status.HTTP_403_FORBIDDEN) -> HTTPException:
    """Audit an out-of-scope access attempt by a bank officer and build the error to raise.

    The response never says whether the record exists or who it belongs to.
    """
    record_audit(
        db,
        action=AuditAction.VERIFICATION_ACCESS_DENIED,
        entity_type="fdr" if fdr_id is not None else "verification_assignment",
        entity_id=fdr_id if fdr_id is not None else assignment_id,
        actor=officer,
        summary=f"Bank officer access denied ({attempted})",
        changes={"attempted": attempted, "fdr_id": fdr_id, "assignment_id": assignment_id},
        request=request,
    )
    db.commit()
    return HTTPException(
        status_code=status_code,
        detail=NOT_ASSIGNED_TO_YOU if status_code == status.HTTP_403_FORBIDDEN else "Verification case not found",
    )


def end_active_assignment(db: Session, fdr: FDR, actor: User, new_status: AssignmentStatus, reason: str,
                          request: Request | None) -> VerificationAssignment | None:
    """Close the FDR's active assignment, if any (used when AICTE returns or rejects the record)."""
    assignment = active_assignment(db, fdr.id)
    if assignment is None:
        return None
    assignment.status = new_status
    assignment.ended_at = datetime.now(timezone.utc)
    assignment.ended_by_id = actor.id
    assignment.end_reason = reason
    record_audit(
        db,
        action=AuditAction.VERIFICATION_CANCELLED,
        entity_type="fdr",
        entity_id=fdr.id,
        institution_id=fdr.institution_id,
        actor=actor,
        summary=f"Verification assignment #{assignment.id} cancelled: {reason}"[:500],
        changes={"assignment_id": assignment.id, "bank_officer_id": assignment.bank_officer_id},
        request=request,
    )
    from app.services import notifications

    notifications.notify(
        db, [assignment.bank_officer], event_type="VERIFICATION_CANCELLED",
        dedup_key=f"assignment:{assignment.id}:cancelled",
        title="A verification case was closed by AICTE",
        body=f"Verification case #{assignment.id} (FDR {fdr.fdr_number}) was closed by AICTE before an outcome was "
             "recorded. You no longer have access to it.",
        link=f"/verification/cases/{assignment.id}", fdr_id=None,
    )
    return assignment


# ---------- serialisation ----------


def user_brief(user: User) -> UserBrief:
    return UserBrief.model_validate(user)


def to_outcome_read(db: Session, outcome: VerificationOutcome) -> OutcomeRead:
    documents = []
    if outcome.evidence_document_ids:
        documents = [
            to_document_read(document)
            for document in db.scalars(
                select(FDRDocument).where(FDRDocument.id.in_(outcome.evidence_document_ids)).order_by(FDRDocument.id)
            ).all()
        ]
    return OutcomeRead(
        id=outcome.id,
        assignment_id=outcome.assignment_id,
        outcome=outcome.outcome,
        notes=outcome.notes,
        bank_reference=outcome.bank_reference,
        evidence_documents=documents,
        method=outcome.method,
        submitted_by=user_brief(outcome.officer),
        submitted_at=outcome.submitted_at,
    )


def to_assignment_read(db: Session, assignment: VerificationAssignment) -> AssignmentRead:
    return AssignmentRead(
        id=assignment.id,
        fdr_id=assignment.fdr_id,
        status=assignment.status,
        bank_officer=user_brief(assignment.bank_officer),
        assigned_by=user_brief(assignment.assigned_by),
        assigned_at=assignment.assigned_at,
        assignment_note=assignment.assignment_note,
        previous_assignment_id=assignment.previous_assignment_id,
        ended_at=assignment.ended_at,
        ended_by=user_brief(assignment.ended_by) if assignment.ended_by else None,
        end_reason=assignment.end_reason,
        version=assignment.version,
        outcome=to_outcome_read(db, assignment.outcome) if assignment.outcome else None,
    )


def to_decision_read(decision: ReviewDecision) -> ReviewDecisionRead:
    return ReviewDecisionRead(
        id=decision.id,
        previous_status=decision.previous_status,
        new_status=decision.new_status,
        message_to_institution=decision.message_to_institution,
        internal_notes=decision.internal_notes,
        reviewed_outcome_id=decision.reviewed_outcome_id,
        decided_by=user_brief(decision.decided_by),
        decided_at=decision.decided_at,
    )


def to_queue_item(assignment: VerificationAssignment) -> AssignmentQueueItem:
    fdr = assignment.fdr
    return AssignmentQueueItem(
        id=assignment.id,
        status=assignment.status,
        fdr_id=fdr.id,
        fdr_number=fdr.fdr_number,
        bank_name=fdr.bank_name,
        institution=InstitutionBrief.model_validate(fdr.institution),
        bank_officer=user_brief(assignment.bank_officer),
        assigned_at=assignment.assigned_at,
        ended_at=assignment.ended_at,
        outcome=assignment.outcome.outcome if assignment.outcome else None,
    )


def to_case_summary(assignment: VerificationAssignment) -> BankCaseSummary:
    fdr = assignment.fdr
    return BankCaseSummary(
        id=assignment.id,
        status=assignment.status,
        assigned_at=assignment.assigned_at,
        ended_at=assignment.ended_at,
        fdr_number=fdr.fdr_number,
        bank_name=fdr.bank_name,
        institution=InstitutionBrief.model_validate(fdr.institution),
        outcome=assignment.outcome.outcome if assignment.outcome else None,
        amount=fdr.amount if assignment.status == AssignmentStatus.ACTIVE else None,
        maturity_date=fdr.maturity_date if assignment.status == AssignmentStatus.ACTIVE else None,
    )


def assignment_query():
    return select(VerificationAssignment).options(
        joinedload(VerificationAssignment.fdr).joinedload(FDR.institution),
        joinedload(VerificationAssignment.bank_officer),
        joinedload(VerificationAssignment.outcome),
    )


def require_bank_officer(user: User) -> None:
    if user.role != UserRole.BANK_OFFICER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only bank officers have verification cases")
