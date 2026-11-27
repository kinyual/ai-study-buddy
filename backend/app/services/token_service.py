"""JWT access token creation and verification."""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from ..config import get_settings

REQUIRED_CLAIMS = ("sub", "iat", "exp")


def create_access_token(user_id: int) -> str:
    """Create a signed access token for a user id."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": expires_at,
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate an access token, returning its claims."""
    settings = get_settings()

    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": list(REQUIRED_CLAIMS)},
        )
    except jwt.PyJWTError:
        # Keep errors generic so secrets and token details are not exposed.
        raise ValueError("Invalid or expired token") from None

    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise ValueError("Invalid or expired token")

    return claims
