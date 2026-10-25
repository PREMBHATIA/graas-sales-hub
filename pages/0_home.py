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

st.markdown('<p class="section-label">Cross-Product · 🔒 restricted</p>', unsafe_allow_html=True)

xc1, _ = st.columns([1, 3])
with xc1:
    st.markdown("### 📋 Pipeline 🔒")
    st.markdown("Meetings & proposals — All-e + Hoppr")
    st.page_link("pages/1_pipeline.py", label="Open Pipeline →")

st.markdown("---")

# ── All-e ─────────────────────────────────────────────────────────────────────

st.markdown('<p class="section-label">All-e</p>', unsafe_allow_html=True)

c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    st.markdown("### 🤖 All-e")
    st.markdown("Presales pipeline & deals")
    st.page_link("pages/2_alle.py", label="Open All-e →")

with c2:
    st.markdown("### 📋 Prospect Brief")
    st.markdown("Pre-call two-pager research")
    st.page_link("pages/9_prospect_brief.py", label="Create Brief →")

with c3:
    # Gated page inside the open All-e section — mark the tile so the lock isn't
    # a surprise on click, the same way the Pipeline and Hoppr tiles do.
    # The standalone "Email outreach" section that used to head this page was
    # the same link twice (Prem, 25 Oct) — outreach IS All-e, so it lives here.
    st.markdown("### 📧 CRM 🔒")
    st.markdown("Contacts, campaigns & intent")
    st.page_link("pages/3_crm.py", label="Open CRM →")
    st.markdown(
        "[Outreach log (Sheet) ↗]"
        "(https://docs.google.com/spreadsheets/d/"
        "1Vcu7ZkAjGbzpKH2CUGoSuLUGIfwYBT-GlpNN0zMKJMY/edit)"
    )

with c4:
    # Open, unlike Resources beside it — onboarding material the sales team
    # needs cannot sit behind the team password (Prem, 25 Oct).
    st.markdown("### 🎒 Key Collateral")
    st.markdown("GTM Immersion · videos · creds")
    st.page_link("pages/6_collateral.py", label="Open Key Collateral →")

with c5:
    st.markdown("### 📚 Resources 🔒")
    st.markdown("Key decks & docs")
    st.page_link("pages/5_resources.py", label="Open Resources →")

st.markdown("---")

# ── Hoppr ─────────────────────────────────────────────────────────────────────

st.markdown('<p class="section-label">Hoppr · 🔒 restricted</p>', unsafe_allow_html=True)

h1, _ = st.columns([1, 3])
with h1:
    st.markdown("### 📊 Hoppr 🔒")
    st.markdown("Usage, accounts & MCP Beta")
    st.page_link("pages/7_hoppr.py", label="Open Hoppr →")

st.markdown("---")
st.markdown("💡 **Tip:** Use the sidebar to navigate between dashboards.")
