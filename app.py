"""Graas Sales Hub — Pipeline, All-e & Hoppr."""

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
        margin-bottom: 28px;
    }
    .section-label {
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #6B7280;
        margin-bottom: 8px;
        margin-top: 4px;
    }
    .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🚀 Graas Sales Hub")
    st.markdown("---")

    st.markdown("**Cross-Product**")
    st.markdown("📋 Pipeline")
    st.markdown("")

    st.markdown("**All-e**")
    st.markdown("🤖 All-e Presales")
    st.markdown("📧 CRM")
    st.markdown("📚 Resources")
    st.markdown("📝 All-e Proposal")
    st.markdown("💬 Ask All-e")
    st.markdown("")

    st.markdown("**Hoppr**")
    st.markdown("📊 Hoppr")

# ── Homepage ──────────────────────────────────────────────────────────────────

st.markdown('<p class="main-header">Graas Sales Hub</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Pipeline, All-e & Hoppr — shared team view</p>', unsafe_allow_html=True)

# ── Section: Cross-Product ────────────────────────────────────────────────────

st.markdown('<p class="section-label">Cross-Product</p>', unsafe_allow_html=True)

col1, _ = st.columns([1, 3])
with col1:
    st.markdown("### 📋 Pipeline")
    st.markdown("Meetings & proposals — All-e + Hoppr")
    st.page_link("pages/1_pipeline.py", label="Open Pipeline →")

st.markdown("---")

# ── Section: All-e ────────────────────────────────────────────────────────────

st.markdown('<p class="section-label">All-e</p>', unsafe_allow_html=True)

c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    st.markdown("### 🤖 All-e")
    st.markdown("Presales pipeline & deals")
    st.page_link("pages/2_alle.py", label="Open All-e →")

with c2:
    st.markdown("### 📧 CRM")
    st.markdown("Contacts & email outreach")
    st.page_link("pages/3_crm.py", label="Open CRM →")

with c3:
    st.markdown("### 📚 Resources")
    st.markdown("Key decks & docs")
    st.page_link("pages/5_resources.py", label="Open Resources →")

with c4:
    st.markdown("### 📝 Proposal")
    st.markdown("Build a customer proposal")
    st.page_link("pages/6_proposal.py", label="Open Proposal →")

with c5:
    st.markdown("### 💬 Ask All-e")
    st.markdown("Pipeline & solutions architect")
    st.page_link("pages/4_ask_graas.py", label="Ask All-e →")

st.markdown("---")

# ── Section: Hoppr ────────────────────────────────────────────────────────────

st.markdown('<p class="section-label">Hoppr</p>', unsafe_allow_html=True)

h1, _ = st.columns([1, 3])
with h1:
    st.markdown("### 📊 Hoppr")
    st.markdown("Usage, accounts & Ask Hoppr")
    st.page_link("pages/7_hoppr.py", label="Open Hoppr →")

st.markdown("---")
st.markdown("💡 **Tip:** Use the sidebar to navigate between dashboards.")
