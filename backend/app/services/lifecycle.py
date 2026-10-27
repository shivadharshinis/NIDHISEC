"""FDR lifecycle: eligibility, request transitions, side effects and maturity checks.

Prototype rules (configurable in settings; not official AICTE policy):
  * Renewal, replacement and release apply only to ACTIVE instruments that AICTE
    has ACCEPTED, with no other open lifecycle request.
  * Renewal may be requested from `renewal_window_days` before maturity onwards.
  * Release requires the FDR to have matured when `release_requires_maturity`.
  * Approval is a decision only. A separate, explicitly recorded completion step
    changes lifecycle status. Completing a renewal/replacement requires the
    successor FDR to be ACCEPTED (after the normal bank verification workflow)
    when `lifecycle_require_successor_acceptance`.
  * Nothing is ever released, refunded, accepted or rejected automatically,
    and no money movement is recorded or implied.

Dates: all "today" comparisons use the Indian Standard Time calendar date,
matching the FDR submission rules.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.models import (
    FDR,
    AssignmentStatus,
    FDRStatus,
    LifecycleRequestStatus,
    LifecycleRequestType,
    LifecycleStatus,
    User,
    UserRole,
)
from app.models.lifecycle import LifecycleRequest, LifecycleRequestEvent
from app.schemas.fdr import today_ist
from app.services import notifications
from app.services.audit import AuditAction, record_audit

S = LifecycleRequestStatus
OPEN_STATUSES = {S.SUBMITTED, S.UNDER_REVIEW, S.CLARIFICATION_REQUESTED, S.APPROVED}
CLOSED_STATUSES = {S.REJECTED, S.WITHDRAWN, S.COMPLETED}
# Lifecycle states in which an FDR can still be edited, reviewed, verified or receive documents.
WORKABLE_LIFECYCLE = {LifecycleStatus.ACTIVE, LifecycleStatus.PROPOSED}

# action -> (allowed roles, from-statuses, to-status)
TRANSITIONS: dict[str, tuple[set[UserRole], set[LifecycleRequestStatus], LifecycleRequestStatus]] = {
    "START_REVIEW": ({UserRole.AICTE_OFFICIAL}, {S.SUBMITTED}, S.UNDER_REVIEW),
    "REQUEST_CLARIFICATION": ({UserRole.AICTE_OFFICIAL}, {S.SUBMITTED, S.UNDER_REVIEW}, S.CLARIFICATION_REQUESTED),
    "APPROVE": ({UserRole.AICTE_OFFICIAL}, {S.SUBMITTED, S.UNDER_REVIEW}, S.APPROVED),
    "REJECT": ({UserRole.AICTE_OFFICIAL}, {S.SUBMITTED, S.UNDER_REVIEW, S.CLARIFICATION_REQUESTED, S.APPROVED}, S.REJECTED),
    "COMPLETE": ({UserRole.AICTE_OFFICIAL}, {S.APPROVED}, S.COMPLETED),
    "RESPOND": ({UserRole.INSTITUTION}, {S.CLARIFICATION_REQUESTED}, S.SUBMITTED),
    "WITHDRAW": ({UserRole.INSTITUTION}, {S.SUBMITTED, S.UNDER_REVIEW, S.CLARIFICATION_REQUESTED}, S.WITHDRAWN),
}
# Actions whose message to the institution is mandatory.
MESSAGE_REQUIRED = {"REQUEST_CLARIFICATION", "REJECT", "RESPOND", "WITHDRAW", "COMPLETE"}

TYPE_LABELS = {
    LifecycleRequestType.RENEWAL: "renewal",
    LifecycleRequestType.REPLACEMENT: "replacement",
    LifecycleRequestType.RELEASE: "release/refund",
}


@dataclass
class Eligibility:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


def open_request(db: Session, fdr_id: int) -> LifecycleRequest | None:
    return db.scalars(
        select(LifecycleRequest).where(LifecycleRequest.fdr_id == fdr_id, LifecycleRequest.status.in_(OPEN_STATUSES))
    ).first()


def eligibility(db: Session, fdr: FDR, request_type: LifecycleRequestType, today: date | None = None) -> Eligibility:
    settings = get_settings()
    today = today or today_ist()
    reasons: list[str] = []
    if fdr.lifecycle_status != LifecycleStatus.ACTIVE:
        reasons.append(f"Only active instruments qualify; this FDR is {fdr.lifecycle_status.value.lower()}.")
    if fdr.status != FDRStatus.ACCEPTED:
        reasons.append("The FDR must first be accepted by AICTE (after bank verification).")
    if open_request(db, fdr.id) is not None:
        reasons.append("Another lifecycle request for this FDR is already open.")
    if request_type == LifecycleRequestType.RENEWAL:
        opens_on = fdr.maturity_date - timedelta(days=settings.renewal_window_days)
        if today < opens_on:
            reasons.append(f"Renewal can be requested from {opens_on.isoformat()} "
                           f"({settings.renewal_window_days} days before maturity).")
    if request_type == LifecycleRequestType.RELEASE and settings.release_requires_maturity and fdr.maturity_date > today:
        reasons.append(f"Release can be requested once the FDR has matured (on or after {fdr.maturity_date.isoformat()}).")
    return Eligibility(not reasons, reasons)


def validate_successor(original: FDR, request_type: LifecycleRequestType, issue_date: date, maturity_date: date) -> list[tuple[str, str]]:
    """Extra rules for a renewal's new instrument (on top of the normal FDR rules)."""
    errors: list[tuple[str, str]] = []
    if request_type == LifecycleRequestType.RENEWAL:
        if maturity_date <= original.maturity_date:
            errors.append(("maturity_date", "A renewal must mature after the current instrument "
                                            f"({original.maturity_date.isoformat()})"))
        if issue_date < original.issue_date:
            errors.append(("issue_date", "A renewal cannot be issued before the current instrument"))
    return errors


def add_event(db: Session, request: LifecycleRequest, actor: User, action: str, from_status: LifecycleRequestStatus | None,
              to_status: LifecycleRequestStatus, message: str | None = None, internal_note: str | None = None) -> LifecycleRequestEvent:
    event = LifecycleRequestEvent(
        request_id=request.id, action=action, from_status=from_status, to_status=to_status, actor_id=actor.id,
        actor_role=actor.role.value, message=message, internal_note=internal_note,
    )
    db.add(event)
    db.flush()
    return event


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def apply_transition(db: Session, request_obj: LifecycleRequest, actor: User, action: str, *, message: str | None,
                     internal_note: str | None, completion_reference: str | None, http_request: Request | None) -> LifecycleRequestEvent:
    """Validate and apply one transition with its side effects, event, audit and notifications.

    Runs inside the caller's transaction; the caller commits.
    """
    from app.services import verification as verification_service  # avoids an import cycle

    roles, from_statuses, to_status = TRANSITIONS[action]
    if actor.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your role cannot perform this action")
    if request_obj.status not in from_statuses:
        raise _conflict(f"Cannot {action.lower().replace('_', ' ')} a request that is {request_obj.status.value}")
    if action in MESSAGE_REQUIRED and not message:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"loc": ["body", "message"], "msg": "A message is required for this action", "type": "value_error"}],
        )

    original = request_obj.fdr
    successor = request_obj.successor
    settings = get_settings()

    if action == "APPROVE":
        if original.lifecycle_status != LifecycleStatus.ACTIVE or original.status != FDRStatus.ACCEPTED:
            raise _conflict("The original FDR is no longer an accepted, active instrument")
        if successor is not None and successor.status == FDRStatus.REJECTED:
            raise _conflict("The proposed new instrument has been rejected; reject this request instead")
    if action == "COMPLETE":
        if original.lifecycle_status != LifecycleStatus.ACTIVE:
            raise _conflict("The original FDR is no longer active")
        if successor is not None:
            if successor.lifecycle_status != LifecycleStatus.PROPOSED:
                raise _conflict("The proposed new instrument is not in the proposed state")
            if settings.lifecycle_require_successor_acceptance and successor.status != FDRStatus.ACCEPTED:
                raise _conflict("The new instrument must be accepted by AICTE (after bank verification) before completion")

    previous = request_obj.status
    request_obj.status = to_status
    now = datetime.now(timezone.utc)
    if action in ("APPROVE", "REJECT"):
        request_obj.decided_at = now
    if action == "COMPLETE":
        request_obj.completed_at = now
        request_obj.completion_reference = completion_reference

    # Side effects on the instruments.
    if to_status in (S.REJECTED, S.WITHDRAWN) and successor is not None:
        successor.lifecycle_status = LifecycleStatus.CANCELLED
        successor.updated_by_id = actor.id
        reason = f"Linked {TYPE_LABELS[request_obj.request_type]} request #{request_obj.id} {to_status.value.lower()}"
        verification_service.end_active_assignment(db, successor, actor, AssignmentStatus.CANCELLED, reason, http_request)
    if to_status == S.COMPLETED:
        if request_obj.request_type == LifecycleRequestType.RELEASE:
            original.lifecycle_status = LifecycleStatus.RELEASED
        else:
            original.lifecycle_status = (LifecycleStatus.RENEWED if request_obj.request_type == LifecycleRequestType.RENEWAL
                                         else LifecycleStatus.REPLACED)
            successor.lifecycle_status = LifecycleStatus.ACTIVE
            successor.updated_by_id = actor.id
        original.updated_by_id = actor.id

    db.flush()
    event = add_event(db, request_obj, actor, action, previous, to_status, message, internal_note)
    label = TYPE_LABELS[request_obj.request_type]
    record_audit(
        db, action=AuditAction.LIFECYCLE_REQUEST_UPDATED, entity_type="fdr", entity_id=original.id,
        institution_id=original.institution_id, actor=actor, request=http_request,
        summary=f"{label.capitalize()} request #{request_obj.id}: {previous.value} -> {to_status.value}",
        changes={"request_id": request_obj.id, "action": action, "from": previous.value, "to": to_status.value,
                 "event_id": event.id, "successor_fdr_id": request_obj.successor_fdr_id,
                 "completion_reference": completion_reference},
    )

    link = f"/lifecycle-requests/{request_obj.id}"
    if actor.role == UserRole.AICTE_OFFICIAL and action != "START_REVIEW":
        title, wording = {
            "REQUEST_CLARIFICATION": (f"Clarification requested on your {label} request", "AICTE requested clarification on"),
            "APPROVE": (f"Your {label} request was approved", "AICTE approved"),
            "REJECT": (f"Your {label} request was rejected", "AICTE rejected"),
            "COMPLETE": (f"Your {label} request was completed", "AICTE recorded completion of"),
        }[action]
        notifications.notify(
            db, notifications.institution_users(db, request_obj.institution_id),
            event_type=f"LIFECYCLE_{to_status.value}", dedup_key=f"lifecycle:{request_obj.id}:event:{event.id}",
            title=title,
            body=f"{wording} your {label} request for FDR {original.fdr_number}. Open the request for details.",
            link=link, fdr_id=original.id,
        )
    if actor.role == UserRole.INSTITUTION:
        notifications.notify(
            db, notifications.aicte_officials(db),
            event_type=f"LIFECYCLE_{action}", dedup_key=f"lifecycle:{request_obj.id}:event:{event.id}",
            title=f"{label.capitalize()} request {'updated' if action == 'RESPOND' else 'withdrawn'}",
            body=(f"{original.institution.code} {'responded to the clarification on' if action == 'RESPOND' else 'withdrew'} "
                  f"its {label} request for FDR {original.fdr_number}."),
            link=link, fdr_id=original.id,
        )
    return event


def allowed_actions(user: User, request_obj: LifecycleRequest) -> list[str]:
    return [action for action, (roles, from_statuses, _) in TRANSITIONS.items()
            if user.role in roles and request_obj.status in from_statuses]


# ---------- maturity ----------


@dataclass
class MaturityState:
    state: str  # "MATURED" | "DUE" | "NOT_DUE"
    days_remaining: int
    window: int | None


def maturity_state(maturity_date: date, today: date, windows: list[int]) -> MaturityState:
    """Smallest alert window that has been reached. A maturity date equal to today is DUE (0 days left)."""
    days = (maturity_date - today).days
    if days < 0:
        return MaturityState("MATURED", days, None)
    reached = [w for w in windows if days <= w]
    return MaturityState("DUE", days, min(reached)) if reached else MaturityState("NOT_DUE", days, None)


def monitored_query():
    """Instruments whose maturity matters: active and not rejected."""
    return select(FDR).where(FDR.lifecycle_status == LifecycleStatus.ACTIVE, FDR.status != FDRStatus.REJECTED)


def run_lifecycle_check(db: Session, actor: User | None, today: date | None = None,
                        http_request: Request | None = None) -> dict[str, int]:
    """Create maturity notifications for the current alert window of each monitored FDR.

    Idempotent: re-running on the same day (or any day within the same window)
    creates nothing new. A new window, a changed maturity date or a new
    instrument produces new alerts. Never changes any FDR.
    """
    settings = get_settings()
    today = today or today_ist()
    windows = settings.maturity_alert_windows
    horizon = today + timedelta(days=max(windows, default=0))
    counts = {"checked": 0, "due": 0, "matured": 0, "skipped": 0, "notifications_created": 0}
    aicte = notifications.aicte_officials(db)

    for fdr in db.scalars(monitored_query().where(FDR.maturity_date <= horizon).options(joinedload(FDR.institution))).unique():
        counts["checked"] += 1
        if fdr.maturity_date is None:  # defensive: legacy/imported data
            counts["skipped"] += 1
            continue
        state = maturity_state(fdr.maturity_date, today, windows)
        institution_users = notifications.institution_users(db, fdr.institution_id)
        link = f"/fdr-records/{fdr.id}"
        if state.state == "MATURED":
            counts["matured"] += 1
            key = f"maturity:{fdr.id}:{fdr.maturity_date.isoformat()}:matured"
            body = (f"FDR {fdr.fdr_number} matured on {fdr.maturity_date.isoformat()}. If the security deposit must stay in "
                    "place, a renewal or replacement may be needed. Nothing has been released automatically.")
            counts["notifications_created"] += notifications.notify(
                db, institution_users, event_type="MATURITY_PASSED", title="FDR has matured", body=body,
                dedup_key=key, link=link, fdr_id=fdr.id)
            counts["notifications_created"] += notifications.notify(
                db, aicte, event_type="MATURITY_PASSED", title=f"Matured FDR at {fdr.institution.code}",
                body=f"FDR {fdr.fdr_number} ({fdr.institution.code}) matured on {fdr.maturity_date.isoformat()}.",
                dedup_key=key, link=link, fdr_id=fdr.id)
        elif state.state == "DUE":
            counts["due"] += 1
            key = f"maturity:{fdr.id}:{fdr.maturity_date.isoformat()}:{state.window}"
            when = "today" if state.days_remaining == 0 else f"in {state.days_remaining} day(s)"
            counts["notifications_created"] += notifications.notify(
                db, institution_users, event_type="MATURITY_DUE", title=f"FDR matures {when}",
                body=f"FDR {fdr.fdr_number} matures on {fdr.maturity_date.isoformat()} ({when}).",
                dedup_key=key, link=link, fdr_id=fdr.id)
            if state.window is not None and state.window <= settings.aicte_maturity_alert_days:
                counts["notifications_created"] += notifications.notify(
                    db, aicte, event_type="MATURITY_DUE", title=f"FDR at {fdr.institution.code} matures {when}",
                    body=f"FDR {fdr.fdr_number} ({fdr.institution.code}) matures on {fdr.maturity_date.isoformat()}.",
                    dedup_key=key, link=link, fdr_id=fdr.id)

    record_audit(
        db, action=AuditAction.LIFECYCLE_CHECK_RUN, entity_type="lifecycle_check", actor=actor,
        actor_email=None if actor else "system:lifecycle-check", request=http_request,
        summary=(f"Maturity check for {today.isoformat()}: {counts['due']} due, {counts['matured']} matured, "
                 f"{counts['notifications_created']} new notification(s)"),
        changes={**counts, "date": today.isoformat(), "windows": windows},
    )
    db.commit()
    return counts
