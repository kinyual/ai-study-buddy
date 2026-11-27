"""Streamlit entry point for AI Study Buddy authentication screens."""

import streamlit as st

from api_client import ApiError, get_current_user, login_user, register_user
from auth_state import (
    clear_auth_error,
    clear_auth_session,
    get_auth_error,
    get_current_user as get_saved_user,
    has_access_token,
    has_token_validation_error,
    initialize_auth_state,
    is_authenticated,
    retry_token_validation,
    set_authenticated,
    validate_stored_token,
)


def render_login_form() -> None:
    """Show the login form and store the token after a successful login."""
    st.subheader("Log in")

    with st.form("login_form", clear_on_submit=True):
        email = st.text_input("Email", autocomplete="email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

    if not submitted:
        return

    clear_auth_error()
    email = email.strip()

    if not email or not password:
        st.error("Please enter both your email and password.")
        return

    try:
        token_response = login_user(email, password)
        token = token_response["access_token"]
        user = get_current_user(token)
        set_authenticated(token, user)
        st.rerun()
    except ApiError as exc:
        st.error(exc.message)


def render_register_form() -> None:
    """Show the registration form and call the registration endpoint."""
    st.subheader("Register")

    with st.form("register_form", clear_on_submit=True):
        email = st.text_input("Email", autocomplete="email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Create account")

    if not submitted:
        return

    clear_auth_error()
    email = email.strip()

    if not email or not password:
        st.error("Please enter both your email and password.")
        return

    try:
        register_user(email, password)
        st.success("Account created. Please log in with your new credentials.")
    except ApiError as exc:
        st.error(exc.message)


def render_home(user: dict[str, object]) -> None:
    """Show a simple protected home screen after login."""
    st.subheader("Home")
    st.write(f"Welcome, **{user.get('email', 'learner')}**!")
    st.info("You are signed in. Quiz features will be added in a later task.")
    st.caption(
        "Logging out clears this browser session only. "
        "A copied token remains valid until it expires."
    )


def main() -> None:
    """Run the Streamlit authentication interface."""
    st.set_page_config(page_title="AI Study Buddy", page_icon="📚")

    initialize_auth_state()
    validation_message = validate_stored_token()

    st.sidebar.title("AI Study Buddy")

    if has_access_token() and st.sidebar.button("Log out"):
        clear_auth_session()
        st.rerun()

    if validation_message:
        st.warning(validation_message)

    auth_error = get_auth_error()
    if auth_error:
        st.error(auth_error)

    if has_token_validation_error():
        st.info("Your saved session could not be checked yet.")
        if st.button("Retry validation"):
            retry_token_validation()
            st.rerun()

    if is_authenticated():
        render_home(get_saved_user() or {})
        return

    st.title("Welcome")
    st.write("Register or log in to continue.")

    login_tab, register_tab = st.tabs(["Log in", "Register"])
    with login_tab:
        render_login_form()
    with register_tab:
        render_register_form()


main()
