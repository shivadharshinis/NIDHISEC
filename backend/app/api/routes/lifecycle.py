"""Lifecycle requests (renewal, replacement, release/refund) and maturity tracking.

Institutions request changes for their own accepted instruments; AICTE
officials review, decide and separately record completion. Bank officers have
no access (refused and audited). See app/services/lifecycle.py for the rules.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.models import FDR, FDRStatus, LifecycleRequestStatus, LifecycleRequestType, LifecycleStatus, User, UserRole
from app.models.lifecycle import LifecycleRequest
from app.schemas.common import InstitutionBrief, Page
from app.schemas.fdr import today_ist
from app.schemas.lifecycle import (
    EligibilityRead,
    FDRBrief,
    FDRLifecycle,
    LifecycleCheckResult,
    LifecycleEventRead,
    LifecycleRequestCreate,
    LifecycleRequestDetail,
    LifecycleRequestRead,
    LifecycleTransition,
    MaturityItem,
)
from app.services import fdrs as fdr_service
from app.services import lifecycle as lifecycle_service
from app.services import notifications
from app.services.audit import AuditAction, record_audit

router = APIRouter(tags=["lifecycle"])


def require_lifecycle_access(request: Request, user: CurrentUser, db: DbSession) -> User:
    if user.role not in (UserRole.INSTITUTION, UserRole.AICTE_OFFICIAL):
        fdr_id = request.path_params.get("fdr_id")
        record_audit(
            db, action=AuditAction.LIFECYCLE_ACCESS_DENIED,
            entity_type="fdr" if fdr_id else "lifecycle",
            entity_id=int(fdr_id) if fdr_id and str(fdr_id).isdigit() else None,
            actor=user, request=request,
            summary=f"Lifecycle access denied ({request.method} {request.url.path})",
            changes={"role": user.role.value},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Lifecycle requests are available to institutions and AICTE officials only")
    return user


LifecycleUser = Annotated[User, Depends(require_lifecycle_access)]


# ---------- serialisation ----------


def _fdr_brief(fdr: FDR) -> FDRBrief:
    return FDRBrief(id=fdr.id, fdr_number=fdr.fdr_number, bank_name=fdr.bank_name, amount=fdr.amount,
                    issue_date=fdr.issue_date, maturity_date=fdr.maturity_date, status=fdr.status,
                    lifecycle_status=fdr.lifecycle_status)


def _request_read(req: LifecycleRequest) -> LifecycleRequestRead:
    return LifecycleRequestRead(
        id=req.id, request_type=req.request_type, status=req.status,
        institution=InstitutionBrief.model_validate(req.fdr.institution), fdr=_fdr_brief(req.fdr),
        successor=_fdr_brief(req.successor) if req.successor else None, reason=req.reason,
        supporting_note=req.supporting_note, created_by_name=req.created_by.full_name, created_at=req.created_at,
        updated_at=req.updated_at, decided_at=req.decided_at, completed_at=req.completed_at,
        completion_reference=req.completion_reference, version=req.version,
    )


def _completion_blockers(req: LifecycleRequest) -> list[str]:
    blockers: list[str] = []
    if req.fdr.lifecycle_status != LifecycleStatus.ACTIVE:
        blockers.append("The original FDR is no longer active.")
    if req.successor is not None and get_settings().lifecycle_require_successor_acceptance \
            and req.successor.status != FDRStatus.ACCEPTED:
        blockers.append("The new instrument must be accepted by AICTE after bank verification before completion.")
    return blockers


def _request_detail(req: LifecycleRequest, user: User) -> LifecycleRequestDetail:
    is_aicte = user.role == UserRole.AICTE_OFFICIAL
    return LifecycleRequestDetail(
        **_request_read(req).model_dump(),
        events=[
            LifecycleEventRead(
                id=e.id, action=e.action, from_status=e.from_status, to_status=e.to_status,
                actor_name=e.actor.full_name, actor_role=e.actor_role, message=e.message,
                internal_note=e.internal_note if is_aicte else None, created_at=e.created_at,
            )
            for e in req.events
        ],
        allowed_actions=lifecycle_service.allowed_actions(user, req),
        completion_blockers=_completion_blockers(req) if is_aicte and req.status == LifecycleRequestStatus.APPROVED else [],
    )


def _load_request(db: Session, user: User, request_id: int) -> LifecycleRequest:
    req = db.scalars(
        select(LifecycleRequest).where(LifecycleRequest.id == request_id)
        .options(joinedload(LifecycleRequest.fdr).joinedload(FDR.institution), joinedload(LifecycleRequest.successor),
                 joinedload(LifecycleRequest.created_by))
    ).unique().one_or_none()
    # Other institutions' requests are "not found", so their existence is not disclosed.
    if req is None or (user.role == UserRole.INSTITUTION and req.institution_id != user.institution_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lifecycle request not found")
    return req


def _scoped_requests(user: User):
    query = select(LifecycleRequest)
    if user.role == UserRole.INSTITUTION:
        query = query.where(LifecycleRequest.institution_id == user.institution_id)
    return query


# ---------- per-FDR lifecycle ----------


@router.get("/fdrs/{fdr_id}/lifecycle", response_model=FDRLifecycle)
def fdr_lifecycle(fdr_id: int, user: LifecycleUser, db: DbSession) -> FDRLifecycle:
    fdr = fdr_service.get_fdr_for_user(db, user, fdr_id)
    settings = get_settings()
    requests = db.scalars(
        select(LifecycleRequest).where(or_(LifecycleRequest.fdr_id == fdr.id, LifecycleRequest.successor_fdr_id == fdr.id))
        .order_by(LifecycleRequest.id.desc())
    ).all()
    proposed_by = next((r for r in requests if r.successor_fdr_id == fdr.id), None)
    return FDRLifecycle(
        fdr_id=fdr.id, fdr_version=fdr.version, lifecycle_status=fdr.lifecycle_status, maturity_date=fdr.maturity_date,
        days_to_maturity=(fdr.maturity_date - today_ist()).days,
        eligibility={t: EligibilityRead(**vars(lifecycle_service.eligibility(db, fdr, t))) for t in LifecycleRequestType},
        requests=[_request_read(r) for r in requests if r.fdr_id == fdr.id],
        proposed_by_request=_request_read(proposed_by) if proposed_by else None,
        rules={"renewal_window_days": settings.renewal_window_days,
               "release_requires_maturity": settings.release_requires_maturity,
               "successor_acceptance_required": settings.lifecycle_require_successor_acceptance},
    )


@router.post("/fdrs/{fdr_id}/lifecycle-requests", response_model=LifecycleRequestDetail, status_code=status.HTTP_201_CREATED)
def create_request(fdr_id: int, payload: LifecycleRequestCreate, request: Request, user: LifecycleUser,
                   db: DbSession) -> LifecycleRequestDetail:
    """Request renewal, replacement or release of one of the institution's own FDRs.

    The original FDR is never modified. For renewal/replacement the new
    instrument is created as a separate PROPOSED FDR, which goes through the
    normal document, screening and bank verification workflows.
    """
    if user.role != UserRole.INSTITUTION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only institutions can submit lifecycle requests")
    fdr = fdr_service.get_fdr_for_user(db, user, fdr_id)
    if fdr.version != payload.fdr_version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This record was changed by someone else. Reload it and try again.")
    check = lifecycle_service.eligibility(db, fdr, payload.request_type)
    if not check.allowed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=" ".join(check.reasons))

    successor = None
    if payload.successor is not None:
        errors = lifecycle_service.validate_successor(
            fdr, payload.request_type, payload.successor.issue_date, payload.successor.maturity_date)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[{"loc": ["body", "successor", field], "msg": message, "type": "value_error"}
                        for field, message in errors],
            )
        successor = fdr_service.create_fdr_record(db, user, payload.successor, request,
                                                  lifecycle_status=LifecycleStatus.PROPOSED)

    req = LifecycleRequest(
        request_type=payload.request_type, fdr_id=fdr.id, institution_id=fdr.institution_id,
        successor_fdr_id=successor.id if successor else None, status=LifecycleRequestStatus.SUBMITTED,
        reason=payload.reason, supporting_note=payload.supporting_note or None, created_by_id=user.id,
    )
    db.add(req)
    db.flush()  # the open-request unique index rejects a concurrent second request here
    lifecycle_service.add_event(db, req, user, "SUBMIT", None, LifecycleRequestStatus.SUBMITTED, payload.reason)
    label = lifecycle_service.TYPE_LABELS[payload.request_type]
    record_audit(
        db, action=AuditAction.LIFECYCLE_REQUEST_SUBMITTED, entity_type="fdr", entity_id=fdr.id,
        institution_id=fdr.institution_id, actor=user, request=request,
        summary=f"{label.capitalize()} request #{req.id} submitted",
        changes={"request_id": req.id, "request_type": payload.request_type.value,
                 "successor_fdr_id": successor.id if successor else None},
    )
    notifications.notify(
        db, notifications.aicte_officials(db), event_type="LIFECYCLE_SUBMITTED",
        dedup_key=f"lifecycle:{req.id}:submitted", title=f"New {label} request",
        body=f"{fdr.institution.code} submitted a {label} request for FDR {fdr.fdr_number}.",
        link=f"/lifecycle-requests/{req.id}", fdr_id=fdr.id,
    )
    db.commit()
    return _request_detail(_load_request(db, user, req.id), user)


# ---------- requests ----------


@router.get("/lifecycle-requests", response_model=Page[LifecycleRequestRead])
def list_requests(
    user: LifecycleUser,
    db: DbSession,
    request_type: Annotated[list[LifecycleRequestType] | None, Query(alias="type")] = None,
    status_filter: Annotated[list[LifecycleRequestStatus] | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[LifecycleRequestRead]:
    query = _scoped_requests(user)
    if request_type:
        query = query.where(LifecycleRequest.request_type.in_(request_type))
    if status_filter:
        query = query.where(LifecycleRequest.status.in_(status_filter))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.options(joinedload(LifecycleRequest.fdr).joinedload(FDR.institution), joinedload(LifecycleRequest.successor),
                      joinedload(LifecycleRequest.created_by))
        .order_by(LifecycleRequest.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).unique().all()
    return Page[LifecycleRequestRead](items=[_request_read(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/lifecycle-requests/{request_id}", response_model=LifecycleRequestDetail)
def get_request(request_id: int, user: LifecycleUser, db: DbSession) -> LifecycleRequestDetail:
    return _request_detail(_load_request(db, user, request_id), user)


@router.post("/lifecycle-requests/{request_id}/transitions", response_model=LifecycleRequestDetail)
def transition(request_id: int, payload: LifecycleTransition, request: Request, user: LifecycleUser,
               db: DbSession) -> LifecycleRequestDetail:
    """Move a request through its workflow. Every step is recorded; nothing is overwritten."""
    req = _load_request(db, user, request_id)
    if req.version != payload.version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This request was changed by someone else. Reload it and try again.")
    internal_note = payload.internal_note if user.role == UserRole.AICTE_OFFICIAL else None
    if user.role != UserRole.AICTE_OFFICIAL and payload.internal_note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"loc": ["body", "internal_note"], "msg": "Only AICTE officials can add internal notes", "type": "value_error"}],
        )
    lifecycle_service.apply_transition(
        db, req, user, payload.action, message=payload.message, internal_note=internal_note,
        completion_reference=payload.completion_reference if payload.action == "COMPLETE" else None,
        http_request=request,
    )
    db.commit()
    db.expire_all()
    return _request_detail(_load_request(db, user, request_id), user)


# ---------- maturity ----------


@router.get("/lifecycle/maturity", response_model=Page[MaturityItem])
def maturity_list(
    user: LifecycleUser,
    db: DbSession,
    within_days: Annotated[int, Query(ge=0, le=3650)] = 30,
    include_overdue: bool = True,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[MaturityItem]:
    """Active instruments maturing within `within_days` (and, optionally, already matured). Computed live."""
    today = today_ist()
    windows = get_settings().maturity_alert_windows
    query = (fdr_service.scoped_fdr_query(user)
             .where(FDR.lifecycle_status == LifecycleStatus.ACTIVE, FDR.status != FDRStatus.REJECTED,
                    FDR.maturity_date <= today + timedelta(days=within_days)))
    if not include_overdue:
        query = query.where(FDR.maturity_date >= today)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.options(joinedload(FDR.institution)).order_by(FDR.maturity_date, FDR.id)
                      .offset((page - 1) * page_size).limit(page_size)).unique().all()
    open_types = dict(db.execute(
        select(LifecycleRequest.fdr_id, LifecycleRequest.request_type)
        .where(LifecycleRequest.fdr_id.in_([f.id for f in rows]),
               LifecycleRequest.status.in_(lifecycle_service.OPEN_STATUSES))
    ).all())
    items = []
    for fdr in rows:
        state = lifecycle_service.maturity_state(fdr.maturity_date, today, windows)
        items.append(MaturityItem(
            fdr_id=fdr.id, fdr_number=fdr.fdr_number, bank_name=fdr.bank_name,
            institution=InstitutionBrief.model_validate(fdr.institution), status=fdr.status,
            lifecycle_status=fdr.lifecycle_status, maturity_date=fdr.maturity_date,
            days_remaining=state.days_remaining, state=state.state, alert_window=state.window,
            open_request_type=open_types.get(fdr.id),
        ))
    return Page[MaturityItem](items=items, total=total, page=page, page_size=page_size)


@router.post("/lifecycle/check", response_model=LifecycleCheckResult)
def run_check(request: Request, user: LifecycleUser, db: DbSession) -> LifecycleCheckResult:
    """Run the maturity check now (AICTE). Safe to repeat: it never creates duplicate alerts."""
    if user.role != UserRole.AICTE_OFFICIAL:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only AICTE officials can run the maturity check")
    today = today_ist()
    counts = lifecycle_service.run_lifecycle_check(db, user, today=today, http_request=request)
    return LifecycleCheckResult(**counts, date=today)
