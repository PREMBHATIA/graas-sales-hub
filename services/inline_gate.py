"""Inline password gate — locks ONE section of an otherwise-open page.

`auth_gate.require_unlock()` stops the whole page, which is right for a page that
is entirely restricted. The All-e Pipeline page is open to the whole viewer list,
but its "Deals by Stage" tab shows deal values, weighted pipeline by person and
deal risks, so only that tab is locked. `gate_inline()` renders the password form
in place and returns False until the session is unlocked; callers must load the
section's data only when it returns True, so a locked viewer never triggers the
fetch.

It reuses auth_gate's password and session flag, so one unlock covers every
gated section for the browser session. Kept in its own module (rather than added
to auth_gate.py) so a Streamlit Cloud redeploy can never serve a page that
imports a symbol the cached auth_gate module doesn't have yet.
"""

import hmac

import streamlit as st

from services.auth_gate import _SESSION_KEY, _expected_password, is_unlocked


def gate_inline(section_label: str, key: str = "inline") -> bool:
    """True when the session is unlocked. Otherwise draw the unlock form and
    return False."""
    if is_unlocked():
        return True

    st.markdown(f"#### 🔒 {section_label} is restricted")
    st.caption(
        "Enter the team access password to view this tab. It is the same password "
        "as Pipeline (Cross-Product), Hoppr, Emails & Segments and Resources, and "
        "unlocks all of them for this browser session."
    )
    with st.form(f"saleshub_unlock_inline_{key}", clear_on_submit=False):
        pw = st.text_input("Access password", type="password",
                           key=f"saleshub_unlock_pw_{key}")
        submitted = st.form_submit_button("Unlock", type="primary")
    if submitted:
        if hmac.compare_digest(str(pw), _expected_password()):
            st.session_state[_SESSION_KEY] = True
            st.session_state.pop(f"saleshub_unlock_pw_{key}", None)
            st.rerun()
        else:
            st.error("Incorrect password. Ask Prem for the section password.")
    return False
