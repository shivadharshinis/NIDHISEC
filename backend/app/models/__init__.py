"""ORM models.

Every model module is imported here so that `Base.metadata` (used by Alembic
autogenerate and by the test suite) knows about all tables.
"""

from app.db.base import Base
from app.models.audit_log import AuditLog
from app.models.enums import (
    AssignmentStatus,
    DocumentType,
    FDRStatus,
    LifecycleRequestStatus,
    LifecycleRequestType,
    LifecycleStatus,
    UserRole,
    VerificationOutcomeType,
)
from app.models.fdr import FDR, FDRDocument
from app.models.institution import Institution
from app.models.lifecycle import LifecycleRequest, LifecycleRequestEvent, Notification
from app.models.screening import ScreeningFinding, ScreeningReview, ScreeningRun
from app.models.user import User
from app.models.verification import ReviewDecision, VerificationAssignment, VerificationOutcome

__all__ = [
    "Base",
    "AssignmentStatus",
    "AuditLog",
    "DocumentType",
    "FDR",
    "FDRDocument",
    "FDRStatus",
    "Institution",
    "LifecycleRequest",
    "LifecycleRequestEvent",
    "LifecycleRequestStatus",
    "LifecycleRequestType",
    "LifecycleStatus",
    "Notification",
    "ReviewDecision",
    "ScreeningFinding",
    "ScreeningReview",
    "ScreeningRun",
    "User",
    "UserRole",
    "VerificationAssignment",
    "VerificationOutcome",
    "VerificationOutcomeType",
]
