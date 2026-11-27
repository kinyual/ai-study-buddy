"""Tests for authentication endpoints and current-user protection."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Iterator

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.deps import get_db
from backend.app.main import app
from backend.app.models import Base, User
from backend.app.services import token_service
from backend.app.services.password_service import verify_password
from backend.app.services.token_service import create_access_token

TEST_TOKEN_SETTINGS = SimpleNamespace(
    jwt_secret_key="test-only-auth-secret",
    jwt_algorithm="HS256",
    access_token_expire_minutes=60,
)
GENERIC_LOGIN_ERROR = "Incorrect email or password"
CREDENTIALS_ERROR = "Could not validate credentials"


@pytest.fixture
def auth_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, sessionmaker]]:
    """Provide a client backed by a fresh isolated in-memory database."""
    monkeypatch.setattr(token_service, "get_settings", lambda: TEST_TOKEN_SETTINGS)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Iterator[Session]:
        db = test_session_factory()
        try:
            yield db
        finally:
            db.close()

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            yield client, test_session_factory
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _register(client: TestClient, email: str, password: str):
    """Send a registration request."""
    return client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )


def _login(client: TestClient, email: str, password: str):
    """Send a login request."""
    return client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )


def _bearer_headers(token: str) -> dict[str, str]:
    """Build an Authorization header for a bearer token."""
    return {"Authorization": f"Bearer {token}"}


def test_registration_succeeds_without_exposing_credentials(auth_client) -> None:
    client, _ = auth_client

    response = _register(
        client,
        email="  Student@Example.com  ",
        password="test-only-password",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "student@example.com"
    assert isinstance(data["id"], int)
    assert set(data) == {"id", "email"}
    assert "password_hash" not in response.text


def test_invalid_email_is_rejected(auth_client) -> None:
    client, _ = auth_client

    response = _register(
        client,
        email="not-an-email",
        password="test-only-password",
    )

    assert response.status_code == 422


def test_registration_hashes_the_password(auth_client) -> None:
    client, session_factory = auth_client
    password = "plain-text-test-password"

    response = _register(client, email="hash@example.com", password=password)
    assert response.status_code == 201

    with session_factory() as db:
        user = db.execute(
            select(User).where(User.email == "hash@example.com")
        ).scalar_one()
        assert user.password_hash != password
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(password, user.password_hash) is True


def test_duplicate_registration_returns_409(auth_client) -> None:
    client, _ = auth_client

    first_response = _register(
        client,
        email="Duplicate@Example.com",
        password="test-only-password",
    )
    second_response = _register(
        client,
        email="  duplicate@example.com  ",
        password="another-test-password",
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json()["detail"] == "Email is already registered"


def test_login_succeeds_and_returns_a_signed_token(auth_client) -> None:
    client, _ = auth_client
    password = "test-only-password"
    registered = _register(
        client,
        email="login@example.com",
        password=password,
    ).json()

    response = _login(
        client,
        email="  LOGIN@EXAMPLE.COM  ",
        password=password,
    )

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"access_token", "token_type"}
    assert data["token_type"] == "bearer"
    assert "password_hash" not in response.text

    claims = token_service.decode_access_token(data["access_token"])
    assert claims["sub"] == str(registered["id"])


def test_login_rejects_incorrect_password(auth_client) -> None:
    client, _ = auth_client
    _register(
        client,
        email="wrong-password@example.com",
        password="correct-test-password",
    )

    response = _login(
        client,
        email="wrong-password@example.com",
        password="incorrect-test-password",
    )

    assert response.status_code == 401
    assert response.json()["detail"] == GENERIC_LOGIN_ERROR


def test_login_rejects_unknown_email(auth_client) -> None:
    client, _ = auth_client

    response = _login(
        client,
        email="unknown@example.com",
        password="test-only-password",
    )

    assert response.status_code == 401
    assert response.json()["detail"] == GENERIC_LOGIN_ERROR


def test_authenticated_user_can_access_me(auth_client) -> None:
    client, _ = auth_client
    registered = _register(
        client,
        email="me@example.com",
        password="test-only-password",
    ).json()
    token = _login(
        client,
        email="me@example.com",
        password="test-only-password",
    ).json()["access_token"]

    response = client.get("/auth/me", headers=_bearer_headers(token))

    assert response.status_code == 200
    assert response.json() == {
        "id": registered["id"],
        "email": "me@example.com",
    }
    assert "password_hash" not in response.text


def test_me_rejects_missing_token(auth_client) -> None:
    client, _ = auth_client

    response = client.get("/auth/me")

    assert response.status_code == 401


def test_me_rejects_invalid_token(auth_client) -> None:
    client, _ = auth_client

    response = client.get(
        "/auth/me",
        headers=_bearer_headers("not-a-valid-jwt"),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == CREDENTIALS_ERROR


def test_me_rejects_expired_token(auth_client) -> None:
    client, _ = auth_client
    user_id = _register(
        client,
        email="expired@example.com",
        password="test-only-password",
    ).json()["id"]
    now = datetime.now(timezone.utc)
    expired_token = jwt.encode(
        {
            "sub": str(user_id),
            "iat": int((now - timedelta(minutes=10)).timestamp()),
            "exp": int((now - timedelta(minutes=5)).timestamp()),
        },
        TEST_TOKEN_SETTINGS.jwt_secret_key,
        algorithm=TEST_TOKEN_SETTINGS.jwt_algorithm,
    )

    response = client.get("/auth/me", headers=_bearer_headers(expired_token))

    assert response.status_code == 401
    assert response.json()["detail"] == CREDENTIALS_ERROR


def test_me_rejects_unknown_user_id(auth_client) -> None:
    client, _ = auth_client
    token = create_access_token(999_999)

    response = client.get("/auth/me", headers=_bearer_headers(token))

    assert response.status_code == 401
    assert response.json()["detail"] == CREDENTIALS_ERROR
