"""Pydantic schemas for API request and response bodies."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


def _normalize_email(value: object) -> object:
    """Normalize email values before Pydantic validates them."""
    if isinstance(value, str):
        return value.strip().lower()
    return value


class RegisterRequest(BaseModel):
    """Request body for creating a new account."""

    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        """Trim whitespace and lowercase the email before validation."""
        return _normalize_email(value)


class LoginRequest(BaseModel):
    """Request body for logging in."""

    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        """Trim whitespace and lowercase the email before validation."""
        return _normalize_email(value)


class TokenResponse(BaseModel):
    """Access token returned after a successful login."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"


class UserPublic(BaseModel):
    """Public user information; never includes credentials."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
