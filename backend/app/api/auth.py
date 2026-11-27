"""Authentication endpoints for registration, login, and current user lookup."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User
from ..schemas import LoginRequest, RegisterRequest, TokenResponse, UserPublic
from ..services.password_service import hash_password, verify_password
from ..services.token_service import create_access_token
from .deps import get_current_user, get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _normalize_email(email: str) -> str:
    """Store and compare email addresses in one consistent format."""
    return email.strip().lower()


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> User:
    """Create a new user with a hashed password."""
    email = _normalize_email(payload.email)

    existing_user = db.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login_user(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Verify credentials and return an access token."""
    email = _normalize_email(payload.email)

    user = db.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    return TokenResponse(
        access_token=create_access_token(user.id),
        token_type="bearer",
    )


@router.get("/me", response_model=UserPublic)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    """Return public information for the authenticated user."""
    return current_user
