"""Password hashing (Argon2id via pwdlib) and signed access tokens (PyJWT)."""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TOKEN_ISSUER = "nidhisec"
TOKEN_TYPE = "access"

_password_hash = PasswordHash.recommended()
# Verified against when the email is unknown so response timing does not reveal
# whether an account exists.
_DUMMY_HASH = _password_hash.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        _password_hash.verify(password, _DUMMY_HASH)
        return False
    return _password_hash.verify(password, password_hash)


class MissingSecretError(RuntimeError):
    pass


@lru_cache
def get_jwt_secret() -> str:
    """Return the token signing key.

    Outside development a configured secret is mandatory. In development, a
    random per-process key is used if none is configured: tokens then stop
    working whenever the server restarts, but no shared default secret exists.
    """
    settings = get_settings()
    if settings.jwt_secret is not None:
        return settings.jwt_secret.get_secret_value()
    if settings.is_development:
        logger.warning(
            "NIDHISEC_JWT_SECRET is not set; using a temporary key. Sessions end on every restart. "
            "Run `python -m app.cli init-env` to create a persistent one."
        )
        return secrets.token_urlsafe(48)
    raise MissingSecretError("NIDHISEC_JWT_SECRET must be set outside development")


def create_access_token(user_id: int) -> tuple[str, datetime]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    claims = {
        "sub": str(user_id),
        "iss": TOKEN_ISSUER,
        "typ": TOKEN_TYPE,
        "iat": now,
        "nbf": now,
        "exp": expires_at,
        "jti": secrets.token_urlsafe(16),
    }
    token = jwt.encode(claims, get_jwt_secret(), algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_access_token(token: str) -> int | None:
    """Return the user id from a valid token, or None if it is invalid or expired."""
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            get_jwt_secret(),
            algorithms=[settings.jwt_algorithm],
            issuer=TOKEN_ISSUER,
            options={"require": ["sub", "exp", "iat", "iss", "typ"]},
        )
    except jwt.PyJWTError:
        return None
    if claims.get("typ") != TOKEN_TYPE:
        return None
    try:
        return int(claims["sub"])
    except (TypeError, ValueError):
        return None
