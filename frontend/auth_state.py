"""Streamlit session-state helpers for authentication."""

from typing import Any, Optional

import streamlit as st

from api_client import ApiError, get_current_user as fetch_current_user

ACCESS_TOKEN_KEY = "auth_access_token"
CURRENT_USER_KEY = "auth_current_user"
AUTH_STATUS_KEY = "auth_status"
AUTH_ERROR_KEY = "auth_error"

STATUS_ANONYMOUS = "anonymous"
STATUS_VALID = "valid"
STATUS_ERROR = "error"

AUTH_KEYS = (
    ACCESS_TOKEN_KEY,
    CURRENT_USER_KEY,
    AUTH_STATUS_KEY,
    AUTH_ERROR_KEY,
)

_DEFAULTS: dict[str, Any] = {
    ACCESS_TOKEN_KEY: None,
    CURRENT_USER_KEY: None,
    AUTH_STATUS_KEY: STATUS_ANONYMOUS,
    AUTH_ERROR_KEY: None,
}


def initialize_auth_state() -> None:
    """Create authentication keys with safe defaults if needed."""
    for key, value in _DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_auth_session() -> None:
    """Clear local auth state. This does not revoke the JWT on the backend."""
    for key in AUTH_KEYS:
        st.session_state.pop(key, None)
    initialize_auth_state()


def set_authenticated(token: str, user: dict[str, Any]) -> None:
    """Store the active session token and public user information."""
    initialize_auth_state()
    st.session_state[ACCESS_TOKEN_KEY] = token
    st.session_state[CURRENT_USER_KEY] = user
    st.session_state[AUTH_STATUS_KEY] = STATUS_VALID
    st.session_state[AUTH_ERROR_KEY] = None


def get_access_token() -> Optional[str]:
    """Return the active token, if one is stored for this session."""
    initialize_auth_state()
    token = st.session_state[ACCESS_TOKEN_KEY]
    return token if isinstance(token, str) and token else None


def get_current_user() -> Optional[dict[str, Any]]:
    """Return the stored public user information, if present."""
    initialize_auth_state()
    user = st.session_state[CURRENT_USER_KEY]
    return user if isinstance(user, dict) else None


def has_access_token() -> bool:
    """Report whether this session has a stored token."""
    return get_access_token() is not None


def is_authenticated() -> bool:
    """Report whether this session has a validated token and user."""
    initialize_auth_state()
    return (
        get_access_token() is not None
        and st.session_state[AUTH_STATUS_KEY] == STATUS_VALID
        and get_current_user() is not None
    )


def get_auth_error() -> Optional[str]:
    """Return a saved authentication error message, if present."""
    initialize_auth_state()
    error = st.session_state[AUTH_ERROR_KEY]
    return error if isinstance(error, str) and error else None


def clear_auth_error() -> None:
    """Clear any saved authentication error before a new form attempt."""
    initialize_auth_state()
    st.session_state[AUTH_ERROR_KEY] = None


def get_auth_status() -> str:
    """Return the current authentication status."""
    initialize_auth_state()
    status = st.session_state[AUTH_STATUS_KEY]
    return status if isinstance(status, str) else STATUS_ANONYMOUS


def has_token_validation_error() -> bool:
    """Report whether a saved token exists but could not be validated."""
    return get_access_token() is not None and get_auth_status() == STATUS_ERROR


def retry_token_validation() -> None:
    """Allow one explicit retry of validation for a saved token."""
    initialize_auth_state()
    if get_access_token() is None:
        return

    st.session_state[AUTH_STATUS_KEY] = STATUS_ANONYMOUS
    st.session_state[AUTH_ERROR_KEY] = None


def validate_stored_token() -> Optional[str]:
    """Validate a saved token once, not on every Streamlit rerun."""
    initialize_auth_state()
    token = get_access_token()
    status = st.session_state[AUTH_STATUS_KEY]

    if token is None or status in (STATUS_VALID, STATUS_ERROR):
        return None

    try:
        user = fetch_current_user(token)
    except ApiError as exc:
        if exc.status_code == 401:
            clear_auth_session()
            return "Your session has expired or is invalid. Please log in again."

        st.session_state[AUTH_STATUS_KEY] = STATUS_ERROR
        st.session_state[AUTH_ERROR_KEY] = exc.message
        return None

    st.session_state[CURRENT_USER_KEY] = user
    st.session_state[AUTH_STATUS_KEY] = STATUS_VALID
    st.session_state[AUTH_ERROR_KEY] = None
    return None
