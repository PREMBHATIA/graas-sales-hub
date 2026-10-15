"""Section-level password gate for SalesHub.

The app itself is reachable by anyone on the Streamlit Cloud viewer list (valid
email). Some sections hold internal data we don't want the whole audience to
see — Pipeline (Cross-Product) and Hoppr/MCP. Those pages call `require_unlock()`
at the top; everything in the All-e section (Prospect Brief, Emails, Proposal
Bank), Home and Resources stays open.

One shared password, set once in Streamlit Cloud → Settings → Secrets as
`SALESHUB_SECTION_PASSWORD` (env var of the same name also works). Unlocking on
one gated page unlocks all of them for that browser session.

Fails CLOSED: if no password is configured, the gated pages show a config
notice instead of their content — so widening the viewer list can never
accidentally expose these sections.
"""

import hmac
import os

import streamlit as st

_SESSION_KEY = "saleshub_restricted_unlocked"
_SECRET_NAME = "SALESHUB_SECTION_PASSWORD"


def _expected_password() -> str:
    """The configured section password — env first, then st.secrets. '' if unset."""
    pw = os.getenv(_SECRET_NAME, "")
    if not pw:
        try:
            if hasattr(st, "secrets") and _SECRET_NAME in st.secrets:
                pw = st.secrets[_SECRET_NAME]
        except Exception:
            pw = ""
    return str(pw or "")


def is_unlocked() -> bool:
    return bool(st.session_state.get(_SESSION_KEY))


def require_unlock(section_label: str = "This section") -> None:
    """Gate the current page. Renders a password prompt and st.stop()s until the
    correct password is entered; returns normally (page continues) once the
    session is unlocked. MUST be called after st.set_page_config and BEFORE any
    data is loaded, so gated data is never fetched for a locked viewer."""
    if is_unlocked():
        return

    expected = _expected_password()
    if not expected:
        # No password configured → fail closed with an admin-facing message.
        st.markdown(f"## 🔒 {section_label} is restricted")
        st.error(
            "This section is locked, but no access password is configured yet. "
            f"An admin needs to set **`{_SECRET_NAME}`** in Streamlit Cloud → "
            "Settings → Secrets (or as an environment variable) to enable access."
        )
        st.stop()

    st.markdown(f"## 🔒 {section_label} is restricted")
    st.caption(
        "Enter the team access password to view this section. The Prospect Brief, "
        "Emails & Segments and Proposal Bank don't need this — only Pipeline and "
        "Hoppr are gated."
    )
    with st.form("saleshub_unlock_form", clear_on_submit=False):
        pw = st.text_input("Access password", type="password",
                            key="saleshub_unlock_pw")
        submitted = st.form_submit_button("Unlock", type="primary")
    if submitted:
        if hmac.compare_digest(str(pw), expected):
            st.session_state[_SESSION_KEY] = True
            # Drop the typed password from session state before rerunning.
            st.session_state.pop("saleshub_unlock_pw", None)
            st.rerun()
        else:
            st.error("Incorrect password. Ask Prem for the section password.")
    st.stop()
