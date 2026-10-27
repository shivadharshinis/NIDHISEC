"""AICTE reporting snapshot: grouped counts over current records.

Read-only and AICTE-only. Returns counts and amount totals, never remarks,
internal notes, documents or screening details. It describes the current
state of records at request time, not activity over a period.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select

from app.api.deps import DbSession, require_roles
from app.models import FDR, FDRStatus, Institution, LifecycleStatus, UserRole
from app.models.lifecycle import LifecycleRequest
from app.schemas.common import InstitutionBrief
from app.schemas.fdr import today_ist
from app.schemas.reports import InstitutionSummary, MaturityBucket, ReportSummary, RequestCount
from app.services.lifecycle import OPEN_STATUSES

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(require_roles(UserRole.AICTE_OFFICIAL))])

BUCKET_LABELS = {
    "OVERDUE": "Matured (past maturity date), still active",
    "DUE_0_30": "Maturing in 0–30 days",
    "DUE_31_90": "Maturing in 31–90 days",
    "DUE_91_365": "Maturing in 91–365 days",
    "LATER": "Maturing after 365 days",
}
SCOPE_NOTE = (
    "Snapshot of current records at the time shown. Counts reflect each record's present status, not activity "
    "during a period. Maturity figures cover active instruments that are not rejected; dates use Indian Standard Time."
)


def _money(paise: int | None) -> Decimal:
    return Decimal(paise or 0).scaleb(-2)


@router.get("/summary", response_model=ReportSummary)
def report_summary(db: DbSession) -> ReportSummary:
    today = today_ist()
    monitored = (FDR.lifecycle_status == LifecycleStatus.ACTIVE, FDR.status != FDRStatus.REJECTED)

    def value(key):
        return getattr(key, "value", key)

    by_status = {value(k): c for k, c in db.execute(select(FDR.status, func.count()).group_by(FDR.status)).all()}
    by_lifecycle = {value(k): c for k, c in db.execute(
        select(FDR.lifecycle_status, func.count()).group_by(FDR.lifecycle_status)).all()}
    requests = [
        RequestCount(request_type=t, status=s, count=c)
        for t, s, c in db.execute(
            select(LifecycleRequest.request_type, LifecycleRequest.status, func.count())
            .group_by(LifecycleRequest.request_type, LifecycleRequest.status)
            .order_by(LifecycleRequest.request_type, LifecycleRequest.status)
        ).all()
    ]

    bucket = case(
        (FDR.maturity_date < today, "OVERDUE"),
        (FDR.maturity_date <= today + timedelta(days=30), "DUE_0_30"),
        (FDR.maturity_date <= today + timedelta(days=90), "DUE_31_90"),
        (FDR.maturity_date <= today + timedelta(days=365), "DUE_91_365"),
        else_="LATER",
    )
    grouped = {b: (c, s) for b, c, s in db.execute(
        select(bucket, func.count(), func.sum(FDR.amount_paise)).where(*monitored).group_by(bucket)).all()}
    maturity = [
        MaturityBucket(bucket=b, label=label, count=grouped.get(b, (0, 0))[0], total_amount=_money(grouped.get(b, (0, 0))[1]))
        for b, label in BUCKET_LABELS.items()
    ]

    # Per institution, including institutions with no FDRs (outer join).
    is_monitored = (FDR.lifecycle_status == LifecycleStatus.ACTIVE) & (FDR.status != FDRStatus.REJECTED)
    status_columns = [func.sum(case((FDR.status == s, 1), else_=0)).label(s.value) for s in FDRStatus]
    rows = db.execute(
        select(
            Institution,
            func.count(FDR.id),
            func.sum(case((is_monitored, 1), else_=0)),
            func.sum(case((is_monitored, FDR.amount_paise), else_=0)),
            func.sum(case((is_monitored & (FDR.maturity_date >= today) & (FDR.maturity_date <= today + timedelta(days=30)), 1), else_=0)),
            func.sum(case((is_monitored & (FDR.maturity_date < today), 1), else_=0)),
            *status_columns,
        )
        .outerjoin(FDR, FDR.institution_id == Institution.id)
        .group_by(Institution.id)
        .order_by(Institution.code)
    ).all()
    open_requests = dict(db.execute(
        select(LifecycleRequest.institution_id, func.count())
        .where(LifecycleRequest.status.in_(OPEN_STATUSES)).group_by(LifecycleRequest.institution_id)
    ).all())
    institutions = []
    for row in rows:
        inst, total, active, amount, due, overdue = row[:6]
        institutions.append(InstitutionSummary(
            institution=InstitutionBrief.model_validate(inst),
            total_fdrs=total,
            by_status={s.value: int(row[6 + i] or 0) for i, s in enumerate(FDRStatus)},
            active_instruments=int(active or 0),
            active_amount=_money(amount),
            maturing_within_30_days=int(due or 0),
            overdue_active=int(overdue or 0),
            open_lifecycle_requests=open_requests.get(inst.id, 0),
        ))

    return ReportSummary(
        as_of=today,
        generated_at=datetime.now(timezone.utc),
        scope_note=SCOPE_NOTE,
        fdr_total=sum(by_status.values()),
        fdr_by_status=by_status,
        fdr_by_lifecycle=by_lifecycle,
        lifecycle_requests=requests,
        monitored_total=sum(m.count for m in maturity),
        maturity=maturity,
        institutions=institutions,
    )
