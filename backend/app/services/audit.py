"""Audit trail helpers. Entries are added to the caller's transaction, so an
action and its audit record are committed (or rolled back) together."""

from enum import StrEnum
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User


class AuditAction(StrEnum):
    LOGIN_SUCCEEDED = "LOGIN_SUCCEEDED"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGIN_THROTTLED = "LOGIN_THROTTLED"
    FDR_CREATED = "FDR_CREATED"
    FDR_UPDATED = "FDR_UPDATED"
    FDR_STATUS_CHANGED = "FDR_STATUS_CHANGED"
    FDR_DUPLICATE_FLAGGED = "FDR_DUPLICATE_FLAGGED"
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    DOCUMENT_UPLOAD_REJECTED = "DOCUMENT_UPLOAD_REJECTED"
    DOCUMENT_DOWNLOADED = "DOCUMENT_DOWNLOADED"
    DOCUMENT_WITHDRAWN = "DOCUMENT_WITHDRAWN"
    DOCUMENT_INTEGRITY_CHECKED = "DOCUMENT_INTEGRITY_CHECKED"
    DOCUMENT_INTEGRITY_FAILED = "DOCUMENT_INTEGRITY_FAILED"
    VERIFICATION_ASSIGNED = "VERIFICATION_ASSIGNED"
    VERIFICATION_REASSIGNED = "VERIFICATION_REASSIGNED"
    VERIFICATION_CANCELLED = "VERIFICATION_CANCELLED"
    VERIFICATION_OUTCOME_SUBMITTED = "VERIFICATION_OUTCOME_SUBMITTED"
    VERIFICATION_ACCESS_DENIED = "VERIFICATION_ACCESS_DENIED"
    SCREENING_RUN_COMPLETED = "SCREENING_RUN_COMPLETED"
    SCREENING_RUN_FAILED = "SCREENING_RUN_FAILED"
    SCREENING_FINDING_REVIEWED = "SCREENING_FINDING_REVIEWED"
    SCREENING_ACCESS_DENIED = "SCREENING_ACCESS_DENIED"
    LIFECYCLE_REQUEST_SUBMITTED = "LIFECYCLE_REQUEST_SUBMITTED"
    LIFECYCLE_REQUEST_UPDATED = "LIFECYCLE_REQUEST_UPDATED"
    LIFECYCLE_CHECK_RUN = "LIFECYCLE_CHECK_RUN"
    LIFECYCLE_ACCESS_DENIED = "LIFECYCLE_ACCESS_DENIED"


def client_ip(request: Request | None) -> str | None:
    return request.client.host if request is not None and request.client is not None else None


def record_audit(
    db: Session,
    *,
    action: AuditAction,
    entity_type: str,
    summary: str,
    actor: User | None = None,
    actor_email: str | None = None,
    entity_id: int | None = None,
    institution_id: int | None = None,
    changes: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else actor_email,
        actor_name=actor.full_name if actor else None,
        actor_role=actor.role.value if actor else None,
        action=action.value,
        entity_type=entity_type,
        entity_id=entity_id,
        institution_id=institution_id,
        summary=summary[:500],
        changes=changes,
        ip_address=client_ip(request),
    )
    db.add(entry)
    return entry
