"""Graas Sales Hub — homepage."""

import streamlit as st

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

st.markdown('<p class="main-header">Graas Sales Hub</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Pipeline, All-e & Hoppr — shared team view</p>', unsafe_allow_html=True)

# ── Cross-Product ─────────────────────────────────────────────────────────────

st.markdown('<p class="section-label">Cross-Product</p>', unsafe_allow_html=True)

xc1, xc2, _ = st.columns([1, 1, 2])
with xc1:
    st.markdown("### 📋 Pipeline")
    st.markdown("Meetings & proposals — All-e + Hoppr")
    st.page_link("pages/1_pipeline.py", label="Open Pipeline →")
with xc2:
    st.markdown("### 💬 Ask Graas")
    st.markdown("Cross-product Q&A — All-e, Extract, MOR, Hoppr")
    st.page_link("pages/4_ask_graas.py", label="Ask Graas →")

st.markdown("---")

# ── All-e ─────────────────────────────────────────────────────────────────────

st.markdown('<p class="section-label">All-e</p>', unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)

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

st.markdown("---")

# ── Hoppr ─────────────────────────────────────────────────────────────────────

st.markdown('<p class="section-label">Hoppr</p>', unsafe_allow_html=True)

h1, _ = st.columns([1, 3])
with h1:
    st.markdown("### 📊 Hoppr")
    st.markdown("Usage, accounts & Ask Hoppr")
    st.page_link("pages/7_hoppr.py", label="Open Hoppr →")

st.markdown("---")
st.markdown("💡 **Tip:** Use the sidebar to navigate between dashboards.")
