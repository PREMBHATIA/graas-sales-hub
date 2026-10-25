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

import json
from pathlib import Path

import streamlit as st

st.markdown("""
<style>
    /* 3rem, not 2: at 2rem the gradient header's ascenders were clipped by
       the top of the scroll container. */
    .block-container { padding-top: 3rem; }

    /* !important throughout: Streamlit styles paragraphs inside its own
       markdown container with a more specific selector, which silently won
       over font-size here and rendered the title at body size while the
       gradient still applied. */
    .main-header {
        font-size: 3.4rem !important;
        font-weight: 800 !important;
        letter-spacing: -0.035em;
        /* line-height and padding matter: -webkit-background-clip crops the
           glyphs to the painted box, so a tight box cuts the tops and tails
           off the letters. */
        line-height: 1.16 !important;
        padding: 4px 0 8px;
        background: linear-gradient(95deg, #4F46E5, #7C3AED 48%, #DB2777);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0 !important;
        display: inline-block;
    }
    .main-header .mh-graas {
        font-size: 0.52em;
        font-weight: 600;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        display: block;
        margin-bottom: -2px;
        opacity: 0.7;
    }
    .sub-header {
        font-size: 0.95rem !important;
        color: #9CA3AF;
        margin-top: 2px;
        margin-bottom: 28px;
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

    /* News — every card carries its own accent colour, set inline from the
       story's tag, so the band reads as a set rather than one highlight and
       a grey list. */
    .news-lead, .news-card {
        border: 1px solid #E5E7EB; border-radius: 12px;
        padding: 14px 16px; height: 100%;
    }
    .news-lead { padding: 17px 19px; margin: 4px 0 12px; }
    .news-lead .n-ttl { font-size: 1.06rem; font-weight: 800; margin: 6px 0 7px;
                        line-height: 1.3; letter-spacing: -0.01em; }
    .news-lead .n-why { font-size: 0.86rem; color: #374151; line-height: 1.45; }
    .news-card .n-ttl { font-size: 0.87rem; font-weight: 700; margin: 5px 0 0;
                        line-height: 1.36; }
    .n-tag  { font-size: 0.63rem; font-weight: 800; letter-spacing: .08em;
              text-transform: uppercase; display: block; }
    .n-src  { font-size: 0.73rem; color: #6B7280; margin-top: 7px; }
    .news-lead a, .news-card a { text-decoration: none; }
    .news-lead a:hover, .news-card a:hover { text-decoration: underline; }

    /* Security strip */
    .sec-strip {
        border: 1px solid #A7F3D0; border-left: 4px solid #059669;
        border-radius: 12px;
        background: linear-gradient(90deg, #F0FDF4, #FFFFFF 60%);
        padding: 13px 16px; margin-bottom: 6px;
        display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    }
    .sec-strip .s-ttl { font-weight: 800; font-size: 0.92rem;
                        margin-right: 4px; }
    .sec-badge {
        background: #FFFFFF; color: #065F46; border: 1px solid #A7F3D0;
        font-size: 0.7rem; font-weight: 700; padding: 3px 10px;
        border-radius: 999px; white-space: nowrap;
    }
    .sec-note { color: #6B7280; font-size: 0.8rem; margin-left: 4px; }
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


st.markdown('<p class="main-header"><span class="mh-graas">Graas</span> '
            'SalesHub</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Everything a salesperson needs — briefs, '
            'collateral, pipeline and outreach.</p>', unsafe_allow_html=True)

# ── All-e ─────────────────────────────────────────────────────────────────────
# Promoted above Cross-Product: it is where the team actually works and holds
# the only tiles most people need. The restricted sections sit below.

_label("All-e — where the work happens")

c1, c2, c3, c4 = st.columns(4)
with c1:
    _tile("📋", "Prospect Brief", "Pre-call two-pager research",
          "pages/9_prospect_brief.py", "Create a brief →")
with c2:
    # Open, unlike the Knowledge Base below — onboarding material the sales
    # team needs cannot sit behind the team password (Prem, 25 Oct).
    _tile("🎒", "Key Collateral", "GTM Immersion · videos · creds",
          "pages/6_collateral.py", "Open collateral →")
with c3:
    _tile("🤖", "All-e", "Presales pipeline &amp; deals",
          "pages/2_alle.py", "Open All-e →")
with c4:
    # Gated page inside an open section — the pill warns before the click.
    _tile("📧", "CRM", "Contacts, campaigns &amp; intent",
          "pages/3_crm.py", "Open CRM →", locked=True)
    st.markdown(
        '<div style="font-size:0.78rem;margin-top:6px">'
        '<a href="https://docs.google.com/spreadsheets/d/'
        '1Vcu7ZkAjGbzpKH2CUGoSuLUGIfwYBT-GlpNN0zMKJMY/edit" target="_blank">'
        'Outreach log ↗</a></div>', unsafe_allow_html=True)

st.markdown("")

# ── Security & compliance ────────────────────────────────────────────────────
# A strip, not a tile: the certs are a thing you point a procurement team at
# a few times a year, so it earns one line and a link — the documents
# themselves live in Key Collateral (Prem, 25 Oct).
st.markdown(
    '<div class="sec-strip">'
    '<span class="s-ttl">🔐 Security &amp; compliance</span>'
    '<span class="sec-badge">SOC 2 Type 2</span>'
    '<span class="sec-badge">ISO 27001</span>'
    '<span class="sec-badge">GDPR</span>'
    '<span class="sec-badge">PDPA</span>'
    '<span class="sec-note">Reports live in Key Collateral — '
    'send the link, not the file.</span>'
    '</div>', unsafe_allow_html=True)
_s1, _ = st.columns([1, 3])
with _s1:
    st.page_link("pages/6_collateral.py", label="Get the certificates →")

st.markdown("")

# ── News you can Use ─────────────────────────────────────────────────────────
# Reads content/news.json and NOTHING else — no API call, no Sheets read. The
# file is rewritten by .github/workflows/refresh-news.yml at 16:00 UTC
# (midnight SGT), deliberately when nobody is here. The Newsworthy tab was
# deleted in Aug 2026 for fetching on page load; this must never do that.
_NEWS = Path(__file__).parent.parent / "content" / "news.json"
_news = {}
try:
    _news = json.loads(_NEWS.read_text(encoding="utf-8"))
except Exception:
    _news = {}
_stories = _news.get("stories") or []

# Accent by subject, matched on the tag the model writes. Unknown tags fall
# back to slate rather than going uncoloured, so a new category never renders
# as a broken-looking grey card.
_ACCENTS = [
    (("architecture", "context layer", "knowledge graph", "ontolog"),
     ("#4F46E5", "#EEF2FF")),
    (("deployment", "vendor", "launch", "sap", "ships"),
     ("#059669", "#ECFDF5")),
    (("analyst", "research", "survey", "report"),
     ("#7C3AED", "#F5F3FF")),
    (("econom", "budget", "spend", "build-vs-buy", "cost"),
     ("#B45309", "#FFFBEB")),
    (("sierra", "decagon", "cresta", "intercom", "agent vendor"),
     ("#DB2777", "#FDF2F8")),
]


def _accent(tag: str):
    t = str(tag).lower()
    for keys, colours in _ACCENTS:
        if any(k in t for k in keys):
            return colours
    return ("#475569", "#F8FAFC")


if _stories:
    _when = str(_news.get("generated_utc", ""))[:10]
    _label(f"News you can Use &nbsp;·&nbsp; {_when}")

    _ld = _stories[0]
    _c, _bg = _accent(_ld.get("tag", ""))
    st.markdown(
        f'<div class="news-lead" style="border-left:4px solid {_c};'
        f'background:linear-gradient(90deg,{_bg},#FFFFFF 62%)">'
        f'<span class="n-tag" style="color:{_c}">{_ld.get("tag","")}</span>'
        f'<div class="n-ttl"><a href="{_ld.get("source_url","#")}" '
        f'target="_blank" style="color:#111827">{_ld.get("title","")}</a></div>'
        f'<div class="n-why">{_ld.get("why","")}</div>'
        f'<div class="n-src">{_ld.get("source_label","")} ↗</div></div>',
        unsafe_allow_html=True)

    _rest = _stories[1:]
    if _rest:
        _nc = st.columns(min(len(_rest), 3))
        for _i, _s in enumerate(_rest):
            _c2, _bg2 = _accent(_s.get("tag", ""))
            with _nc[_i % len(_nc)]:
                st.markdown(
                    f'<div class="news-card" style="border-left:4px solid {_c2};'
                    f'background:linear-gradient(135deg,{_bg2},#FFFFFF 70%)">'
                    f'<span class="n-tag" style="color:{_c2}">'
                    f'{_s.get("tag","")}</span>'
                    f'<div class="n-ttl"><a href="{_s.get("source_url","#")}" '
                    f'target="_blank" style="color:#1F2937">'
                    f'{_s.get("title","")}</a></div>'
                    f'<div class="n-src">{_s.get("source_label","")} ↗</div>'
                    f'</div>', unsafe_allow_html=True)
    st.markdown("")

# ── Restricted ────────────────────────────────────────────────────────────────

# Resources sits here, not in the All-e row: it is cross-product reference
# material, which is how app.py has always grouped it (Prem, 25 Oct).
_label("Cross-product, Hoppr &amp; reference", locked=True)

r1, r2, r3, _ = st.columns([1, 1, 1, 1])
with r1:
    _tile("📋", "Pipeline", "Meetings &amp; proposals — All-e + Hoppr",
          "pages/1_pipeline.py", "Open Pipeline →", locked=True)
with r2:
    _tile("📊", "Hoppr", "Usage, accounts &amp; MCP Beta",
          "pages/7_hoppr.py", "Open Hoppr →", locked=True)
with r3:
    _tile("🧠", "Knowledge Base", "Source docs, decks &amp; KB health",
          "pages/5_resources.py", "Open the KB →", locked=True)
