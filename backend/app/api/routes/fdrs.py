from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import joinedload

from app.api.deps import CurrentUser, DbSession, require_roles
from app.models import (
    FDR,
    AssignmentStatus,
    AuditLog,
    DocumentType,
    FDRDocument,
    FDRStatus,
    Institution,
    LifecycleStatus,
    ReviewDecision,
    User,
    UserRole,
)
from app.schemas.common import Page
from app.schemas.fdr import (
    FDRCreate,
    FDRDetail,
    FDRHistoryEntry,
    FDRListItem,
    FDRReview,
    FDRSummary,
    FDRUpdate,
    fdr_date_errors,
    today_ist,
)
from app.services import fdrs as fdr_service
from app.services import verification as verification_service
from app.services import notifications
from app.services.audit import AuditAction, record_audit
from app.services.normalization import normalize_bank_name, normalize_fdr_number

router = APIRouter(prefix="/fdrs", tags=["fdrs"])

STATUS_WORDS = {
    FDRStatus.CLARIFICATION_REQUESTED: "clarification requested",
    FDRStatus.REJECTED: "rejected",
    FDRStatus.ACCEPTED: "accepted after the bank officer's recorded confirmation",
}

# Internal verification and screening steps that institutions do not see in their record history.
INSTITUTION_HIDDEN_ACTIONS = [
    AuditAction.VERIFICATION_ASSIGNED.value,
    AuditAction.VERIFICATION_REASSIGNED.value,
    AuditAction.VERIFICATION_CANCELLED.value,
    AuditAction.VERIFICATION_OUTCOME_SUBMITTED.value,
    AuditAction.VERIFICATION_ACCESS_DENIED.value,
    AuditAction.SCREENING_RUN_COMPLETED.value,
    AuditAction.SCREENING_RUN_FAILED.value,
    AuditAction.SCREENING_FINDING_REVIEWED.value,
    AuditAction.SCREENING_ACCESS_DENIED.value,
    AuditAction.LIFECYCLE_ACCESS_DENIED.value,
]

InstitutionUser = Annotated[User, Depends(require_roles(UserRole.INSTITUTION))]
AicteUser = Annotated[User, Depends(require_roles(UserRole.AICTE_OFFICIAL))]

SortOption = Literal["newest", "oldest", "maturity_asc", "maturity_desc", "amount_desc", "amount_asc"]
SORTS = {
    "newest": FDR.id.desc(),
    "oldest": FDR.id.asc(),
    "maturity_asc": FDR.maturity_date.asc(),
    "maturity_desc": FDR.maturity_date.desc(),
    "amount_desc": FDR.amount_paise.desc(),
    "amount_asc": FDR.amount_paise.asc(),
}

EDITABLE_FIELDS = ("bank_name", "branch_name", "ifsc_code", "fdr_number", "amount", "issue_date", "maturity_date", "remarks")


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _check_version(fdr: FDR, version: int) -> None:
    if fdr.version != version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This record was changed by someone else. Reload it and try again.",
        )


def _flag_duplicates(db: DbSession, request: Request, user: User, fdr: FDR) -> None:
    matches = fdr_service.find_duplicates(db, fdr)
    if matches:
        record_audit(
            db,
            action=AuditAction.FDR_DUPLICATE_FLAGGED,
            entity_type="fdr",
            entity_id=fdr.id,
            institution_id=fdr.institution_id,
            actor=user,
            summary=f"Possible duplicate of {len(matches)} existing record(s); flagged for review",
            changes={"match_count": len(matches)},
            request=request,
        )


@router.get("", response_model=Page[FDRListItem])
def list_fdrs(
    user: CurrentUser,
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=100, description="Search FDR number, bank, branch or institution")] = None,
    status_filter: Annotated[list[FDRStatus] | None, Query(alias="status")] = None,
    institution_id: Annotated[int | None, Query(description="AICTE officials only")] = None,
    maturity_from: date | None = None,
    maturity_to: date | None = None,
    duplicates_only: bool = False,
    missing_fdr_copy: Annotated[
        bool, Query(description="Only records without a current (non-withdrawn) document of type FDR copy")
    ] = False,
    sort: SortOption = "newest",
) -> Page[FDRListItem]:
    query = fdr_service.scoped_fdr_query(user).join(FDR.institution)

    if q and q.strip():
        pattern = _like(q.strip())
        query = query.where(
            or_(
                FDR.fdr_number.ilike(pattern, escape="\\"),
                FDR.bank_name.ilike(pattern, escape="\\"),
                FDR.branch_name.ilike(pattern, escape="\\"),
                Institution.name.ilike(pattern, escape="\\"),
                Institution.code.ilike(pattern, escape="\\"),
            )
        )
    if status_filter:
        query = query.where(FDR.status.in_(status_filter))
    if institution_id is not None and user.role == UserRole.AICTE_OFFICIAL:
        query = query.where(FDR.institution_id == institution_id)
    if maturity_from:
        query = query.where(FDR.maturity_date >= maturity_from)
    if maturity_to:
        query = query.where(FDR.maturity_date <= maturity_to)
    if duplicates_only:
        query = query.where(fdr_service.has_duplicate_clause())
    if missing_fdr_copy:
        query = query.where(~exists().where(
            FDRDocument.fdr_id == FDR.id,
            FDRDocument.document_type == DocumentType.FDR_COPY,
            FDRDocument.withdrawn_at.is_(None),
        ))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.options(joinedload(FDR.institution))
        .order_by(SORTS[sort], FDR.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    flagged = fdr_service.duplicate_flags(db, rows)
    return Page[FDRListItem](
        items=[fdr_service.to_list_item(fdr, fdr.id in flagged) for fdr in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/summary", response_model=FDRSummary)
def fdr_summary(user: CurrentUser, db: DbSession) -> FDRSummary:
    """Counts for the dashboard, limited to the records this user may see."""
    visible = fdr_service.scoped_fdr_query(user).subquery()
    by_status = dict(db.execute(select(visible.c.status, func.count()).group_by(visible.c.status)).all())

    scoped = fdr_service.scoped_fdr_query(user)
    today = today_ist()

    def count(query) -> int:
        return db.scalar(select(func.count()).select_from(query.subquery())) or 0

    open_statuses = [s for s in FDRStatus if s != FDRStatus.REJECTED]
    possible_duplicates = count(scoped.where(fdr_service.has_duplicate_clause()))
    # Maturity matters only for the instrument currently in force (not renewed, released or proposed ones).
    scoped = scoped.where(FDR.lifecycle_status == LifecycleStatus.ACTIVE)
    return FDRSummary(
        total=sum(by_status.values()),
        by_status={s: by_status.get(s, 0) for s in FDRStatus},
        possible_duplicates=possible_duplicates,
        maturing_within_90_days=count(
            scoped.where(
                FDR.status.in_(open_statuses),
                FDR.maturity_date >= today,
                FDR.maturity_date <= today + timedelta(days=90),
            )
        ),
        matured=count(scoped.where(FDR.status.in_(open_statuses), FDR.maturity_date < today)),
    )


@router.post("", response_model=FDRDetail, status_code=status.HTTP_201_CREATED)
def create_fdr(payload: FDRCreate, request: Request, user: InstitutionUser, db: DbSession) -> FDRDetail:
    """Submit an FDR for the signed-in user's institution.

    A record with the same bank and FDR reference as an existing one is still
    saved, as a separate record, and flagged as a possible duplicate for review.
    """
    fdr = fdr_service.create_fdr_record(db, user, payload, request)
    db.commit()
    return fdr_service.to_detail(db, user, fdr_service.get_fdr_for_user(db, user, fdr.id))


@router.get("/{fdr_id}", response_model=FDRDetail)
def get_fdr(fdr_id: int, request: Request, user: CurrentUser, db: DbSession) -> FDRDetail:
    if user.role == UserRole.BANK_OFFICER:
        # Bank officers use /verification/cases; direct record access is denied and audited.
        raise verification_service.deny_bank_officer(db, request, user, fdr_id=fdr_id, attempted="fdr_detail")
    return fdr_service.to_detail(db, user, fdr_service.get_fdr_for_user(db, user, fdr_id))


@router.patch("/{fdr_id}", response_model=FDRDetail)
def update_fdr(fdr_id: int, payload: FDRUpdate, request: Request, user: InstitutionUser, db: DbSession) -> FDRDetail:
    """Correct an FDR's details. Allowed for the owning institution while the
    record is Submitted or Clarification Requested."""
    fdr = fdr_service.get_fdr_for_user(db, user, fdr_id)
    if not fdr_service.is_workable(fdr):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This instrument is {fdr.lifecycle_status.value.lower()} and can no longer be edited",
        )
    if fdr.status not in fdr_service.INSTITUTION_EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Records with status {fdr.status.value} cannot be edited",
        )
    _check_version(fdr, payload.version)

    current = {
        "bank_name": fdr.bank_name,
        "branch_name": fdr.branch_name,
        "ifsc_code": fdr.ifsc_code,
        "fdr_number": fdr.fdr_number,
        "amount": fdr.amount,
        "issue_date": fdr.issue_date,
        "maturity_date": fdr.maturity_date,
        "remarks": fdr.remarks,
    }
    proposed = {**current, **{name: getattr(payload, name) for name in EDITABLE_FIELDS if name in payload.model_fields_set}}

    date_errors = fdr_date_errors(proposed["issue_date"], proposed["maturity_date"])
    if date_errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"loc": ["body", field], "msg": message, "type": "value_error"} for field, message in date_errors],
        )

    changes = {
        name: {"old": fdr_service.audit_value(current[name]), "new": fdr_service.audit_value(proposed[name])}
        for name in EDITABLE_FIELDS
        if proposed[name] != current[name]
    }
    if not changes:
        return fdr_service.to_detail(db, user, fdr)

    reference_changed = "bank_name" in changes or "fdr_number" in changes or "ifsc_code" in changes
    fdr.bank_name = proposed["bank_name"]
    fdr.bank_name_normalized = normalize_bank_name(proposed["bank_name"])
    fdr.branch_name = proposed["branch_name"]
    fdr.ifsc_code = proposed["ifsc_code"]
    fdr.fdr_number = proposed["fdr_number"]
    fdr.fdr_number_normalized = normalize_fdr_number(proposed["fdr_number"])
    fdr.amount_paise = fdr_service.to_paise(proposed["amount"])
    fdr.issue_date = proposed["issue_date"]
    fdr.maturity_date = proposed["maturity_date"]
    fdr.remarks = proposed["remarks"]
    fdr.updated_by_id = user.id

    summary = f"FDR {fdr.fdr_number} updated ({', '.join(changes)})"
    if fdr.status == FDRStatus.CLARIFICATION_REQUESTED:
        changes["status"] = {"old": fdr.status.value, "new": FDRStatus.SUBMITTED.value}
        fdr.status = FDRStatus.SUBMITTED
        summary += "; resubmitted after clarification"

    record_audit(
        db,
        action=AuditAction.FDR_UPDATED,
        entity_type="fdr",
        entity_id=fdr.id,
        institution_id=fdr.institution_id,
        actor=user,
        summary=summary,
        changes=changes,
        request=request,
    )
    db.flush()
    if reference_changed:
        _flag_duplicates(db, request, user, fdr)
    db.commit()
    return fdr_service.to_detail(db, user, fdr)


@router.post("/{fdr_id}/review", response_model=FDRDetail)
def review_fdr(fdr_id: int, payload: FDRReview, request: Request, user: AicteUser, db: DbSession) -> FDRDetail:
    """Record an AICTE review decision.

    Decisions are stored append-only and kept separate from bank officers'
    verification outcomes. ACCEPTED is only possible once the current bank
    outcome is "confirmed against bank records" and no assignment is open.
    Returning a record for clarification, or rejecting it, closes any open
    verification assignment. No decision confirms that an FDR is genuine.
    """
    fdr = fdr_service.get_fdr_for_user(db, user, fdr_id)
    _check_version(fdr, payload.version)
    if not fdr_service.is_workable(fdr):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This instrument is {fdr.lifecycle_status.value.lower()}; its review status can no longer change",
        )
    if payload.status not in fdr_service.REVIEW_TRANSITIONS[fdr.status]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot change status from {fdr.status.value} to {payload.status.value}",
        )
    if payload.status == FDRStatus.ACCEPTED and not verification_service.can_accept(db, fdr):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A record can be accepted only after a bank officer has recorded a confirmed outcome "
            "and no verification assignment is open",
        )

    previous_status = fdr.status
    outcome = verification_service.latest_outcome(db, fdr.id)
    if payload.status in (FDRStatus.CLARIFICATION_REQUESTED, FDRStatus.REJECTED):
        verification_service.end_active_assignment(
            db, fdr, user, AssignmentStatus.CANCELLED,
            f"Record {'returned to the institution' if payload.status == FDRStatus.CLARIFICATION_REQUESTED else 'rejected'} by AICTE",
            request,
        )

    decision = ReviewDecision(
        fdr_id=fdr.id,
        decided_by_id=user.id,
        previous_status=previous_status,
        new_status=payload.status,
        message_to_institution=payload.review_remarks,
        internal_notes=payload.internal_notes,
        reviewed_outcome_id=outcome.id if outcome else None,
    )
    db.add(decision)
    fdr.status = payload.status
    fdr.review_remarks = payload.review_remarks
    fdr.updated_by_id = user.id
    db.flush()
    record_audit(
        db,
        action=AuditAction.FDR_STATUS_CHANGED,
        entity_type="fdr",
        entity_id=fdr.id,
        institution_id=fdr.institution_id,
        actor=user,
        summary=f"Status changed from {previous_status.value} to {payload.status.value}",
        # Internal notes live only in review_decisions, never in the shared history.
        changes={
            "status": {"old": previous_status.value, "new": payload.status.value},
            "review_remarks": payload.review_remarks,
            "decision_id": decision.id,
            "reviewed_outcome_id": decision.reviewed_outcome_id,
        },
        request=request,
    )
    institution_titles = {
        FDRStatus.CLARIFICATION_REQUESTED: "AICTE requested clarification on your FDR",
        FDRStatus.REJECTED: "Your FDR was rejected by AICTE",
        FDRStatus.ACCEPTED: "Your FDR was accepted by AICTE",
    }
    if payload.status in institution_titles:
        notifications.notify(
            db, notifications.institution_users(db, fdr.institution_id), event_type=f"FDR_{payload.status.value}",
            dedup_key=f"review_decision:{decision.id}", title=institution_titles[payload.status],
            body=f"FDR {fdr.fdr_number}: {STATUS_WORDS[payload.status]}. Open the record for AICTE's message.",
            link=f"/fdr-records/{fdr.id}", fdr_id=fdr.id,
        )
    db.commit()
    return fdr_service.to_detail(db, user, fdr)


@router.get("/{fdr_id}/history", response_model=list[FDRHistoryEntry])
def fdr_history(fdr_id: int, user: CurrentUser, db: DbSession) -> list[AuditLog]:
    """Audit trail for a single record, visible to anyone who may view the record."""
    fdr = fdr_service.get_fdr_for_user(db, user, fdr_id)
    query = select(AuditLog).where(AuditLog.entity_type == "fdr", AuditLog.entity_id == fdr.id)
    if user.role != UserRole.AICTE_OFFICIAL:
        # Institutions do not see internal verification steps or which bank officer handled the case.
        query = query.where(
            AuditLog.action.not_in(INSTITUTION_HIDDEN_ACTIONS),
            or_(AuditLog.actor_role.is_(None), AuditLog.actor_role != UserRole.BANK_OFFICER.value),
        )
    return list(db.scalars(query.order_by(AuditLog.id.desc())).all())
