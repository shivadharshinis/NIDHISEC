"""FDR access rules, possible-duplicate detection and serialisation."""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased, joinedload

from app.models import FDR, FDRStatus, User, UserRole
from app.schemas.common import InstitutionBrief
from app.schemas.fdr import DuplicateMatch, DuplicateReview, FDRDetail, FDRListItem

# Institutions may correct their submission only while it is with them.
INSTITUTION_EDITABLE_STATUSES = {FDRStatus.SUBMITTED, FDRStatus.CLARIFICATION_REQUESTED}

REVIEW_TRANSITIONS: dict[FDRStatus, set[FDRStatus]] = {
    FDRStatus.SUBMITTED: {FDRStatus.UNDER_REVIEW, FDRStatus.CLARIFICATION_REQUESTED, FDRStatus.REJECTED},
    # ACCEPTED additionally requires a confirmed bank outcome (see services/verification.py).
    FDRStatus.UNDER_REVIEW: {FDRStatus.CLARIFICATION_REQUESTED, FDRStatus.REJECTED, FDRStatus.ACCEPTED},
    FDRStatus.CLARIFICATION_REQUESTED: {FDRStatus.UNDER_REVIEW, FDRStatus.REJECTED},
    FDRStatus.REJECTED: set(),
    FDRStatus.ACCEPTED: set(),
}

BANK_OFFICER_NO_ACCESS = (
    "Bank officers can only access FDRs assigned to them for verification, "
    "through their verification cases."
)


# ---------- access control ----------


def scoped_fdr_query(user: User) -> Select[tuple[FDR]]:
    """Base query restricted to the FDRs this user may see. Deny by default."""
    query = select(FDR)
    if user.role == UserRole.AICTE_OFFICIAL:
        return query
    if user.role == UserRole.INSTITUTION and user.institution_id is not None:
        return query.where(FDR.institution_id == user.institution_id)
    if user.role == UserRole.BANK_OFFICER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=BANK_OFFICER_NO_ACCESS)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


def get_fdr_for_user(db: Session, user: User, fdr_id: int) -> FDR:
    """Load an FDR the user may see. Records outside the user's scope return 404
    so their existence is not disclosed."""
    query = scoped_fdr_query(user).where(FDR.id == fdr_id).options(
        joinedload(FDR.institution), joinedload(FDR.created_by)
    )
    fdr = db.scalars(query).unique().one_or_none()
    if fdr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FDR record not found")
    return fdr


def is_workable(fdr: FDR) -> bool:
    """Active or proposed instruments; superseded, released or cancelled ones are history."""
    return fdr.lifecycle_status.value in ("ACTIVE", "PROPOSED")


def can_edit(user: User, fdr: FDR) -> bool:
    return (
        user.role == UserRole.INSTITUTION
        and user.institution_id == fdr.institution_id
        and fdr.status in INSTITUTION_EDITABLE_STATUSES
        and is_workable(fdr)
    )


def can_review(user: User, fdr: FDR) -> bool:
    return user.role == UserRole.AICTE_OFFICIAL and bool(REVIEW_TRANSITIONS[fdr.status]) and is_workable(fdr)


# ---------- possible-duplicate detection ----------


def _duplicate_condition(this: Any, other: Any):
    """Same normalised FDR reference, and the same bank (by normalised name or IFSC bank code)."""
    return and_(
        other.id != this.id,
        other.fdr_number_normalized == this.fdr_number_normalized,
        or_(
            other.bank_name_normalized == this.bank_name_normalized,
            and_(
                this.ifsc_code.is_not(None),
                other.ifsc_code.is_not(None),
                func.substr(other.ifsc_code, 1, 4) == func.substr(this.ifsc_code, 1, 4),
            ),
        ),
    )


def has_duplicate_clause():
    """Correlated EXISTS clause: true when an FDR has at least one possible duplicate."""
    other = aliased(FDR)
    return exists().where(_duplicate_condition(FDR, other))


def _is_match(a: FDR, b: FDR) -> bool:
    if a.id == b.id or a.fdr_number_normalized != b.fdr_number_normalized:
        return False
    if a.bank_name_normalized == b.bank_name_normalized:
        return True
    return bool(a.ifsc_code and b.ifsc_code and a.ifsc_code[:4] == b.ifsc_code[:4])


def find_duplicates(db: Session, fdr: FDR) -> list[FDR]:
    """All other records (across every institution) that may be the same FDR."""
    query = (
        select(FDR)
        .where(FDR.id != fdr.id, FDR.fdr_number_normalized == fdr.fdr_number_normalized)
        .options(joinedload(FDR.institution))
        .order_by(FDR.id)
    )
    candidates = db.scalars(query).unique().all()
    return [candidate for candidate in candidates if _is_match(fdr, candidate)]


def duplicate_flags(db: Session, fdrs: Iterable[FDR]) -> set[int]:
    """IDs from `fdrs` that have at least one possible duplicate anywhere."""
    fdrs = list(fdrs)
    numbers = {fdr.fdr_number_normalized for fdr in fdrs}
    if not numbers:
        return set()
    candidates = db.scalars(select(FDR).where(FDR.fdr_number_normalized.in_(numbers))).all()
    return {fdr.id for fdr in fdrs if any(_is_match(fdr, candidate) for candidate in candidates)}


def build_duplicate_review(user: User, fdr: FDR, matches: list[FDR]) -> DuplicateReview:
    visible = [
        match
        for match in matches
        if user.role == UserRole.AICTE_OFFICIAL or match.institution_id == user.institution_id
    ]
    return DuplicateReview(
        flagged=bool(matches),
        match_count=len(matches),
        matches=[
            DuplicateMatch(
                id=match.id,
                institution=InstitutionBrief.model_validate(match.institution),
                bank_name=match.bank_name,
                fdr_number=match.fdr_number,
                status=match.status,
                created_at=match.created_at,
                same_institution=match.institution_id == fdr.institution_id,
            )
            for match in visible
        ],
        hidden_match_count=len(matches) - len(visible),
    )


# ---------- serialisation ----------


def to_list_item(fdr: FDR, possible_duplicate: bool) -> FDRListItem:
    item = FDRListItem.model_validate(fdr)
    item.possible_duplicate = possible_duplicate
    return item


def to_detail(db: Session, user: User, fdr: FDR) -> FDRDetail:
    # Local imports: these modules depend on this one.
    from app.services import documents, verification

    matches = find_duplicates(db, fdr)
    base = to_list_item(fdr, possible_duplicate=bool(matches))
    return FDRDetail(
        **base.model_dump(),
        remarks=fdr.remarks,
        review_remarks=fdr.review_remarks,
        created_by_name=fdr.created_by.full_name,
        documents=[documents.to_document_read(document) for document in fdr.documents],
        duplicate_review=build_duplicate_review(user, fdr, matches),
        can_edit=can_edit(user, fdr),
        can_review=can_review(user, fdr),
        can_upload_documents=documents.can_upload(user, fdr),
        verification_state=verification.verification_state(db, fdr),
    )


def to_paise(amount: Decimal) -> int:
    return int((amount * 100).to_integral_exact())


def audit_value(value: Any) -> Any:
    """JSON-safe representation for audit change summaries."""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, FDRStatus):
        return value.value
    return value


def create_fdr_record(db: Session, user: User, payload, http_request, lifecycle_status=None) -> FDR:
    """Create an FDR for the user's institution with its audit entry and duplicate flag.

    Used by direct submission and by renewal/replacement requests. Flushes but
    does not commit, so callers can include it in a larger transaction.
    """
    from app.models import LifecycleStatus
    from app.services.audit import AuditAction, record_audit
    from app.services.normalization import normalize_bank_name, normalize_fdr_number

    assert user.institution_id is not None  # guaranteed by the users table constraint
    fdr = FDR(
        institution_id=user.institution_id,
        bank_name=payload.bank_name,
        bank_name_normalized=normalize_bank_name(payload.bank_name),
        branch_name=payload.branch_name,
        ifsc_code=payload.ifsc_code,
        fdr_number=payload.fdr_number,
        fdr_number_normalized=normalize_fdr_number(payload.fdr_number),
        amount_paise=to_paise(payload.amount),
        issue_date=payload.issue_date,
        maturity_date=payload.maturity_date,
        remarks=payload.remarks,
        status=FDRStatus.SUBMITTED,
        lifecycle_status=lifecycle_status or LifecycleStatus.ACTIVE,
        created_by_id=user.id,
    )
    db.add(fdr)
    db.flush()
    record_audit(
        db,
        action=AuditAction.FDR_CREATED,
        entity_type="fdr",
        entity_id=fdr.id,
        institution_id=fdr.institution_id,
        actor=user,
        summary=f"FDR {fdr.fdr_number} ({fdr.bank_name}) submitted",
        changes={
            "fdr_number": fdr.fdr_number,
            "bank_name": fdr.bank_name,
            "amount": audit_value(payload.amount),
            "issue_date": fdr.issue_date.isoformat(),
            "maturity_date": fdr.maturity_date.isoformat(),
            "lifecycle_status": fdr.lifecycle_status.value,
        },
        request=http_request,
    )
    matches = find_duplicates(db, fdr)
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
            request=http_request,
        )
    return fdr
