"""Section-level password gate for SalesHub.

The app itself is reachable by anyone on the Streamlit Cloud viewer list (valid
email). Some pages hold internal data we don't want the whole audience to see —
Pipeline (Cross-Product), Hoppr/MCP, Emails & Segments (real recipient data,
send log and open/click tracking) and Resources / the Knowledge Base (internal
GTM material, commercials, lessons learnt). Those pages call `require_unlock()`
at the top; Home and the rest of All-e (Pipeline, Prospect Brief, Proposal Bank)
stay open.

The KB's own Drive folders were made private on 2026-10-22 (the public
"anyone with link" reader was removed from the "KB (in SalesHub)" wrapper, which
the whole KB tree inherited from). Gating the Resources page keeps the app
surface consistent with that.

Note the lock is per PAGE, not per sidebar group: Emails & Segments sits inside
the otherwise-open All-e group, so its 🔒 marker lives on the page title in
app.py rather than on the group label.

One shared password for everyone on the viewer list. It resolves in this order:
env var `SALESHUB_SECTION_PASSWORD` → st.secrets `SALESHUB_SECTION_PASSWORD` →
the temporary built-in default below. Set the secret to rotate it without a code
change; until then the built-in default applies. Unlocking on one gated page
unlocks all of them for that browser session.
"""

import hmac
import os

import streamlit as st

_SESSION_KEY = "saleshub_restricted_unlocked"
_SECRET_NAME = "SALESHUB_SECTION_PASSWORD"
# Temporary shared password. Low-stakes section gate (hides Pipeline/Hoppr from
# the wider viewer list), not hard security. To rotate it without a code change,
# set SALESHUB_SECTION_PASSWORD in Streamlit Cloud → Settings → Secrets — that
# overrides this. Only repo collaborators can see this value, not the app's
# viewer list.
_DEFAULT_PASSWORD = "showmethemoney"


def _expected_password() -> str:
    """The section password — env → st.secrets → built-in default."""
    pw = os.getenv(_SECRET_NAME, "")
    if not pw:
        try:
            if hasattr(st, "secrets") and _SECRET_NAME in st.secrets:
                pw = st.secrets[_SECRET_NAME]
        except Exception:
            pw = ""
    return str(pw or _DEFAULT_PASSWORD)


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
        "All-e Pipeline and Proposal Bank don't need this — Pipeline "
        "(Cross-Product), Hoppr, Emails & Segments and Resources are gated. "
        "Unlocking here unlocks all of them for this browser session."
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
