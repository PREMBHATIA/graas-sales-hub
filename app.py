"""SalesHub — navigation controller.

The page files live in views/, NOT pages/. Streamlit auto-discovers any
folder called pages/ and builds its own sidebar from the filenames, which
showed up beside this one as a flat lowercase list ("ask graas", "B
proposal bank") with no groups, no icons and no lock markers. Renaming the
folder is what stops that: st.navigation below is then the only nav, and
its first entry — Home — is where everyone lands.
"""

import streamlit as st

st.set_page_config(
    page_title="SalesHub | Graas",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

pg = st.navigation(
    {
        "": [
            # default=True, not merely first: Streamlit falls back to the
            # first page in the first group, so a reorder would silently move
            # where everyone lands. This states it.
            st.Page("views/0_home.py", title="🏠 Home", url_path="home",
                    default=True),
        ],
        # 🔒 Gated section — password-protected (see services/auth_gate.py).
        "Cross-Product 🔒": [
            st.Page("views/1_pipeline.py",  title="📋 Pipeline",   url_path="pipeline"),
        ],
        "All-e": [
            st.Page("views/2_alle.py",            title="📊 Pipeline",                url_path="alle"),
            # 🔒 Gated page inside an otherwise-open section — the lock sits on the
            # page title, not the "All-e" group, because its siblings stay open.
            st.Page("views/3_crm.py",             title="📧 Emails & Segments 🔒",     url_path="crm"),
            st.Page("views/9_prospect_brief.py",  title="📋 Create Prospect Brief  ✨ NEW",   url_path="prospect-brief"),
            st.Page("views/B_proposal_bank.py",   title="📑 Proposal Bank",            url_path="proposal-bank"),
            # Open, unlike Resources at the bottom: onboarding and customer-
            # facing collateral cannot sit behind the team password, which the
            # sales team does not have (Prem, 25 Oct).
            st.Page("views/6_collateral.py",      title="🎒 Key Collateral",           url_path="collateral"),
            # Ask Graas is deliberately NOT in the nav (Prem, 26 Oct). The page
            # file stays in views/ so this is a one-line restore, but views/ is
            # not auto-discovered by Streamlit, so leaving it out here is what
            # actually removes it — there is no second route back in.
        ],
        # 🔒 Gated section — password-protected (Hoppr + MCP Beta).
        "Hoppr 🔒": [
            st.Page("views/7_hoppr.py",      title="📊 Hoppr",      url_path="hoppr"),
            st.Page("views/8_ask_hoppr.py",  title="💬 Ask Hoppr",  url_path="ask-hoppr"),
        ],
        # Shared / cross-product reference material — kept at the bottom so it
        # reads as "the team's library", not as an All-e-specific page.
        # 🔒 Gated section — the KB holds internal-only material.
        "Reference 🔒": [
            st.Page("views/5_resources.py",  title="🧠 Knowledge Base",  url_path="resources"),
        ],
    },
    position="sidebar",
)

pg.run()
