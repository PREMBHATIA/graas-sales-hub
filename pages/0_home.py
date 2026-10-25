"""Graas Sales Hub — homepage.

Navigation only. The email stats table that used to head this page was
removed on 25 Oct: the numbers belong in Emails & Segments where they can be
read in context, and a landing page's job is to get people where they're
going. So this one is about making the destinations obvious and worth
clicking, not about data.

Styling note: hover and layout rules hang off
[data-testid="stVerticalBlockBorderWrapper"], the bordered container
Streamlit renders for st.container(border=True). That testid is stable across
releases; the st-emotion-cache-* classes beside it are not, so don't target
those.
"""

import streamlit as st

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }

    .main-header {
        font-size: 2.4rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        background: linear-gradient(90deg, #4F46E5, #7C3AED 55%, #DB2777);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 1rem;
        color: #9CA3AF;
        margin-top: -6px;
        margin-bottom: 30px;
    }

    /* Section label with a fading rule, so the eye can find the groups */
    .section-label {
        font-size: 0.7rem;
        font-weight: 800;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #6B7280;
        margin: 6px 0 12px;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .section-label::after {
        content: "";
        flex: 1;
        height: 1px;
        background: linear-gradient(90deg, #E5E7EB, transparent);
    }
    .lock-pill {
        background: #FEF3C7;
        color: #92400E;
        font-size: 0.62rem;
        font-weight: 800;
        letter-spacing: 0.06em;
        padding: 2px 7px;
        border-radius: 999px;
        text-transform: uppercase;
    }

    /* The cards themselves */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 14px;
        border: 1px solid #E5E7EB;
        transition: transform .15s ease, box-shadow .15s ease,
                    border-color .15s ease;
        height: 100%;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:hover {
        transform: translateY(-3px);
        box-shadow: 0 10px 22px rgba(79,70,229,.13);
        border-color: #C7D2FE;
    }
    .tile-icon  { font-size: 1.7rem; line-height: 1; }
    .tile-title { font-size: 1.02rem; font-weight: 800; margin: 6px 0 2px;
                  letter-spacing: -0.01em; }
    .tile-desc  { font-size: 0.82rem; color: #6B7280; min-height: 2.4em;
                  line-height: 1.35; }

    /* Streamlit's page_link, made to read as the card's action */
    div[data-testid="stVerticalBlockBorderWrapper"] a[data-testid="stPageLink-NavLink"] {
        font-weight: 700;
        font-size: 0.84rem;
    }
    .foot-tip {
        color: #6B7280; font-size: 0.86rem;
        background: #F9FAFB; border: 1px solid #F3F4F6;
        border-radius: 10px; padding: 10px 14px;
    }
</style>
""", unsafe_allow_html=True)


def _tile(icon, title, desc, page, label, locked=False):
    """One card. Same shape everywhere so the row lines up."""
    with st.container(border=True):
        st.markdown(
            f'<div class="tile-icon">{icon}</div>'
            f'<div class="tile-title">{title}'
            + (' <span class="lock-pill">locked</span>' if locked else '')
            + f'</div><div class="tile-desc">{desc}</div>',
            unsafe_allow_html=True)
        st.page_link(page, label=label)


def _label(text, locked=False):
    st.markdown(
        f'<p class="section-label">{text}'
        + (' <span class="lock-pill">restricted</span>' if locked else '')
        + '</p>', unsafe_allow_html=True)


st.markdown('<p class="main-header">Graas Sales Hub</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Pipeline, All-e &amp; Hoppr — shared team view</p>',
            unsafe_allow_html=True)

# ── All-e ─────────────────────────────────────────────────────────────────────
# Promoted above Cross-Product: it is where the team actually works and holds
# the only tiles most people need. The restricted sections sit below.

_label("All-e — where the work happens")

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    _tile("🤖", "All-e", "Presales pipeline &amp; deals",
          "pages/2_alle.py", "Open All-e →")
with c2:
    _tile("📋", "Prospect Brief", "Pre-call two-pager research",
          "pages/9_prospect_brief.py", "Create a brief →")
with c3:
    # Gated page inside an open section — the pill warns before the click.
    _tile("📧", "CRM", "Contacts, campaigns &amp; intent",
          "pages/3_crm.py", "Open CRM →", locked=True)
    st.markdown(
        '<div style="font-size:0.78rem;margin-top:6px">'
        '<a href="https://docs.google.com/spreadsheets/d/'
        '1Vcu7ZkAjGbzpKH2CUGoSuLUGIfwYBT-GlpNN0zMKJMY/edit" target="_blank">'
        'Outreach log ↗</a></div>', unsafe_allow_html=True)
with c4:
    # Open, unlike Resources beside it — onboarding material the sales team
    # needs cannot sit behind the team password (Prem, 25 Oct).
    _tile("🎒", "Key Collateral", "GTM Immersion · videos · creds",
          "pages/6_collateral.py", "Open collateral →")
with c5:
    _tile("📚", "Resources", "Key decks &amp; docs",
          "pages/5_resources.py", "Open Resources →", locked=True)

st.markdown("")

# ── Restricted ────────────────────────────────────────────────────────────────

_label("Cross-product &amp; Hoppr", locked=True)

r1, r2, _ = st.columns([1, 1, 3])
with r1:
    _tile("📋", "Pipeline", "Meetings &amp; proposals — All-e + Hoppr",
          "pages/1_pipeline.py", "Open Pipeline →", locked=True)
with r2:
    _tile("📊", "Hoppr", "Usage, accounts &amp; MCP Beta",
          "pages/7_hoppr.py", "Open Hoppr →", locked=True)

st.markdown("")
st.markdown(
    '<div class="foot-tip">🔒 <b>Locked</b> tiles need the team password — '
    'one unlock covers them all for this browser session. '
    'Everything else is open to the whole team.</div>',
    unsafe_allow_html=True)
