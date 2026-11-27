"""Unit tests for the JWT token service."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional

import jwt
import pytest

from backend.app.services import token_service
from backend.app.services.token_service import create_access_token, decode_access_token

TEST_TOKEN_SETTINGS = SimpleNamespace(
    jwt_secret_key="test-only-jwt-secret",
    jwt_algorithm="HS256",
    access_token_expire_minutes=60,
)


@pytest.fixture(autouse=True)
def token_settings(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Use fixed test settings instead of any developer's local .env file."""
    monkeypatch.setattr(token_service, "get_settings", lambda: TEST_TOKEN_SETTINGS)
    return TEST_TOKEN_SETTINGS


def _make_test_token(
    payload: dict[str, Any],
    secret: Optional[str] = None,
) -> str:
    """Create a token directly for negative test cases."""
    signing_secret = (
        secret if secret is not None else TEST_TOKEN_SETTINGS.jwt_secret_key
    )

    return jwt.encode(
        payload,
        signing_secret,
        algorithm=TEST_TOKEN_SETTINGS.jwt_algorithm,
    )


def test_token_can_be_created() -> None:
    token = create_access_token(1)

    assert isinstance(token, str)
    assert token


def test_token_contains_expected_claims(
    token_settings: SimpleNamespace,
) -> None:
    token = create_access_token(42)

    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["sub"] == "42"
    assert isinstance(claims["iat"], int)
    assert isinstance(claims["exp"], int)
    assert claims["exp"] - claims["iat"] == (
        token_settings.access_token_expire_minutes * 60
    )


def test_valid_token_can_be_decoded() -> None:
    token = create_access_token(7)

    claims = decode_access_token(token)

    assert claims["sub"] == "7"
    assert "iat" in claims
    assert "exp" in claims


def test_expired_token_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    token = _make_test_token(
        {
            "sub": "9",
            "iat": now - timedelta(minutes=10),
            "exp": now - timedelta(minutes=5),
        }
    )

    with pytest.raises(ValueError):
        decode_access_token(token)


def test_token_signed_with_wrong_secret_is_rejected(
    token_settings: SimpleNamespace,
) -> None:
    now = datetime.now(timezone.utc)
    wrong_secret = token_settings.jwt_secret_key + "-wrong-test-only"
    token = _make_test_token(
        {
            "sub": "10",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        secret=wrong_secret,
    )

    with pytest.raises(ValueError) as exc_info:
        decode_access_token(token)

    assert token_settings.jwt_secret_key not in str(exc_info.value)


def test_malformed_token_is_rejected() -> None:
    with pytest.raises(ValueError):
        decode_access_token("not-a-valid-jwt")
