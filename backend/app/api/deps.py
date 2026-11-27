"""Reusable FastAPI dependencies."""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..services.token_service import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _credentials_exception() -> HTTPException:
    """Return a generic authentication error without sensitive details."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Return the user identified by a valid bearer token."""
    try:
        claims = decode_access_token(token)
    except ValueError:
        raise _credentials_exception() from None

    raw_user_id = claims.get("sub")
    if not isinstance(raw_user_id, str) or not raw_user_id.isdecimal():
        raise _credentials_exception()

    user_id = int(raw_user_id)
    if user_id <= 0:
        raise _credentials_exception()

    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None:
        raise _credentials_exception()

    return user


__all__ = ["get_current_user", "get_db"]
