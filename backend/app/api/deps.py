"""Shared FastAPI dependencies: database session, current user, role checks."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{get_settings().api_prefix}/auth/token", auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(db: DbSession, token: Annotated[str | None, Depends(oauth2_scheme)]) -> User:
    if not token:
        raise _unauthorized()
    user_id = decode_access_token(token)
    if user_id is None:
        raise _unauthorized("Session is invalid or has expired")
    # Role and active status are always read from the database, never the token.
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("Session is invalid or has expired")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your role does not permit this action")
        return user

    return checker
