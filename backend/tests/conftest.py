"""Test configuration.

Environment variables are set before the app is imported so the suite uses a
throwaway SQLite database and a random signing key, never the dev database.
"""

import os
import secrets
import tempfile
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="nidhisec-tests-"))
os.environ["NIDHISEC_DATABASE_URL"] = f"sqlite:///{(_TMP_DIR / 'test.db').as_posix()}"
os.environ["NIDHISEC_ENVIRONMENT"] = "test"
os.environ["NIDHISEC_JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["NIDHISEC_DOCUMENT_STORAGE_DIR"] = (_TMP_DIR / "documents").as_posix()

import shutil  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.login_throttle import login_throttle  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Institution, User, UserRole  # noqa: E402

# Hashing with Argon2 is deliberately slow; hash the shared test password once.
TEST_PASSWORD = "correct-horse-battery-staple"
_TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


@pytest.fixture(autouse=True)
def fresh_database() -> Iterator[None]:
    # Dropping a table runs an implicit DELETE, which RESTRICT foreign keys
    # (e.g. the assignment reassignment chain) would block; this is test-only cleanup.
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(connection)
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
    Base.metadata.create_all(engine)
    login_throttle.reset()
    shutil.rmtree(get_settings().document_storage_path, ignore_errors=True)
    yield
    login_throttle.reset()


@pytest.fixture
def db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_institution(db: Session) -> Callable[..., Institution]:
    counter = iter(range(1, 1000))

    def factory(code: str | None = None, name: str | None = None) -> Institution:
        n = next(counter)
        inst = Institution(code=code or f"TEST-INST-{n:03d}", name=name or f"Test Institution {n}")
        db.add(inst)
        db.commit()
        return inst

    return factory


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    counter = iter(range(1, 1000))

    def factory(role: UserRole, institution: Institution | None = None, *, is_active: bool = True) -> User:
        n = next(counter)
        user = User(
            email=f"user{n}.{role.value.lower()}@example.org",
            full_name=f"Test User {n}",
            role=role,
            institution_id=institution.id if institution else None,
            password_hash=_TEST_PASSWORD_HASH,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        return user

    return factory


def login(client: TestClient, user: User, password: str = TEST_PASSWORD) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": user.email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def actors(make_institution, make_user, client):
    """Two institutions with one user each, a bank officer and an AICTE official, all signed in."""
    inst_a = make_institution(name="Alpha Test Institute")
    inst_b = make_institution(name="Beta Test College")
    users = {
        "inst_a": make_user(UserRole.INSTITUTION, inst_a),
        "inst_b": make_user(UserRole.INSTITUTION, inst_b),
        "bank": make_user(UserRole.BANK_OFFICER),
        "aicte": make_user(UserRole.AICTE_OFFICIAL),
    }

    class Actors:
        institution_a = inst_a
        institution_b = inst_b
        user = users
        headers = {key: login(client, user) for key, user in users.items()}

    return Actors


def fdr_payload(**overrides) -> dict:
    issue = date.today() - timedelta(days=30)
    payload = {
        "bank_name": "Test Demo Bank",
        "branch_name": "Main Branch",
        "ifsc_code": "TEST0000001",
        "fdr_number": "FD-0001",
        "amount": "250000.00",
        "issue_date": issue.isoformat(),
        "maturity_date": (issue + timedelta(days=365)).isoformat(),
        "remarks": "Test record",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def create_fdr(client: TestClient):
    def factory(headers: dict[str, str], **overrides) -> dict:
        response = client.post("/api/fdrs", json=fdr_payload(**overrides), headers=headers)
        assert response.status_code == 201, response.text
        return response.json()

    return factory
