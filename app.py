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
            st.Page("pages/1_pipeline.py", title="📋 Pipeline", url_path="pipeline"),
        ],
        "All-e": [
            st.Page("pages/2_alle.py",      title="🤖 All-e Presales", url_path="alle"),
            st.Page("pages/3_crm.py",       title="📧 CRM",            url_path="crm"),
            st.Page("pages/5_resources.py", title="📚 Resources",       url_path="resources"),
            st.Page("pages/6_proposal.py",  title="📝 All-e Proposal",  url_path="proposal"),
            st.Page("pages/4_ask_graas.py", title="💬 Ask All-e",       url_path="ask-alle"),
        ],
        "Hoppr": [
            st.Page("pages/7_hoppr.py",      title="📊 Hoppr",      url_path="hoppr"),
            st.Page("pages/8_ask_hoppr.py",  title="💬 Ask Hoppr",  url_path="ask-hoppr"),
        ],
    },
    position="sidebar",
)

pg.run()
