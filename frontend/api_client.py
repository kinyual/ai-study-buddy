"""HTTP client for AI Study Buddy authentication endpoints."""

import os
from typing import Any, Optional

import httpx

DEFAULT_BACKEND_BASE_URL = "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 10.0

REGISTER_STATUS_MESSAGES = {
    409: "That email is already registered. Try logging in or use another email.",
    422: "Please enter a valid email address and password.",
}

LOGIN_STATUS_MESSAGES = {
    401: "Incorrect email or password.",
    422: "Please enter a valid email address and password.",
}

CURRENT_USER_STATUS_MESSAGES = {
    401: "Your session has expired or is invalid. Please log in again.",
}


class ApiError(Exception):
    """A friendly error message that is safe to display in the UI."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _base_url() -> str:
    """Return the backend URL without a trailing slash."""
    return os.getenv("BACKEND_BASE_URL", DEFAULT_BACKEND_BASE_URL).rstrip("/")


def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    """Make one short HTTP request and convert connection errors safely."""
    url = f"{_base_url()}{path}"

    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            return client.request(method, url, **kwargs)
    except httpx.TimeoutException:
        raise ApiError(
            "The backend did not respond in time. Please try again."
        ) from None
    except httpx.ConnectError:
        raise ApiError(
            "Cannot connect to the backend. Please check that it is running."
        ) from None
    except httpx.RequestError:
        raise ApiError("Could not reach the backend. Please try again.") from None


def _json_object(response: httpx.Response) -> dict[str, Any]:
    """Return a JSON object or raise a friendly error."""
    try:
        data = response.json()
    except ValueError:
        raise ApiError("The backend returned an unexpected response.") from None

    if not isinstance(data, dict):
        raise ApiError("The backend returned an unexpected response.")

    return data


def _raise_status_error(
    response: httpx.Response,
    friendly_messages: dict[int, str],
) -> None:
    """Raise a friendly error for an unsuccessful response."""
    message = friendly_messages.get(response.status_code)

    if message is None:
        if 400 <= response.status_code < 500:
            message = "Please check your details and try again."
        else:
            message = "The backend had a problem. Please try again later."

    raise ApiError(message, response.status_code)


def register_user(email: str, password: str) -> dict[str, Any]:
    """Create an account through POST /auth/register."""
    response = _request(
        "POST",
        "/auth/register",
        json={"email": email, "password": password},
    )

    if response.status_code != 201:
        _raise_status_error(response, REGISTER_STATUS_MESSAGES)

    data = _json_object(response)
    if not isinstance(data.get("id"), int) or not isinstance(data.get("email"), str):
        raise ApiError("The registration response was unexpected. Please try again.")

    return data


def login_user(email: str, password: str) -> dict[str, Any]:
    """Log in through POST /auth/login and return the token response."""
    response = _request(
        "POST",
        "/auth/login",
        json={"email": email, "password": password},
    )

    if response.status_code != 200:
        _raise_status_error(response, LOGIN_STATUS_MESSAGES)

    data = _json_object(response)
    token = data.get("access_token")
    token_type = data.get("token_type")

    if not isinstance(token, str) or not token or token_type != "bearer":
        raise ApiError("The login response was unexpected. Please try again.")

    return data


def get_current_user(token: str) -> dict[str, Any]:
    """Get public user information through GET /auth/me using a bearer token."""
    response = _request(
        "GET",
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    if response.status_code != 200:
        _raise_status_error(response, CURRENT_USER_STATUS_MESSAGES)

    data = _json_object(response)
    if not isinstance(data.get("id"), int) or not isinstance(data.get("email"), str):
        raise ApiError("The user response was unexpected. Please try again.")

    return data
