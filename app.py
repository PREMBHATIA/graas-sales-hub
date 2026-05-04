"""Graas Sales Hub — Pipeline, All-e & CRM."""

import streamlit as st

st.set_page_config(
    page_title="Graas Sales Hub",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #4F46E5, #7C3AED);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 1rem;
        color: #9CA3AF;
        margin-top: -10px;
        margin-bottom: 20px;
    }
    .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🚀 Graas Sales Hub")
    st.markdown("---")
    st.markdown("**Dashboards**")
    st.markdown("- 📋 Pipeline — Meetings & Proposals")
    st.markdown("- 🤖 All-e — Presales Pipeline")
    st.markdown("- 📧 CRM — Contacts & Outreach")
    st.markdown("- 💬 Ask Graas — AI Sales Assistant")
    st.markdown("- 📚 Resources — Decks & Docs")

st.markdown('<p class="main-header">Graas Sales Hub</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Pipeline, Presales & CRM — shared team view</p>', unsafe_allow_html=True)

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.markdown("### 📋 Pipeline")
    st.markdown("Meetings & Proposals tracker")
    st.page_link("pages/1_pipeline.py", label="Open Pipeline →")

with col2:
    st.markdown("### 🤖 All-e")
    st.markdown("Presales pipeline & deals")
    st.page_link("pages/2_alle.py", label="Open All-e →")

with col3:
    st.markdown("### 📧 CRM")
    st.markdown("Contacts & email outreach")
    st.page_link("pages/3_crm.py", label="Open CRM →")

with col4:
    st.markdown("### 💬 Ask Graas")
    st.markdown("AI-powered sales Q&A")
    st.page_link("pages/4_ask_graas.py", label="Ask a Question →")

with col5:
    st.markdown("### 📚 Resources")
    st.markdown("Key decks & docs")
    st.page_link("pages/5_resources.py", label="Open Resources →")

st.markdown("---")
st.markdown("💡 **Tip:** Use the sidebar to navigate between dashboards.")
