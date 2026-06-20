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
        "Cross-Product": [
            st.Page("pages/1_pipeline.py",  title="📋 Pipeline",   url_path="pipeline"),
            st.Page("pages/4_ask_graas.py", title="💬 Ask Graas",  url_path="ask-graas"),
        ],
        "All-e": [
            st.Page("pages/2_alle.py",            title="📊 Pipeline",                url_path="alle"),
            st.Page("pages/3_crm.py",             title="📧 Emails & Segments",        url_path="crm"),
            st.Page("pages/9_prospect_brief.py",  title="📋 Create Prospect Brief  ✨ NEW",   url_path="prospect-brief"),
            st.Page("pages/A_architect_soln.py",  title="🏗️ Architect a Soln",         url_path="architect"),
            st.Page("pages/6_proposal.py",        title="📝 Create Proposal",         url_path="proposal"),
        ],
        "Hoppr": [
            st.Page("pages/7_hoppr.py",      title="📊 Hoppr",      url_path="hoppr"),
            st.Page("pages/8_ask_hoppr.py",  title="💬 Ask Hoppr",  url_path="ask-hoppr"),
        ],
        # Shared / cross-product reference material — kept at the bottom so it
        # reads as "the team's library", not as an All-e-specific page.
        "Knowledge": [
            st.Page("pages/5_resources.py",  title="📚 Resources",  url_path="resources"),
        ],
    },
    position="sidebar",
)

pg.run()
