from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select

from app.core.security import TOKEN_ISSUER, create_access_token, get_jwt_secret
from app.models import AuditLog, UserRole
from tests.conftest import TEST_PASSWORD, login


def test_login_success_returns_token_and_safe_user(client, make_institution, make_user, db):
    inst = make_institution()
    user = make_user(UserRole.INSTITUTION, inst)

    response = client.post("/api/auth/login", json={"email": user.email.upper(), "password": TEST_PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == user.email
    assert body["user"]["role"] == "INSTITUTION"
    assert body["user"]["institution"]["id"] == inst.id
    assert "password" not in response.text.lower()
    assert "argon2" not in response.text

    audit = db.scalars(select(AuditLog).where(AuditLog.action == "LOGIN_SUCCEEDED")).one()
    assert audit.actor_user_id == user.id


def test_me_returns_current_user(client, make_user):
    user = make_user(UserRole.AICTE_OFFICIAL)
    response = client.get("/api/auth/me", headers=login(client, user))
    assert response.status_code == 200
    assert response.json()["id"] == user.id
    assert "password_hash" not in response.json()


def test_wrong_password_and_unknown_email_get_same_401(client, make_user, db):
    user = make_user(UserRole.AICTE_OFFICIAL)

    wrong = client.post("/api/auth/login", json={"email": user.email, "password": "not-the-password"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.org", "password": "whatever"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Incorrect email or password"}
    assert len(db.scalars(select(AuditLog).where(AuditLog.action == "LOGIN_FAILED")).all()) == 2


def test_inactive_user_cannot_log_in(client, make_user):
    user = make_user(UserRole.AICTE_OFFICIAL, is_active=False)
    response = client.post("/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 401


def test_deactivated_user_token_stops_working(client, make_user, db):
    user = make_user(UserRole.AICTE_OFFICIAL)
    headers = login(client, user)
    user.is_active = False
    db.commit()
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_missing_and_malformed_tokens_are_rejected(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
    assert client.get("/api/fdrs").status_code == 401


def test_expired_token_is_rejected(client, make_user):
    user = make_user(UserRole.AICTE_OFFICIAL)
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    token = jwt.encode(
        {"sub": str(user.id), "iss": TOKEN_ISSUER, "typ": "access", "iat": past, "exp": past + timedelta(minutes=5)},
        get_jwt_secret(),
        algorithm="HS256",
    )
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_token_signed_with_other_key_is_rejected(client, make_user):
    user = make_user(UserRole.AICTE_OFFICIAL)
    now = datetime.now(timezone.utc)
    forged = jwt.encode(
        {"sub": str(user.id), "iss": TOKEN_ISSUER, "typ": "access", "iat": now, "exp": now + timedelta(hours=1)},
        "an-attacker-chosen-secret-that-is-long-enough",
        algorithm="HS256",
    )
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_unsigned_token_is_rejected(client, make_user):
    user = make_user(UserRole.AICTE_OFFICIAL)
    now = datetime.now(timezone.utc)
    unsigned = jwt.encode(
        {"sub": str(user.id), "iss": TOKEN_ISSUER, "typ": "access", "iat": now, "exp": now + timedelta(hours=1)},
        None,
        algorithm="none",
    )
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {unsigned}"}).status_code == 401


def test_valid_token_works(client, make_user):
    user = make_user(UserRole.BANK_OFFICER)
    token, expires_at = create_access_token(user.id)
    assert expires_at > datetime.now(timezone.utc)
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_repeated_failures_are_throttled(client, make_user, db):
    user = make_user(UserRole.AICTE_OFFICIAL)
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": user.email, "password": "wrong"}).status_code == 401

    blocked = client.post("/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert db.scalars(select(AuditLog).where(AuditLog.action == "LOGIN_THROTTLED")).first() is not None


def test_swagger_form_login(client, make_user):
    user = make_user(UserRole.AICTE_OFFICIAL)
    response = client.post("/api/auth/token", data={"username": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 200
    assert response.json()["access_token"]
