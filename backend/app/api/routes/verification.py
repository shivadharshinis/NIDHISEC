"""Bank verification workflow.

AICTE officials assign FDRs to bank officers, reassign them with a reason and
read the full history. Bank officers see only their own cases and may record
one outcome per assignment. An outcome is the officer's recorded attestation:
NidhiSec has no connection to bank systems and does not verify FDRs itself.
"""

from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, require_roles
from app.models import (
    FDR,
    AssignmentStatus,
    FDRDocument,
    FDRStatus,
    ReviewDecision,
    User,
    UserRole,
    VerificationAssignment,
    VerificationOutcome,
)
from app.schemas.common import InstitutionBrief, Page
from app.schemas.verification import (
    AssignmentCreate,
    AssignmentQueueItem,
    AssignmentRead,
    AssignmentReassign,
    BankCase,
    BankCaseSummary,
    CaseFDRView,
    OutcomeSubmit,
    UserBrief,
    VerificationHistory,
)
from app.services import fdrs as fdr_service
from app.services import verification as verification_service
from app.services import notifications
from app.services.audit import AuditAction, record_audit
from app.services.documents import to_document_read

router = APIRouter(tags=["verification"])

AicteUser = Annotated[User, Depends(require_roles(UserRole.AICTE_OFFICIAL))]
OfficerUser = Annotated[User, Depends(require_roles(UserRole.BANK_OFFICER))]


def _get_bank_officer(db: Session, officer_id: int) -> User:
    officer = db.get(User, officer_id)
    if officer is None or officer.role != UserRole.BANK_OFFICER or not officer.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"loc": ["body", "bank_officer_id"], "msg": "Choose an active bank officer", "type": "value_error"}],
        )
    return officer


def _get_fdr(db: Session, fdr_id: int) -> FDR:
    fdr = db.get(FDR, fdr_id)
    if fdr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FDR record not found")
    return fdr


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


# ---------- AICTE: officers, queue, history ----------


@router.get("/verification/officers", response_model=list[UserBrief])
def list_bank_officers(_user: AicteUser, db: DbSession) -> list[User]:
    """Active bank officers who can receive assignments."""
    return list(
        db.scalars(
            select(User).where(User.role == UserRole.BANK_OFFICER, User.is_active.is_(True)).order_by(User.full_name)
        ).all()
    )


@router.get("/verification/assignments", response_model=Page[AssignmentQueueItem])
def list_assignments(
    _user: AicteUser,
    db: DbSession,
    status_filter: Annotated[list[AssignmentStatus] | None, Query(alias="status")] = None,
    bank_officer_id: int | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[AssignmentQueueItem]:
    """All verification assignments, newest first (AICTE only)."""
    query = select(VerificationAssignment)
    if status_filter:
        query = query.where(VerificationAssignment.status.in_(status_filter))
    if bank_officer_id is not None:
        query = query.where(VerificationAssignment.bank_officer_id == bank_officer_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        verification_service.assignment_query()
        .where(VerificationAssignment.id.in_(query.with_only_columns(VerificationAssignment.id)))
        .order_by(VerificationAssignment.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).unique().all()
    return Page[AssignmentQueueItem](
        items=[verification_service.to_queue_item(row) for row in rows], total=total, page=page, page_size=page_size
    )


@router.get("/fdrs/{fdr_id}/verification", response_model=VerificationHistory)
def verification_history(fdr_id: int, _user: AicteUser, db: DbSession) -> VerificationHistory:
    """Every assignment, outcome and AICTE decision for one FDR. Nothing is overwritten."""
    fdr = _get_fdr(db, fdr_id)
    assignments = db.scalars(
        select(VerificationAssignment)
        .where(VerificationAssignment.fdr_id == fdr.id)
        .order_by(VerificationAssignment.id.desc())
    ).all()
    decisions = db.scalars(
        select(ReviewDecision).where(ReviewDecision.fdr_id == fdr.id).order_by(ReviewDecision.id.desc())
    ).all()
    active = next((a for a in assignments if a.status == AssignmentStatus.ACTIVE), None)
    return VerificationHistory(
        fdr_id=fdr.id,
        fdr_status=fdr.status,
        fdr_version=fdr.version,
        state=verification_service.verification_state(db, fdr),
        can_assign=(active is None and fdr.status in verification_service.ASSIGNABLE_STATUSES
                    and fdr_service.is_workable(fdr)),
        can_accept=verification_service.can_accept(db, fdr),
        active_assignment=verification_service.to_assignment_read(db, active) if active else None,
        assignments=[verification_service.to_assignment_read(db, a) for a in assignments],
        decisions=[verification_service.to_decision_read(d) for d in decisions],
    )


# ---------- AICTE: assign and reassign ----------


@router.post("/fdrs/{fdr_id}/verification/assignments", response_model=AssignmentRead, status_code=status.HTTP_201_CREATED)
def create_assignment(fdr_id: int, payload: AssignmentCreate, request: Request, user: AicteUser, db: DbSession) -> AssignmentRead:
    """Assign an FDR to a bank officer. Moves a Submitted record to Under review,
    which also freezes the institution's edits while the bank checks it."""
    fdr = _get_fdr(db, fdr_id)
    if fdr.version != payload.fdr_version:
        raise _conflict("This record was changed by someone else. Reload it and try again.")
    if fdr.status not in verification_service.ASSIGNABLE_STATUSES:
        raise _conflict(f"Records with status {fdr.status.value} cannot be assigned for verification")
    if not fdr_service.is_workable(fdr):
        raise _conflict(f"This instrument is {fdr.lifecycle_status.value.lower()} and cannot be assigned")
    if verification_service.active_assignment(db, fdr.id) is not None:
        raise _conflict("This record already has an active verification assignment. Use reassignment instead.")
    officer = _get_bank_officer(db, payload.bank_officer_id)

    assignment = VerificationAssignment(
        fdr_id=fdr.id,
        bank_officer_id=officer.id,
        assigned_by_id=user.id,
        assignment_note=payload.note or None,
        status=AssignmentStatus.ACTIVE,
    )
    db.add(assignment)
    changes = {"bank_officer_id": officer.id}
    if fdr.status == FDRStatus.SUBMITTED:
        fdr.status = FDRStatus.UNDER_REVIEW
        fdr.updated_by_id = user.id
        changes["fdr_status"] = {"old": FDRStatus.SUBMITTED.value, "new": FDRStatus.UNDER_REVIEW.value}
    db.flush()  # the partial unique index rejects a concurrent second ACTIVE assignment here
    changes["assignment_id"] = assignment.id
    record_audit(
        db,
        action=AuditAction.VERIFICATION_ASSIGNED,
        entity_type="fdr",
        entity_id=fdr.id,
        institution_id=fdr.institution_id,
        actor=user,
        summary=f"Assigned for bank verification to {officer.full_name} (assignment #{assignment.id})",
        changes=changes,
        request=request,
    )
    notifications.notify(
        db, [officer], event_type="VERIFICATION_ASSIGNED", dedup_key=f"assignment:{assignment.id}:assigned",
        title="New verification case assigned to you",
        body=f"AICTE assigned FDR {fdr.fdr_number} ({fdr.bank_name}) to you for verification against bank records.",
        link=f"/verification/cases/{assignment.id}", fdr_id=None,
    )
    db.commit()
    return verification_service.to_assignment_read(db, assignment)


@router.post("/verification/assignments/{assignment_id}/reassign", response_model=AssignmentRead, status_code=status.HTTP_201_CREATED)
def reassign(assignment_id: int, payload: AssignmentReassign, request: Request, user: AicteUser, db: DbSession) -> AssignmentRead:
    """Move an active case to another officer. The old assignment is kept as SUPERSEDED with the reason."""
    current = db.get(VerificationAssignment, assignment_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    if current.version != payload.version:
        raise _conflict("This assignment was changed by someone else. Reload it and try again.")
    if current.status != AssignmentStatus.ACTIVE:
        raise _conflict(f"Only active assignments can be reassigned (this one is {current.status.value})")
    if payload.bank_officer_id == current.bank_officer_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"loc": ["body", "bank_officer_id"], "msg": "Choose a different bank officer", "type": "value_error"}],
        )
    officer = _get_bank_officer(db, payload.bank_officer_id)
    fdr = current.fdr

    current.status = AssignmentStatus.SUPERSEDED
    current.ended_at = datetime.now(timezone.utc)
    current.ended_by_id = user.id
    current.end_reason = payload.reason
    db.flush()  # close the old one first so the new ACTIVE row satisfies the unique index
    replacement = VerificationAssignment(
        fdr_id=fdr.id,
        bank_officer_id=officer.id,
        assigned_by_id=user.id,
        assignment_note=current.assignment_note,
        previous_assignment_id=current.id,
        status=AssignmentStatus.ACTIVE,
    )
    db.add(replacement)
    db.flush()
    record_audit(
        db,
        action=AuditAction.VERIFICATION_REASSIGNED,
        entity_type="fdr",
        entity_id=fdr.id,
        institution_id=fdr.institution_id,
        actor=user,
        summary=f"Verification reassigned from assignment #{current.id} to {officer.full_name} (#{replacement.id})",
        changes={
            "previous_assignment_id": current.id,
            "assignment_id": replacement.id,
            "bank_officer_id": {"old": current.bank_officer_id, "new": officer.id},
            "reason": payload.reason,
        },
        request=request,
    )
    notifications.notify(
        db, [officer], event_type="VERIFICATION_ASSIGNED", dedup_key=f"assignment:{replacement.id}:assigned",
        title="New verification case assigned to you",
        body=f"AICTE assigned FDR {fdr.fdr_number} ({fdr.bank_name}) to you for verification against bank records.",
        link=f"/verification/cases/{replacement.id}", fdr_id=None,
    )
    notifications.notify(
        db, [current.bank_officer], event_type="VERIFICATION_REASSIGNED", dedup_key=f"assignment:{current.id}:reassigned",
        title="A verification case was reassigned",
        body=f"AICTE reassigned verification case #{current.id} (FDR {fdr.fdr_number}) to another officer. "
             "You no longer have access to it.",
        link=f"/verification/cases/{current.id}", fdr_id=None,
    )
    db.commit()
    return verification_service.to_assignment_read(db, replacement)


# ---------- bank officer: own cases ----------


@router.get("/verification/cases", response_model=Page[BankCaseSummary])
def my_cases(
    user: OfficerUser,
    db: DbSession,
    state: Literal["active", "closed", "all"] = "active",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[BankCaseSummary]:
    """The signed-in officer's own assignments only."""
    query = select(VerificationAssignment.id).where(VerificationAssignment.bank_officer_id == user.id)
    if state == "active":
        query = query.where(VerificationAssignment.status == AssignmentStatus.ACTIVE)
    elif state == "closed":
        query = query.where(VerificationAssignment.status != AssignmentStatus.ACTIVE)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        verification_service.assignment_query()
        .where(VerificationAssignment.id.in_(query))
        .order_by(VerificationAssignment.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).unique().all()
    return Page[BankCaseSummary](
        items=[verification_service.to_case_summary(row) for row in rows], total=total, page=page, page_size=page_size
    )


def _own_assignment(db: Session, request: Request, user: User, assignment_id: int, attempted: str) -> VerificationAssignment:
    assignment = db.get(VerificationAssignment, assignment_id)
    if assignment is None or assignment.bank_officer_id != user.id:
        # Same response whether the case does not exist or belongs to another officer.
        raise verification_service.deny_bank_officer(
            db, request, user, fdr_id=None, assignment_id=assignment_id, attempted=attempted,
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return assignment


@router.get("/verification/cases/{assignment_id}", response_model=BankCase)
def get_case(assignment_id: int, request: Request, user: OfficerUser, db: DbSession) -> BankCase:
    assignment = _own_assignment(db, request, user, assignment_id, "verification_case")
    fdr = assignment.fdr
    active = assignment.status == AssignmentStatus.ACTIVE
    return BankCase(
        id=assignment.id,
        status=assignment.status,
        version=assignment.version,
        assigned_at=assignment.assigned_at,
        assignment_note=assignment.assignment_note,
        ended_at=assignment.ended_at,
        fdr_number=fdr.fdr_number,
        bank_name=fdr.bank_name,
        institution=InstitutionBrief.model_validate(fdr.institution),
        fdr=CaseFDRView(
            id=fdr.id,
            institution=InstitutionBrief.model_validate(fdr.institution),
            bank_name=fdr.bank_name,
            branch_name=fdr.branch_name,
            ifsc_code=fdr.ifsc_code,
            fdr_number=fdr.fdr_number,
            amount=fdr.amount,
            issue_date=fdr.issue_date,
            maturity_date=fdr.maturity_date,
        ) if active else None,
        documents=[to_document_read(document) for document in fdr.documents] if active else [],
        outcome=verification_service.to_outcome_read(db, assignment.outcome) if assignment.outcome else None,
        can_submit_outcome=active,
    )


@router.post("/verification/cases/{assignment_id}/outcome", response_model=BankCase, status_code=status.HTTP_201_CREATED)
def submit_outcome(assignment_id: int, payload: OutcomeSubmit, request: Request, user: OfficerUser, db: DbSession) -> BankCase:
    """Record the officer's outcome. Completes the assignment; one outcome per assignment."""
    assignment = _own_assignment(db, request, user, assignment_id, "verification_outcome")
    if assignment.status != AssignmentStatus.ACTIVE:
        raise _conflict(f"This case is closed ({assignment.status.value}); no outcome can be recorded")
    if assignment.version != payload.version:
        raise _conflict("This case was changed by someone else. Reload it and try again.")

    evidence_ids = sorted(set(payload.evidence_document_ids))
    if evidence_ids:
        valid = set(
            db.scalars(
                select(FDRDocument.id).where(
                    FDRDocument.id.in_(evidence_ids),
                    FDRDocument.fdr_id == assignment.fdr_id,
                    FDRDocument.withdrawn_at.is_(None),
                )
            ).all()
        )
        if valid != set(evidence_ids):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[{
                    "loc": ["body", "evidence_document_ids"],
                    "msg": "Evidence must be current documents attached to this FDR",
                    "type": "value_error",
                }],
            )

    outcome = VerificationOutcome(
        assignment_id=assignment.id,
        fdr_id=assignment.fdr_id,
        officer_id=user.id,
        outcome=payload.outcome,
        notes=payload.notes,
        bank_reference=payload.bank_reference or None,
        evidence_document_ids=evidence_ids,
    )
    db.add(outcome)
    assignment.status = AssignmentStatus.COMPLETED
    assignment.ended_at = datetime.now(timezone.utc)
    db.flush()  # unique(assignment_id) + version check reject a concurrent second submission
    fdr = assignment.fdr
    record_audit(
        db,
        action=AuditAction.VERIFICATION_OUTCOME_SUBMITTED,
        entity_type="fdr",
        entity_id=fdr.id,
        institution_id=fdr.institution_id,
        actor=user,
        summary=f"Bank officer outcome recorded for assignment #{assignment.id}: {payload.outcome.value}",
        changes={
            "assignment_id": assignment.id,
            "outcome_id": outcome.id,
            "outcome": payload.outcome.value,
            "evidence_document_ids": evidence_ids,
        },
        request=request,
    )
    notifications.notify(
        db, notifications.aicte_officials(db), event_type="VERIFICATION_OUTCOME", dedup_key=f"outcome:{outcome.id}",
        title="Bank verification outcome awaiting review",
        body=f"A bank officer recorded an outcome for FDR {fdr.fdr_number} ({fdr.institution.code}). "
             "It awaits an AICTE decision.",
        link=f"/fdr-records/{fdr.id}", fdr_id=fdr.id,
    )
    db.commit()
    db.refresh(assignment)
    return get_case(assignment.id, request, user, db)
