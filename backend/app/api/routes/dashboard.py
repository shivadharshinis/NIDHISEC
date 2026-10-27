"""Role-scoped dashboard counts, computed with grouped queries over real records."""

from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import and_, exists, func, select

from app.api.deps import CurrentUser, DbSession
from app.models import (
    FDR,
    AssignmentStatus,
    FDRStatus,
    LifecycleRequestStatus,
    LifecycleStatus,
    UserRole,
    VerificationAssignment,
)
from app.models.enums import FindingSeverity
from app.models.lifecycle import LifecycleRequest, Notification
from app.models.screening import ScreeningFinding, ScreeningReview, ScreeningRun
from app.schemas.fdr import today_ist
from app.schemas.lifecycle import DashboardSummary
from app.services.lifecycle import OPEN_STATUSES
from app.services.verification import awaiting_decision_conditions

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _grouped(db, column, *conditions) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).where(*conditions).group_by(column)).all()
    return {getattr(key, "value", key): count for key, count in rows}


def _count(db, model, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


@router.get("/summary", response_model=DashboardSummary)
def summary(user: CurrentUser, db: DbSession) -> DashboardSummary:
    today = today_ist()
    unread = _count(db, Notification, Notification.recipient_id == user.id, Notification.read_at.is_(None))
    base = DashboardSummary(role=user.role.value, as_of=today, unread_notifications=unread)

    if user.role == UserRole.BANK_OFFICER:
        mine = VerificationAssignment.bank_officer_id == user.id
        base.cases_awaiting_action = _count(db, VerificationAssignment, mine, VerificationAssignment.status == AssignmentStatus.ACTIVE)
        base.cases_completed = _count(db, VerificationAssignment, mine, VerificationAssignment.status == AssignmentStatus.COMPLETED)
        base.cases_closed_other = _count(db, VerificationAssignment, mine, VerificationAssignment.status.in_(
            [AssignmentStatus.SUPERSEDED, AssignmentStatus.CANCELLED]))
        return base

    # FDR scope: an institution sees only its own records; AICTE sees all.
    scope = [FDR.institution_id == user.institution_id] if user.role == UserRole.INSTITUTION else []
    request_scope = ([LifecycleRequest.institution_id == user.institution_id]
                     if user.role == UserRole.INSTITUTION else [])
    monitored = [*scope, FDR.lifecycle_status == LifecycleStatus.ACTIVE, FDR.status != FDRStatus.REJECTED]

    base.fdr_by_status = _grouped(db, FDR.status, *scope)
    base.fdr_by_lifecycle = _grouped(db, FDR.lifecycle_status, *scope)
    base.maturing_within_30_days = _count(db, FDR, *monitored, FDR.maturity_date >= today,
                                          FDR.maturity_date <= today + timedelta(days=30))
    base.overdue_active = _count(db, FDR, *monitored, FDR.maturity_date < today)
    base.lifecycle_requests_open = _grouped(db, LifecycleRequest.request_type, *request_scope,
                                            LifecycleRequest.status.in_(OPEN_STATUSES))

    if user.role == UserRole.INSTITUTION:
        base.clarifications_requiring_action = (
            _count(db, FDR, *scope, FDR.status == FDRStatus.CLARIFICATION_REQUESTED,
                   FDR.lifecycle_status.in_([LifecycleStatus.ACTIVE, LifecycleStatus.PROPOSED]))
            + _count(db, LifecycleRequest, *request_scope,
                     LifecycleRequest.status == LifecycleRequestStatus.CLARIFICATION_REQUESTED)
        )
        return base

    # AICTE officials
    base.lifecycle_requests_awaiting_decision = _grouped(
        db, LifecycleRequest.request_type,
        LifecycleRequest.status.in_([LifecycleRequestStatus.SUBMITTED, LifecycleRequestStatus.UNDER_REVIEW]))
    base.lifecycle_requests_awaiting_completion = _count(db, LifecycleRequest,
                                                         LifecycleRequest.status == LifecycleRequestStatus.APPROVED)
    base.verification_active = _count(db, VerificationAssignment, VerificationAssignment.status == AssignmentStatus.ACTIVE)

    # Same definition as the review queue (GET /verification/awaiting-decision).
    base.verification_outcomes_awaiting_decision = _count(db, FDR, *awaiting_decision_conditions())

    # Unreviewed findings in each FDR's latest screening run.
    latest = (select(ScreeningRun.fdr_id, func.max(ScreeningRun.run_number).label("run_number"))
              .group_by(ScreeningRun.fdr_id).subquery())
    unreviewed = (
        select(ScreeningFinding.severity, func.count())
        .join(ScreeningRun, ScreeningFinding.run_id == ScreeningRun.id)
        .join(latest, and_(ScreeningRun.fdr_id == latest.c.fdr_id, ScreeningRun.run_number == latest.c.run_number))
        .where(~exists().where(ScreeningReview.finding_id == ScreeningFinding.id))
        .group_by(ScreeningFinding.severity)
    )
    counts = {getattr(k, "value", k): v for k, v in db.execute(unreviewed).all()}
    base.screening_unreviewed_high = counts.get(FindingSeverity.HIGH.value, 0)
    base.screening_unreviewed_warning = counts.get(FindingSeverity.WARNING.value, 0)
    return base
