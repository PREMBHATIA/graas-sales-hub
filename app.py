"""Graas Sales Hub — navigation controller."""

import streamlit as st

st.set_page_config(
    page_title="Graas Sales Hub",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

pg = st.navigation(
    {
        "": [
            st.Page("pages/0_home.py", title="🏠 Home", url_path="home"),
        ],
        # 🔒 Gated section — password-protected (see services/auth_gate.py).
        "Cross-Product 🔒": [
            st.Page("pages/1_pipeline.py",  title="📋 Pipeline",   url_path="pipeline"),
        ],
        "All-e": [
            st.Page("pages/2_alle.py",            title="📊 Pipeline",                url_path="alle"),
            # 🔒 Gated page inside an otherwise-open section — the lock sits on the
            # page title, not the "All-e" group, because its siblings stay open.
            st.Page("pages/3_crm.py",             title="📧 Emails & Segments 🔒",     url_path="crm"),
            st.Page("pages/9_prospect_brief.py",  title="📋 Create Prospect Brief  ✨ NEW",   url_path="prospect-brief"),
            st.Page("pages/B_proposal_bank.py",   title="📑 Proposal Bank",            url_path="proposal-bank"),
            # Open, unlike Resources at the bottom: onboarding and customer-
            # facing collateral cannot sit behind the team password, which the
            # sales team does not have (Prem, 25 Oct).
            st.Page("pages/6_collateral.py",      title="🎒 Key Collateral",           url_path="collateral"),
        ],
        # 🔒 Gated section — password-protected (Hoppr + MCP Beta).
        "Hoppr 🔒": [
            st.Page("pages/7_hoppr.py",      title="📊 Hoppr",      url_path="hoppr"),
        ],
        # Shared / cross-product reference material — kept at the bottom so it
        # reads as "the team's library", not as an All-e-specific page.
        # 🔒 Gated section — the KB holds internal-only material.
        "Knowledge 🔒": [
            st.Page("pages/5_resources.py",  title="📚 Resources",  url_path="resources"),
        ],
    },
    position="sidebar",
)

pg.run()
