from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_, select

from app.api.deps import DbSession, require_roles
from app.models import FDR, FDRStatus, Institution, User, UserRole
from app.schemas.common import InstitutionBrief, InstitutionSummary, Page

router = APIRouter(prefix="/institutions", tags=["institutions"])

AicteUser = Annotated[User, Depends(require_roles(UserRole.AICTE_OFFICIAL))]

# Records still with AICTE or the institution, i.e. without a final review decision.
OPEN_REVIEW_STATUSES = (FDRStatus.SUBMITTED, FDRStatus.UNDER_REVIEW, FDRStatus.CLARIFICATION_REQUESTED)


@router.get("", response_model=list[InstitutionBrief])
def list_institutions(
    db: DbSession,
    user: Annotated[User, Depends(require_roles(UserRole.AICTE_OFFICIAL, UserRole.INSTITUTION))],
) -> list[Institution]:
    """AICTE officials see all institutions (e.g. for filtering); institution users see only their own."""
    query = select(Institution).order_by(Institution.name)
    if user.role == UserRole.INSTITUTION:
        query = query.where(Institution.id == user.institution_id)
    return list(db.scalars(query).all())


def _fdr_counts():
    """Per-institution FDR counts, grouped once so a page of results needs one query."""
    return (
        select(
            FDR.institution_id.label("institution_id"),
            func.count(FDR.id).label("fdr_total"),
            func.sum(case((FDR.status.in_(OPEN_REVIEW_STATUSES), 1), else_=0)).label("open_review"),
            func.sum(case((FDR.status == FDRStatus.ACCEPTED, 1), else_=0)).label("accepted"),
            func.sum(case((FDR.status == FDRStatus.REJECTED, 1), else_=0)).label("rejected"),
            func.max(FDR.created_at).label("latest_submission_at"),
        )
        .group_by(FDR.institution_id)
        .subquery()
    )


def _summary(institution: Institution, counts) -> InstitutionSummary:
    latest: datetime | None = counts.latest_submission_at if counts else None
    return InstitutionSummary(
        id=institution.id,
        name=institution.name,
        code=institution.code,
        state=institution.state,
        contact_email=institution.contact_email,
        contact_phone=institution.contact_phone,
        fdr_total=counts.fdr_total if counts else 0,
        fdrs_open_review=int(counts.open_review or 0) if counts else 0,
        fdrs_accepted=int(counts.accepted or 0) if counts else 0,
        fdrs_rejected=int(counts.rejected or 0) if counts else 0,
        latest_submission_at=latest,
    )


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/search", response_model=Page[InstitutionSummary])
def search_institutions(
    db: DbSession,
    _user: AicteUser,
    q: Annotated[str | None, Query(max_length=100, description="Part of the college name, code or state")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[InstitutionSummary]:
    """AICTE college directory: matching institutions with counts of their FDRs."""
    query = select(Institution)
    if q and q.strip():
        pattern = _like(q.strip())
        query = query.where(or_(
            Institution.name.ilike(pattern, escape="\\"),
            Institution.code.ilike(pattern, escape="\\"),
            Institution.state.ilike(pattern, escape="\\"),
        ))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    counts = _fdr_counts()
    rows = db.execute(
        select(Institution, *counts.c)
        .outerjoin(counts, counts.c.institution_id == Institution.id)
        .where(Institution.id.in_(query.with_only_columns(Institution.id)))
        .order_by(Institution.name, Institution.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page[InstitutionSummary](
        items=[_summary(row[0], row if row.institution_id is not None else None) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{institution_id}", response_model=InstitutionSummary)
def get_institution(institution_id: int, db: DbSession, _user: AicteUser) -> InstitutionSummary:
    institution = db.get(Institution, institution_id)
    if institution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")
    counts = _fdr_counts()
    row = db.execute(select(counts).where(counts.c.institution_id == institution_id)).one_or_none()
    return _summary(institution, row)
