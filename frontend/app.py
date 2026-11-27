"""Streamlit entry point for Lana Study Buddy authentication screens."""

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

BRAND_NAME = "Lana Study Buddy"
TAGLINE = "Upload. Learn. Practise. Improve."

_CUSTOM_CSS = """
:root {
    --lana-bg: #F4F2FD;
    --lana-lavender: #A697F6;
    --lana-muted: #B8AFD0;
    --lana-primary: #6545D7;
    --lana-accent: #906FF1;
    --lana-ink: #2F2D37;
    --lana-clay: #B37470;
    --lana-plum: #9A729C;
}

html, body, [class*="css"] {
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    color: var(--lana-ink);
}

[data-testid="stAppViewContainer"] {
    background: var(--lana-bg);
}

[data-testid="stHeader"] {
    background: rgba(244, 242, 253, 0.88);
}

[data-testid="stSidebar"] {
    background: linear-gradient(
        180deg,
        #F4F2FD 0%,
        rgba(166, 151, 246, 0.18) 100%
    );
    border-right: 1px solid rgba(184, 175, 208, 0.55);
}

.sidebar-brand {
    font-size: 1.05rem;
    font-weight: 800;
    color: var(--lana-primary);
    padding: 0.35rem 0;
}

[data-testid="stSidebar"] .stButton > button {
    background: rgba(166, 151, 246, 0.2);
    color: var(--lana-primary);
    border: 1px solid rgba(101, 69, 215, 0.24);
}

[data-testid="stHorizontalBlock"]:has(.lana-art-panel) {
    align-items: center;
    flex-wrap: nowrap !important;
    gap: 1rem !important;
}

[data-testid="stHorizontalBlock"]:has(.lana-art-panel) > [data-testid="stColumn"] {
    box-sizing: border-box;
    min-width: 0;
}

[data-testid="stHorizontalBlock"]:has(.lana-art-panel) > [data-testid="stColumn"]:first-child {
    padding: 2.25rem 1.75rem;
    border-radius: 34px;
    background: rgba(244, 242, 253, 0.86);
    border: 1px solid rgba(184, 175, 208, 0.5);
    box-shadow: 0 24px 60px rgba(154, 114, 156, 0.16);
}

[data-testid="stHorizontalBlock"]:has(.lana-art-panel) > [data-testid="stColumn"]:last-child {
    padding: 1.5rem 1rem;
}

.lana-brand-lockup {
    display: flex;
    align-items: center;
    gap: 0.85rem;
    margin-bottom: 2.25rem;
}

.lana-brand-mark {
    width: 54px;
    height: 54px;
    border-radius: 18px;
    display: grid;
    place-items: center;
    font-size: 1.55rem;
    background: linear-gradient(135deg, var(--lana-primary), var(--lana-accent));
    box-shadow: 0 14px 28px rgba(101, 69, 215, 0.25);
}

.lana-brand-title {
    font-size: 1.05rem;
    font-weight: 800;
    color: var(--lana-primary);
    letter-spacing: 0.01em;
}

.lana-tagline {
    margin-top: 0.18rem;
    font-size: 0.78rem;
    font-weight: 700;
    color: var(--lana-plum);
}

.lana-intro h1 {
    margin: 0 0 0.55rem;
    font-size: clamp(2.2rem, 4vw, 3.4rem);
    line-height: 1.05;
    font-weight: 800;
    letter-spacing: -0.03em;
    color: var(--lana-ink);
}

.lana-intro p {
    margin: 0 0 1.8rem;
    font-size: 1.02rem;
    color: var(--lana-plum);
}

.lana-art-panel {
    position: relative;
    width: 100%;
    min-height: 640px;
    border-radius: 38px;
    padding: 1rem;
    display: grid;
    place-items: center;
    overflow: hidden;
    background:
        radial-gradient(
            circle at 78% 12%,
            rgba(166, 151, 246, 0.88) 0%,
            transparent 48%
        ),
        linear-gradient(155deg, #A697F6 0%, #906FF1 44%, #F4F2FD 100%);
    border: 1px solid rgba(144, 111, 241, 0.28);
    box-shadow:
        0 36px 80px rgba(154, 114, 156, 0.26),
        inset 0 1px 0 rgba(244, 242, 253, 0.9);
}

.lana-art-panel::before {
    content: "";
    position: absolute;
    top: -120px;
    right: -90px;
    width: 380px;
    height: 380px;
    border-radius: 50%;
    background: rgba(166, 151, 246, 0.35);
    filter: blur(18px);
}

.lana-art-panel::after {
    content: "";
    position: absolute;
    bottom: -150px;
    left: -100px;
    width: 340px;
    height: 340px;
    border-radius: 50%;
    background: rgba(144, 111, 241, 0.18);
    filter: blur(22px);
}

.lana-illustration {
    position: relative;
    z-index: 1;
    width: 100%;
    height: auto;
    max-height: 620px;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 0.35rem;
    width: max-content;
    padding: 0.3rem;
    border-radius: 16px;
    background: rgba(184, 175, 208, 0.22);
}

.stTabs [data-baseweb="tab"] {
    border-radius: 12px;
    padding: 0.6rem 1.1rem;
    font-weight: 700;
    color: var(--lana-plum);
}

.stTabs [aria-selected="true"] {
    color: var(--lana-primary);
    background: rgba(244, 242, 253, 0.96);
    box-shadow: 0 6px 16px rgba(154, 114, 156, 0.18);
}

[data-testid="stForm"] {
    padding: 1.35rem;
    border-radius: 24px;
    background: rgba(244, 242, 253, 0.92);
    border: 1px solid rgba(184, 175, 208, 0.6);
    box-shadow: 0 20px 45px rgba(154, 114, 156, 0.16);
    backdrop-filter: blur(10px);
}

[data-testid="stTextInput"] input {
    padding: 0.72rem 0.85rem;
    border-radius: 14px;
    border: 1px solid rgba(184, 175, 208, 0.85);
    background: var(--lana-bg);
    color: var(--lana-ink);
}

[data-testid="stTextInput"] input:focus {
    border-color: var(--lana-primary);
    box-shadow: 0 0 0 3px rgba(166, 151, 246, 0.35);
}

.stFormSubmitButton > button,
.stButton > button,
button[kind="primaryFormSubmit"],
button[kind="secondaryFormSubmit"] {
    border-radius: 14px;
    padding: 0.62rem 1rem;
    font-weight: 700;
    border: 1px solid transparent;
    transition: transform 0.14s ease, box-shadow 0.14s ease;
}

.stFormSubmitButton > button,
button[kind="primaryFormSubmit"],
.stButton > button[kind="primary"] {
    background: linear-gradient(90deg, var(--lana-primary), var(--lana-accent));
    color: var(--lana-bg);
    box-shadow: 0 12px 24px rgba(101, 69, 215, 0.24);
}

button[kind="secondaryFormSubmit"],
.stButton > button[kind="secondary"] {
    background: rgba(166, 151, 246, 0.2);
    color: var(--lana-primary);
    border-color: rgba(101, 69, 215, 0.24);
}

.stFormSubmitButton > button:hover,
.stButton > button:hover,
button[kind="primaryFormSubmit"]:hover,
button[kind="secondaryFormSubmit"]:hover {
    transform: translateY(-1px);
    box-shadow: 0 16px 30px rgba(154, 114, 156, 0.28);
}

button:focus-visible,
input:focus-visible {
    outline: 3px solid var(--lana-primary);
    outline-offset: 2px;
}

[data-testid="stAlert"] {
    border-radius: 16px;
    border: 1px solid rgba(184, 175, 208, 0.55);
}

@media (max-width: 640px) {
    [data-testid="stHorizontalBlock"]:has(.lana-art-panel) {
        flex-direction: column;
    }

    [data-testid="stHorizontalBlock"]:has(.lana-art-panel) > [data-testid="stColumn"] {
        width: 100% !important;
        flex: 1 1 100% !important;
        padding: 1rem !important;
    }

    .lana-art-panel {
        min-height: 420px;
    }

    .lana-illustration {
        max-height: 420px;
    }
}

@media (max-width: 640px) {
    .lana-brand-lockup {
        margin-bottom: 1.25rem;
    }

    .lana-intro h1 {
        font-size: 2.2rem;
    }

    [data-testid="stForm"] {
        padding: 1rem;
    }

    .lana-art-panel {
        min-height: 340px;
        border-radius: 28px;
    }
}

@media (prefers-reduced-motion: reduce) {
    .stFormSubmitButton > button,
    .stButton > button,
    button[kind="primaryFormSubmit"],
    button[kind="secondaryFormSubmit"] {
        transition: none;
    }
}
"""

_HIDDEN_SIDEBAR_CSS = """
[data-testid="stSidebar"] {
    display: none;
}
"""

_ILLUSTRATION_SVG = """
<svg class="lana-illustration" viewBox="0 0 640 620" role="img" aria-labelledby="lana-art-title lana-art-desc" xmlns="http://www.w3.org/2000/svg">
  <title id="lana-art-title">Lana Study Buddy student illustration</title>
  <desc id="lana-art-desc">A friendly student studies with books, notes, and floating quiz cards in a lavender scene.</desc>
  <defs>
    <linearGradient id="lana-halo" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#A697F6"/>
      <stop offset="100%" stop-color="#906FF1"/>
    </linearGradient>
    <linearGradient id="lana-shirt" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#6545D7"/>
      <stop offset="100%" stop-color="#906FF1"/>
    </linearGradient>
    <filter id="lana-shadow" x="-40%" y="-40%" width="180%" height="180%">
      <feDropShadow dx="0" dy="18" stdDeviation="16" flood-color="#9A729C" flood-opacity="0.3"/>
    </filter>
    <filter id="lana-soft-shadow" x="-40%" y="-40%" width="180%" height="180%">
      <feDropShadow dx="0" dy="10" stdDeviation="9" flood-color="#6545D7" flood-opacity="0.22"/>
    </filter>
  </defs>

  <ellipse cx="320" cy="562" rx="218" ry="28" fill="#B8AFD0" opacity="0.42"/>
  <circle cx="328" cy="292" r="218" fill="url(#lana-halo)" opacity="0.32"/>
  <circle cx="512" cy="118" r="66" fill="#A697F6" opacity="0.6"/>
  <circle cx="116" cy="404" r="78" fill="#906FF1" opacity="0.18"/>
  <path d="M126 300c38-36 76-40 114-10" fill="none" stroke="#B8AFD0" stroke-width="3" stroke-dasharray="6 10"/>

  <g filter="url(#lana-soft-shadow)" transform="translate(54 132) rotate(-8)">
    <rect width="146" height="88" rx="22" fill="#F4F2FD"/>
    <rect x="16" y="16" width="38" height="38" rx="12" fill="#6545D7"/>
    <path d="M27 27h16v16H27z" fill="#F4F2FD" opacity="0.85"/>
    <text x="66" y="34" fill="#2F2D37" font-family="Segoe UI, Arial, sans-serif" font-size="18" font-weight="700">Quiz</text>
    <text x="66" y="60" fill="#9A729C" font-family="Segoe UI, Arial, sans-serif" font-size="13">10 questions</text>
  </g>

  <g filter="url(#lana-soft-shadow)" transform="translate(452 168) rotate(9)">
    <rect width="132" height="82" rx="20" fill="#F4F2FD"/>
    <circle cx="32" cy="32" r="16" fill="#A697F6"/>
    <path d="M25 32l5 5 10-11" fill="none" stroke="#6545D7" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
    <text x="58" y="35" fill="#2F2D37" font-family="Segoe UI, Arial, sans-serif" font-size="17" font-weight="700">A+</text>
    <text x="24" y="65" fill="#9A729C" font-family="Segoe UI, Arial, sans-serif" font-size="12">Great work!</text>
  </g>

  <g filter="url(#lana-soft-shadow)" transform="translate(86 386) rotate(6)">
    <rect width="120" height="72" rx="18" fill="#F4F2FD"/>
    <rect x="16" y="16" width="52" height="8" rx="4" fill="#A697F6"/>
    <rect x="16" y="32" width="82" height="8" rx="4" fill="#B8AFD0"/>
    <rect x="16" y="48" width="64" height="8" rx="4" fill="#906FF1"/>
  </g>

  <g filter="url(#lana-shadow)">
    <rect x="196" y="432" width="252" height="34" rx="17" fill="#F4F2FD"/>
    <rect x="224" y="466" width="18" height="58" rx="9" fill="#B8AFD0"/>
    <rect x="402" y="466" width="18" height="58" rx="9" fill="#B8AFD0"/>
  </g>

  <g filter="url(#lana-shadow)">
    <path d="M238 432c0-58 38-96 82-96s82 38 82 96z" fill="url(#lana-shirt)"/>
    <path d="M300 346h40v30h-40z" fill="#B37470"/>
    <ellipse cx="320" cy="302" rx="63" ry="70" fill="#B37470"/>
    <path d="M258 292c0-49 27-78 62-78s62 29 62 78c0-18-18-28-40-32-18-3-31-15-38-30-10 20-27 33-46 36z" fill="#2F2D37"/>
    <circle cx="298" cy="306" r="5" fill="#2F2D37"/>
    <circle cx="342" cy="306" r="5" fill="#2F2D37"/>
    <path d="M303 330c10 9 24 9 34 0" fill="none" stroke="#2F2D37" stroke-width="4" stroke-linecap="round"/>
    <path d="M260 398c-24 8-36 22-36 38" fill="none" stroke="#B37470" stroke-width="18" stroke-linecap="round"/>
    <path d="M380 398c24 8 36 22 36 38" fill="none" stroke="#B37470" stroke-width="18" stroke-linecap="round"/>
  </g>

  <g filter="url(#lana-soft-shadow)">
    <path d="M254 412h132l18 28H236z" fill="#F4F2FD"/>
    <rect x="268" y="360" width="104" height="64" rx="10" fill="#906FF1"/>
    <rect x="278" y="370" width="84" height="44" rx="6" fill="#F4F2FD" opacity="0.82"/>
    <rect x="286" y="378" width="48" height="7" rx="3.5" fill="#A697F6"/>
    <rect x="286" y="392" width="62" height="7" rx="3.5" fill="#B8AFD0"/>
  </g>

  <g filter="url(#lana-soft-shadow)">
    <rect x="174" y="466" width="112" height="18" rx="9" fill="#9A729C"/>
    <rect x="180" y="448" width="100" height="18" rx="9" fill="#A697F6"/>
    <rect x="188" y="430" width="84" height="18" rx="9" fill="#B8AFD0"/>
  </g>

  <g fill="#6545D7" opacity="0.75">
    <circle cx="190" cy="210" r="5"/>
    <circle cx="214" cy="188" r="3"/>
    <circle cx="462" cy="292" r="4"/>
    <circle cx="488" cy="318" r="3"/>
  </g>
</svg>
"""


def _apply_custom_styles(hide_sidebar: bool) -> None:
    """Add the lavender Zentask-inspired visual theme with plain CSS."""
    st.markdown(
        "<style>"
        + _CUSTOM_CSS
        + (_HIDDEN_SIDEBAR_CSS if hide_sidebar else "")
        + "</style>",
        unsafe_allow_html=True,
    )


def _render_brand_lockup() -> None:
    """Show the Lana Study Buddy brand and tagline in the form column."""
    st.markdown(
        f"""
        <div class="lana-brand-lockup">
            <div class="lana-brand-mark">📚</div>
            <div>
                <div class="lana-brand-title">{BRAND_NAME}</div>
                <div class="lana-tagline">{TAGLINE}</div>
            </div>
        </div>
        <div class="lana-intro">
            <h1>Welcome back</h1>
            <p>Register or log in to continue.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_illustration() -> None:
    """Show the polished inline student illustration panel."""
    st.markdown(
        f'<div class="lana-art-panel">{_ILLUSTRATION_SVG}</div>',
        unsafe_allow_html=True,
    )


def render_auth_screen() -> None:
    """Show the split-screen login and registration interface."""
    form_column, art_column = st.columns([1.0, 1.18])

    with form_column:
        _render_brand_lockup()
        login_tab, register_tab = st.tabs(["Log in", "Register"])
        with login_tab:
            render_login_form()
        with register_tab:
            render_register_form()

    with art_column:
        _render_illustration()


def render_login_form() -> None:
    """Show the login form and store the token after a successful login."""
    with st.container():
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
    with st.container():
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
    with st.container(border=True):
        st.subheader("Home")
        st.write(f"Welcome, **{user.get('email', 'learner')}**!")
        st.info("You are signed in. Quiz features will be added in a later task.")
        st.caption(
            "Logging out clears this browser session only. "
            "A copied token remains valid until it expires."
        )


def main() -> None:
    """Run the Streamlit authentication interface."""
    st.set_page_config(page_title=BRAND_NAME, page_icon="📚", layout="wide")

    initialize_auth_state()
    _apply_custom_styles(hide_sidebar=not has_access_token())
    validation_message = validate_stored_token()

    st.sidebar.markdown(
        f'<div class="sidebar-brand">📚 {BRAND_NAME}</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.caption(TAGLINE)

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

    render_auth_screen()


main()
