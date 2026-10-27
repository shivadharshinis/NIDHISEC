"""Advisory screening endpoints. AICTE officials only.

Screening results include cross-institution comparisons and internal
assessments, so institutions and bank officers cannot reach any of these
endpoints; their attempts are refused with 403 and audited. Nothing here
changes an FDR's status, its documents or its verification workflow.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import CurrentUser, DbSession
from app.models import FDR, User, UserRole
from app.models.enums import FindingSeverity, ReviewPriority
from app.models.screening import ScreeningFinding, ScreeningReview, ScreeningRun
from app.schemas.common import InstitutionBrief, Page
from app.schemas.screening import (
    FindingRead,
    NoLongerRaised,
    RunDetail,
    RunSummary,
    ScreeningOverview,
    ScreeningQueueItem,
    ScreeningReviewCreate,
    ScreeningReviewRead,
)
from app.schemas.verification import UserBrief
from app.services import screening as screening_service
from app.services.audit import AuditAction, record_audit

router = APIRouter(tags=["screening"])

PRIORITY_EXPLANATION = (
    "HIGH: at least one high-priority finding. MEDIUM: otherwise at least one warning. LOW: informational "
    "findings only. Maturity-timing findings never raise the priority. This is a review-ordering aid, "
    "not a score or a probability of fraud."
)
PRIORITY_ORDER = {ReviewPriority.HIGH: 0, ReviewPriority.MEDIUM: 1, ReviewPriority.LOW: 2, None: 3}


def require_screening_access(request: Request, user: CurrentUser, db: DbSession) -> User:
    if user.role != UserRole.AICTE_OFFICIAL:
        fdr_id = request.path_params.get("fdr_id")
        record_audit(
            db,
            action=AuditAction.SCREENING_ACCESS_DENIED,
            entity_type="fdr" if fdr_id else "screening",
            entity_id=int(fdr_id) if fdr_id and str(fdr_id).isdigit() else None,
            actor=user,
            summary=f"Screening access denied ({request.method} {request.url.path})",
            changes={"role": user.role.value},
            request=request,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Screening is available to AICTE officials only")
    return user


ScreeningUser = Annotated[User, Depends(require_screening_access)]


# ---------- serialisation ----------


def _review_read(review: ScreeningReview, run_number: int) -> ScreeningReviewRead:
    return ScreeningReviewRead(
        id=review.id, finding_id=review.finding_id, run_number=run_number, disposition=review.disposition,
        notes=review.notes, reviewer=UserBrief.model_validate(review.reviewer), reviewed_at=review.reviewed_at,
    )


def _run_summary(run: ScreeningRun) -> RunSummary:
    return RunSummary(
        id=run.id, run_number=run.run_number, status=run.status, engine_version=run.engine_version,
        started_at=run.started_at, completed_at=run.completed_at,
        triggered_by=UserBrief.model_validate(run.triggered_by), review_priority=run.review_priority,
        high_count=run.high_count, warning_count=run.warning_count, info_count=run.info_count,
        fdr_version=run.fdr_version, error_code=run.error_code,
    )


def _is_stale(run: ScreeningRun, fdr: FDR) -> bool:
    return run.fdr_version != fdr.version or run.documents_fingerprint != screening_service._documents_fingerprint(
        list(fdr.documents)
    )


def _run_detail(db: Session, run: ScreeningRun, fdr: FDR, all_runs: list[ScreeningRun]) -> RunDetail:
    earlier = [r for r in all_runs if r.run_number < run.run_number]
    # Earlier human reviews, by fingerprint, for context only.
    earlier_reviews: dict[str, list[ScreeningReviewRead]] = {}
    for previous in earlier:
        for finding in previous.findings:
            for review in finding.reviews:
                earlier_reviews.setdefault(finding.fingerprint, []).append(_review_read(review, previous.run_number))

    findings = [
        FindingRead(
            id=f.id, code=f.code, rule_version=f.rule_version, category=f.category, severity=f.severity,
            title=f.title, description=f.description, reason=f.reason, field=f.field, observed=f.observed,
            document_id=f.document_id, related_fdr_id=f.related_fdr_id, match_type=f.match_type,
            fingerprint=f.fingerprint, reviews=[_review_read(r, run.run_number) for r in f.reviews],
            earlier_reviews=earlier_reviews.get(f.fingerprint, []),
        )
        for f in sorted(run.findings, key=lambda f: (["HIGH", "WARNING", "INFO"].index(f.severity.value), f.id))
    ]

    no_longer: list[NoLongerRaised] = []
    previous_completed = next((r for r in sorted(earlier, key=lambda r: -r.run_number)
                               if r.status.value == "COMPLETED"), None)
    if previous_completed and run.status.value == "COMPLETED":
        current = {f.fingerprint for f in run.findings}
        no_longer = [
            NoLongerRaised(code=f.code, title=f.title, severity=f.severity, fingerprint=f.fingerprint,
                           previous_run_number=previous_completed.run_number, reviewed_by_human=bool(f.reviews))
            for f in previous_completed.findings if f.fingerprint not in current
        ]

    latest = max(all_runs, key=lambda r: r.run_number)
    return RunDetail(
        **_run_summary(run).model_dump(), findings=findings, extraction=run.extraction,
        no_longer_raised=no_longer, is_latest=run.id == latest.id, is_stale=_is_stale(run, fdr),
    )


def _load_fdr(db: Session, fdr_id: int) -> FDR:
    fdr = db.get(FDR, fdr_id)
    if fdr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FDR record not found")
    return fdr


def _runs(db: Session, fdr_id: int) -> list[ScreeningRun]:
    return list(db.scalars(
        select(ScreeningRun).where(ScreeningRun.fdr_id == fdr_id)
        .options(joinedload(ScreeningRun.findings).joinedload(ScreeningFinding.reviews).joinedload(ScreeningReview.reviewer),
                 joinedload(ScreeningRun.triggered_by))
        .order_by(ScreeningRun.run_number.desc())
    ).unique().all())


# ---------- endpoints ----------


@router.get("/fdrs/{fdr_id}/screening", response_model=ScreeningOverview)
def screening_overview(fdr_id: int, _user: ScreeningUser, db: DbSession) -> ScreeningOverview:
    fdr = _load_fdr(db, fdr_id)
    runs = _runs(db, fdr.id)
    return ScreeningOverview(
        fdr_id=fdr.id, advisory_notice=screening_service.ADVISORY_NOTICE, priority_explanation=PRIORITY_EXPLANATION,
        latest=_run_detail(db, runs[0], fdr, runs) if runs else None,
        runs=[_run_summary(r) for r in runs],
    )


@router.post("/fdrs/{fdr_id}/screening/runs", response_model=RunDetail, status_code=status.HTTP_201_CREATED)
def run_screening(fdr_id: int, request: Request, user: ScreeningUser, db: DbSession) -> RunDetail:
    """Screen the FDR now. Earlier runs are kept. Never changes the FDR or its workflow."""
    fdr = _load_fdr(db, fdr_id)
    run = screening_service.run_screening(db, fdr, user, request)
    fdr = _load_fdr(db, fdr_id)
    runs = _runs(db, fdr.id)
    return _run_detail(db, next(r for r in runs if r.id == run.id), fdr, runs)


@router.get("/fdrs/{fdr_id}/screening/runs/{run_id}", response_model=RunDetail)
def get_run(fdr_id: int, run_id: int, _user: ScreeningUser, db: DbSession) -> RunDetail:
    fdr = _load_fdr(db, fdr_id)
    runs = _runs(db, fdr.id)
    run = next((r for r in runs if r.id == run_id), None)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screening run not found")
    return _run_detail(db, run, fdr, runs)


@router.post("/fdrs/{fdr_id}/screening/findings/{finding_id}/reviews", response_model=ScreeningReviewRead,
             status_code=status.HTTP_201_CREATED)
def review_finding(fdr_id: int, finding_id: int, payload: ScreeningReviewCreate, request: Request,
                   user: ScreeningUser, db: DbSession) -> ScreeningReviewRead:
    """Record a human judgement on a finding of the latest run. Earlier reviews are kept."""
    fdr = _load_fdr(db, fdr_id)
    finding = db.get(ScreeningFinding, finding_id)
    if finding is None or finding.run.fdr_id != fdr.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    latest_number = db.scalar(select(func.max(ScreeningRun.run_number)).where(ScreeningRun.fdr_id == fdr.id))
    if finding.run.run_number != latest_number:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only findings of the latest screening run can be reviewed. Reload to see the latest run.",
        )
    review = ScreeningReview(finding_id=finding.id, reviewer_id=user.id, disposition=payload.disposition,
                             notes=payload.notes)
    db.add(review)
    db.flush()
    record_audit(
        db, action=AuditAction.SCREENING_FINDING_REVIEWED, entity_type="fdr", entity_id=fdr.id,
        institution_id=fdr.institution_id, actor=user, request=request,
        summary=f"Screening finding {finding.code} (run #{finding.run.run_number}) reviewed: {payload.disposition.value}",
        changes={"finding_id": finding.id, "review_id": review.id, "run_id": finding.run_id,
                 "disposition": payload.disposition.value},
    )
    db.commit()
    db.refresh(review)
    return _review_read(review, finding.run.run_number)


@router.get("/screening/queue", response_model=Page[ScreeningQueueItem])
def screening_queue(
    _user: ScreeningUser,
    db: DbSession,
    priority: ReviewPriority | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[ScreeningQueueItem]:
    """Latest screening run of every screened FDR, highest priority first."""
    latest = (
        select(ScreeningRun.fdr_id, func.max(ScreeningRun.run_number).label("run_number"))
        .group_by(ScreeningRun.fdr_id).subquery()
    )
    query = (
        select(ScreeningRun)
        .join(latest, and_(ScreeningRun.fdr_id == latest.c.fdr_id, ScreeningRun.run_number == latest.c.run_number))
        .options(joinedload(ScreeningRun.findings).joinedload(ScreeningFinding.reviews))
    )
    if priority is not None:
        query = query.where(ScreeningRun.review_priority == priority)
    runs = sorted(db.scalars(query).unique().all(),
                  key=lambda r: (PRIORITY_ORDER[r.review_priority], -r.completed_at.timestamp()))
    total = len(runs)
    window = runs[(page - 1) * page_size: page * page_size]
    fdrs = {f.id: f for f in db.scalars(
        select(FDR).where(FDR.id.in_([r.fdr_id for r in window])).options(joinedload(FDR.institution))
    ).unique().all()}

    def unreviewed(run: ScreeningRun, severity: FindingSeverity) -> int:
        return sum(1 for f in run.findings if f.severity == severity and not f.reviews)

    items = [
        ScreeningQueueItem(
            fdr_id=run.fdr_id, fdr_number=fdrs[run.fdr_id].fdr_number, bank_name=fdrs[run.fdr_id].bank_name,
            institution=InstitutionBrief.model_validate(fdrs[run.fdr_id].institution),
            fdr_status=fdrs[run.fdr_id].status, run_id=run.id, run_number=run.run_number, run_status=run.status,
            completed_at=run.completed_at, review_priority=run.review_priority, high_count=run.high_count,
            warning_count=run.warning_count, info_count=run.info_count,
            unreviewed_high=unreviewed(run, FindingSeverity.HIGH),
            unreviewed_warning=unreviewed(run, FindingSeverity.WARNING),
            is_stale=_is_stale(run, fdrs[run.fdr_id]),
        )
        for run in window
    ]
    return Page[ScreeningQueueItem](items=items, total=total, page=page, page_size=page_size)
