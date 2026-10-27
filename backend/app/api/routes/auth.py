from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.login_throttle import login_throttle
from app.core.security import create_access_token, verify_password
from app.models import User
from app.schemas.auth import LoginRequest, TokenResponse, UserRead
from app.services.audit import AuditAction, record_audit

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS = "Incorrect email or password"


def _authenticate(db: DbSession, request: Request, email: str, password: str) -> TokenResponse:
    settings = get_settings()
    email = email.strip().lower()
    window = settings.login_lockout_minutes * 60

    retry_after = login_throttle.retry_after(email, settings.login_max_failures, window)
    if retry_after:
        record_audit(
            db,
            action=AuditAction.LOGIN_THROTTLED,
            entity_type="user",
            actor_email=email,
            summary="Login blocked after repeated failed attempts",
            request=request,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.scalars(select(User).where(User.email == email)).one_or_none()
    # Always run a hash verification so timing does not reveal unknown emails.
    password_ok = verify_password(password, user.password_hash if user else None)

    if user is None or not password_ok or not user.is_active:
        login_throttle.record_failure(email, window)
        record_audit(
            db,
            action=AuditAction.LOGIN_FAILED,
            entity_type="user",
            entity_id=user.id if user else None,
            actor_email=email,
            summary="Failed login attempt" if user is None or not password_ok else "Login attempt on inactive account",
            request=request,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )

    login_throttle.reset(email)
    user.last_login_at = datetime.now(timezone.utc)
    record_audit(
        db,
        action=AuditAction.LOGIN_SUCCEEDED,
        entity_type="user",
        entity_id=user.id,
        actor=user,
        institution_id=user.institution_id,
        summary="User signed in",
        request=request,
    )
    db.commit()

    token, expires_at = create_access_token(user.id)
    return TokenResponse(access_token=token, expires_at=expires_at, user=UserRead.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: DbSession) -> TokenResponse:
    """Exchange email and password for a signed, expiring bearer token."""
    return _authenticate(db, request, payload.email, payload.password)


@router.post("/token", response_model=TokenResponse, include_in_schema=True)
def login_form(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, db: DbSession
) -> TokenResponse:
    """OAuth2 password-form variant of /login, used by the Swagger UI "Authorize" button.
    Enter the email address in the username field."""
    return _authenticate(db, request, form.username, form.password)


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser) -> User:
    return user
