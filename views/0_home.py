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
    .sub-header {
        font-size: 0.95rem !important;
        color: #9CA3AF;
        margin-top: 2px;
        margin-bottom: 28px;
    }

    /* Section label with a fading rule, so the eye can find the groups */
    .section-label {
        font-size: 1rem;
        font-weight: 800;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #111827;
        margin: 8px 0 14px;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    /* accent bar in the title's indigo-to-pink, so each section start is findable */
    .section-label::before {
        content: "";
        width: 5px;
        height: 1.15em;
        border-radius: 3px;
        background: linear-gradient(180deg, #4F46E5, #DB2777);
    }
    .section-label::after {
        content: "";
        flex: 1;
        height: 2px;
        background: linear-gradient(90deg, #C7D2FE, transparent);
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
    /* Icon sits beside the title, not above it: the cards live in a narrow rail
       next to the pipeline board, and stacking the icon cost ~30px a card. */
    .tile-icon  { font-size: 1.3rem; line-height: 1; display: inline-block;
                  vertical-align: middle; margin-right: 7px; }
    .tile-title { font-size: 1.02rem; font-weight: 800; display: inline;
                  vertical-align: middle; letter-spacing: -0.01em; }
    .tile-desc  { font-size: 0.8rem; color: #6B7280; margin-top: 3px;
                  line-height: 1.35; }

    /* Streamlit's page_link, made to read as the card's action */
    div[data-testid="stVerticalBlockBorderWrapper"] a[data-testid="stPageLink-NavLink"] {
        font-weight: 700;
        font-size: 0.84rem;
    }

    /* The All-e rail: solid coloured tiles so it holds its own beside the dark
       pipeline board. Streamlit gives a container no class of its own, so each tile
       carries a marker span (.tm-<tone>) and the CSS finds the card whose own
       children hold it. Two selector forms cover older and newer Streamlit markup. */
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm) {
        border: none; color: #FFFFFF; box-shadow: 0 6px 16px rgba(30,27,75,.16);
        transition: transform .15s ease, box-shadow .15s ease;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm-indigo),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm-indigo) {
        background: linear-gradient(135deg, #4F46E5, #7C3AED);
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm-amber),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm-amber) {
        background: linear-gradient(135deg, #F59E0B, #EA580C);
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm-teal),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm-teal) {
        background: linear-gradient(135deg, #0D9488, #0891B2);
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm-rose),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm-rose) {
        background: linear-gradient(135deg, #DB2777, #9D174D);
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm):hover {
        box-shadow: 0 12px 26px rgba(30,27,75,.28); transform: translateY(-3px);
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm) .tile-title,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm) .tile-title { color: #FFFFFF; }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm) .tile-desc,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm) .tile-desc { color: rgba(255,255,255,.88); }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm) a[data-testid="stPageLink-NavLink"],
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm) a[data-testid="stPageLink-NavLink"] { background: rgba(255,255,255,.2); border-radius: 8px; }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm) a[data-testid="stPageLink-NavLink"] *,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm) a[data-testid="stPageLink-NavLink"] * { color: #FFFFFF !important; }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm) .lock-pill,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm) .lock-pill { background: #FFFFFF; }

    /* Compact: the rail sits beside a board that is already tall. */
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm) { position: relative; padding: 0.8rem 0.95rem 0.85rem; gap: 0.2rem; }
    /* the action button rides the title row at the right instead of taking its own row */
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm) > div > div[data-testid="stElementContainer"]:last-child,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm) > div[data-testid="stElementContainer"]:last-child { position: absolute; top: 0.55rem; right: 0.6rem; width: auto; }
    /* narrow window: not enough room beside the title, so the button gets its own row */
    @media (max-width: 1300px) {
      div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm) > div > div[data-testid="stElementContainer"]:last-child,
      div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm) > div[data-testid="stElementContainer"]:last-child { position: static; }
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm) .tile-desc,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm) .tile-desc { margin-top: 1px; }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stElementContainer"] .tm) a[data-testid="stPageLink-NavLink"],
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tm) a[data-testid="stPageLink-NavLink"] { padding: 0.1rem 0.6rem; min-height: 0; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stLayoutWrapper"] .tm) { gap: 0.55rem; }

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

    /* Monthly Ruminations — headline + date only. The emails themselves are
       in Key Collateral; this is a reminder that they exist and are
       forwardable, not a reading list. */
    .rumi-row {
        display: flex; align-items: baseline; gap: 10px;
        padding: 8px 0; border-bottom: 1px solid #F3F4F6;
        font-size: 0.86rem;
    }
    .rumi-row:last-child { border-bottom: none; }
    .rumi-date {
        font-size: 0.68rem; font-weight: 800; color: #6B7280;
        letter-spacing: .06em; text-transform: uppercase;
        white-space: nowrap; min-width: 62px;
    }
    .rumi-row a { color: #1F2937; text-decoration: none; }
    .rumi-row a:hover { text-decoration: underline; }
    .rumi-about { color: #6B7280; font-size: 0.8rem; flex: 1;
                  border-left: 2px solid #E5E7EB; padding-left: 12px;
                  margin-left: 4px; }
    .rumi-subj  { min-width: 270px; font-weight: 600; }

    /* All-e pipeline board: four columns (proposals <60 days, >60 days, won,
       lost), the same funnel as the Cross-Product Proposal Board. Plain HTML,
       NOT a bordered container, so the card hover-lift above doesn't apply. */
    .kb-sum  { font-size: 0.8rem; color: #6B7280; margin: 0 0 10px; }
    .kb-sum b { color: #111827; }
    .kb-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr));
               gap: 14px; }
    .kb-head { font-weight: 800; font-size: 0.92rem; line-height: 1.2;
               padding: 4px 0 6px; border-bottom: 2px solid; margin-bottom: 8px; }
    .kb-sub  { font-size: 0.66rem; font-weight: 600; color: #6B7280; margin-top: 1px; }
    .kb-tot  { font-size: 0.8rem; font-weight: 700; margin-top: 3px; }
    /* Two lines per card: name on the left with the amount top-right, and the
       owner · region · month line beneath. A grid, so the amount can sit on the
       first row even though it comes last in the markup. */
    .kb-card { background: #1E1E2E; border-radius: 5px; padding: 4px 8px 5px;
               margin-bottom: 3px; border-left: 3px solid;
               display: grid; grid-template-columns: minmax(0, 1fr) auto;
               column-gap: 8px; align-items: baseline; }
    .kb-name { grid-column: 1; font-weight: 700; font-size: 0.8rem; color: #E2E8F0;
               line-height: 1.25; white-space: nowrap; overflow: hidden;
               text-overflow: ellipsis; }
    .kb-amt  { grid-column: 2; grid-row: 1; font-size: 0.8rem; font-weight: 800;
               line-height: 1.25; text-align: right; }
    .kb-meta { grid-column: 1 / -1; font-size: 0.66rem; color: #9CA3AF;
               line-height: 1.2; white-space: nowrap; overflow: hidden;
               text-overflow: ellipsis; }
    /* Revisit: ONE card for every parked proposal, a line per deal. */
    .kb-revisit { display: block; padding: 5px 9px 6px; }
    .kb-line { display: flex; justify-content: space-between; gap: 8px;
               font-size: 0.8rem; line-height: 1.5; color: #E2E8F0; font-weight: 700; }
    .kb-line span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    /* Recent conversations: a row of the same compact cards, with a third line for
       the next step / last note. */
    .rc-sub  { font-size: 0.78rem; color: #6B7280; margin: -4px 0 8px; }
    .rc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
               gap: 4px 10px; }
    .rc-step { grid-column: 1 / -1; font-size: 0.68rem; color: #CBD5E1; line-height: 1.25;
               margin-top: 1px; white-space: nowrap; overflow: hidden;
               text-overflow: ellipsis; }
    .kb-more { font-size: 0.74rem; color: #6B7280; padding: 2px 2px 0; }
    .kb-empty { font-size: 0.78rem; color: #9CA3AF; padding: 10px 2px; }
    .kb-note { font-size: 0.7rem; color: #9CA3AF; margin-top: 8px; }
</style>
""", unsafe_allow_html=True)


def _tile(icon, title, desc, page, label, locked=False, tone=None):
    """One card. Same shape everywhere so the row lines up. `tone` paints it as a
    solid coloured tile (the All-e rail); the marker span is what the CSS finds."""
    with st.container(border=True):
        st.markdown(
            (f'<span class="tm tm-{tone}"></span>' if tone else '')
            + f'<div class="tile-icon">{icon}</div>'
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


def _k(x):
    """$1.14M / $229K / $0."""
    if not x:
        return "$0"
    return f"${x / 1_000_000:,.2f}M" if x >= 1_000_000 else f"${x / 1_000:,.0f}K"


def _pipeline_panel():
    """All-e proposal board: counts, per-deal revenue and column totals, open to
    everyone on the viewer list (Prem, 4 Nov: option 1 — no password on the
    board). Never lets a sheet problem break the landing page."""
    import html as _h
    try:
        from services.home_pipeline import load_headline
        d = load_headline()
    except Exception:
        st.caption("Pipeline numbers are unavailable right now.")
        return
    if st.query_params.get("diag"):
        st.caption(f"diag: {d.get('diag', 'no diag in this build')}")

    CAP = 10  # cards are compact enough to show every deal; extras collapse to "+N more"
    cols = [("Revisit", "Revisit", "#8B5CF6", "🔁", "None", "proposal sent, no response"),
            (">60", "> 60 days", "#F59E0B", "🟡", "None", ""),
            ("<60", "< 60 days", "#3B82F6", "🔵", "None sent in the last 60 days", ""),
            ("Won", "Won", "#10B981", "✅", "None", ""),
            ("Lost", "Lost", "#EF4444", "❌", "None", "")]

    def card(c, color):
        meta = " · ".join(x for x in (c["owner"], c["region"], c["month"]) if x)
        amt = ('<div class="kb-amt" style="color:' + color + '">'
               + (_k(c["rev"]) if c["rev"] else "—") + '</div>')
        return (f'<div class="kb-card" style="border-color:{color}">'
                f'<div class="kb-name">{_h.escape(c["name"])}</div>'
                f'<div class="kb-meta">{_h.escape(meta) or "&nbsp;"}</div>{amt}</div>')

    out = []
    for key, label, color, icon, empty, sub in cols:
        items = d["stages"][key]
        total = sum(c["rev"] or 0 for c in items)
        tot = _k(total)
        if key == "Revisit" and items:
            lines = "".join(
                f'<div class="kb-line" title="{_h.escape(" · ".join(x for x in (c["owner"], c["region"], c["month"]) if x))}">'
                f'<span>{_h.escape(c["name"])}</span>'
                f'<b style="color:{color}">{_k(c["rev"]) if c["rev"] else "—"}</b></div>'
                for c in items)
            body = f'<div class="kb-card kb-revisit" style="border-color:{color}">{lines}</div>'
        else:
            body = "".join(card(c, color) for c in items[:CAP])
        if len(items) > CAP:
            body += f'<div class="kb-more">+{len(items) - CAP} more</div>'
        if not items:
            body = f'<div class="kb-empty">{empty}</div>'
        out.append(
            '<div><div class="kb-head" style="border-color:' + color + ';color:' + color + '">'
            f'{icon} {label} ({len(items)})'
            + (f'<div class="kb-sub">{sub}</div>' if sub else '')
            + f'<div class="kb-tot">{tot}</div></div>{body}</div>')

    p1 = f"{d['proposals'] / d['leads']:.0%}" if d["leads"] else "—"
    p2 = f"{d['won'] / d['proposals']:.0%}" if d["proposals"] else "—"
    note = ""
    if d["rev_missing"]:
        note = ('<div class="kb-note">' + ", ".join(d["rev_missing"])
                + ': value not on the sheet yet.</div>')
    st.markdown(
        f'<div class="kb-sum"><b>{d["leads"]}</b> net-new leads → <b>{d["proposals"]}</b> proposals '
        f'({p1}) → <b>{d["won"]}</b> won ({p2})</div>'
        '<div class="kb-grid">' + "".join(out) + '</div>' + note,
        unsafe_allow_html=True)



def _recent_panel():
    """Good conversations from the last 30 days that have not reached a proposal yet.
    Rendered below the board so the board paints first (the deck read can take a few
    seconds). Silent on any failure: the board above is the point of this page."""
    import html as _h
    try:
        from services.home_recent import load_recent
        items = load_recent()
    except Exception:
        return
    if not items:
        return
    CAP, color = 8, "#14B8A6"
    cards = ""
    for x in items[:CAP]:
        meta = " · ".join(p for p in (x["owner"], x["where"], f'{x["date"]:%d %b}') if p)
        step = _h.escape(x["step"] or "")
        cards += (
            f'<div class="kb-card" style="border-color:{color}" title="{step}">'
            f'<div class="kb-name">{_h.escape(x["name"])}</div>'
            + (f'<div class="kb-amt" style="color:{color}">{_k(x["value"])}</div>' if x["value"] else "")
            + f'<div class="kb-meta">{_h.escape(meta)}</div>'
            + (f'<div class="rc-step">{step}</div>' if step else "") + '</div>')
    more = (f'<div class="kb-more">+{len(items) - CAP} more</div>' if len(items) > CAP else "")
    _label(f"Recent conversations ({len(items)})")
    st.markdown('<div class="rc-sub">Active leads spoken to in the last 30 days that have not '
                'reached a proposal yet.</div><div class="rc-grid">' + cards + '</div>' + more,
                unsafe_allow_html=True)


st.markdown('<p class="main-header">SalesHub</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Everything a salesperson needs — briefs, '
            'collateral, pipeline and outreach.</p>', unsafe_allow_html=True)

# ── All-e ─────────────────────────────────────────────────────────────────────
# Promoted above Cross-Product: it is where the team actually works and holds
# the only tiles most people need. The restricted sections sit below.

_left, _right = st.columns([2, 7], gap="large")
with _left:
    _label("All-e")
    c1 = st.container()
    c2 = st.container()
    c3 = st.container()
    c4 = st.container()
with _right:
    _label("All-e pipeline &nbsp;<span style='text-transform:none;letter-spacing:0;font-weight:600;font-size:0.8rem;color:#6B7280'>(Proposal and after stage only)</span>")
    _pipeline_panel()
    _recent_panel()

with c1:
    _tile("📋", "Prospect Brief", "Pre-call two-pager research",
          "views/9_prospect_brief.py", "Create →", tone="indigo")
with c2:
    # Open, unlike the Knowledge Base below — onboarding material the sales
    # team needs cannot sit behind the team password (Prem, 25 Oct).
    _tile("🎒", "Key Collateral", "GTM Immersion · videos · creds",
          "views/6_collateral.py", "Open →", tone="amber")
with c3:
    _tile("🤖", "All-e", "Presales pipeline &amp; deals",
          "views/2_alle.py", "Open →", tone="teal")
with c4:
    # Gated page inside an open section — the pill warns before the click.
    _tile("📧", "CRM", "Contacts, campaigns &amp; intent",
          "views/3_crm.py", "Open →", locked=True, tone="rose")
    # The intent list is the sheet salespeople actually work from — who
    # engaged, at what level, and who not to contact. The raw outreach log
    # (every send, every beacon) is plumbing and was the only thing linked
    # here, which is why nobody could find the list (Prem, 25 Oct).
    # The age matters as much as the link: sales act on these tiers, and a
    # sheet that silently stopped refreshing looks identical to one that is
    # current. A nightly job rewrites it; this says when it last ran.
    _age = ""
    try:
        from datetime import datetime as _dt, timezone as _tz
        _st = json.loads((Path(__file__).parent.parent / "content"
                          / "intent_refresh.json").read_text("utf-8"))
        _hrs = (_dt.now(_tz.utc) - _dt.strptime(
            _st["refreshed_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=_tz.utc)).total_seconds() / 3600
        _when = ("just now" if _hrs < 1 else
                 f"{int(_hrs)}h ago" if _hrs < 48 else
                 f"{int(_hrs / 24)}d ago")
        _col = "#9CA3AF" if _hrs < 36 else "#D97706"
        _age = (f'<span style="color:{_col}">· refreshed {_when}</span>')
    except Exception:
        pass
    st.markdown(
        '<div style="font-size:0.78rem;margin-top:6px;line-height:1.7">'
        '<a href="https://docs.google.com/spreadsheets/d/'
        '1zGr-Brg_uuHuICDgJJ36ctUnnf7Yluw1Yd0fAy44AaM/edit" target="_blank">'
        '<b>Who to follow up ↗</b></a> ' + _age + '<br>'
        '<a href="https://docs.google.com/spreadsheets/d/'
        '1Vcu7ZkAjGbzpKH2CUGoSuLUGIfwYBT-GlpNN0zMKJMY/edit" target="_blank" '
        'style="color:#9CA3AF">Raw outreach log ↗</a></div>',
        unsafe_allow_html=True)

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

# ── Monthly Ruminations ──────────────────────────────────────────────────────
# Headlines and dates only — one line each, read from the exported index.
# The emails live in Key Collateral; this is a prompt that they exist and are
# forwardable, not a reading list (Prem, 25 Oct).
_RUMI_IDX = Path(__file__).parent.parent / "content" / "collateral" / "ruminations" / "index.json"
_rumi = []
try:
    _rumi = json.loads(_RUMI_IDX.read_text(encoding="utf-8"))
except Exception:
    _rumi = []

if _rumi:
    _label("Monthly Ruminations &nbsp;·&nbsp; forward one to a customer")
    st.caption("To send one: open it in **Key Collateral** and download the "
               "PDF, then attach it to your own email. Forwarding the original "
               "from insights@ in your inbox works too, and keeps your name on "
               "the thread.")
    # "Send to" on the right: the headline alone does not tell anyone which
    # customer this one suits, which is what stops it being forwarded.
    _rows = "".join(
        f'<div class="rumi-row">'
        f'<span class="rumi-date">{str(r.get("sent",""))[3:].strip()}</span>'
        f'<span class="rumi-subj"><a href="collateral?r={r.get("n","")}" '
        f'target="_self">{r.get("subject","")}</a></span>'
        f'<span class="rumi-about">{r.get("send_to","")}</span>'
        f'</div>'
        for r in sorted(_rumi, key=lambda x: x.get("n", 0), reverse=True))
    st.markdown(_rows, unsafe_allow_html=True)
    _r1, _ = st.columns([1, 3])
    with _r1:
        st.page_link("views/6_collateral.py", label="Preview or download →")
    st.markdown("")

# ── Restricted ────────────────────────────────────────────────────────────────

# Resources sits here, not in the All-e row: it is cross-product reference
# material, which is how app.py has always grouped it (Prem, 25 Oct).
_label("Cross-product, Hoppr &amp; reference", locked=True)

r1, r2, r3, _ = st.columns([1, 1, 1, 1])
with r1:
    _tile("📋", "Pipeline", "Meetings &amp; proposals — All-e + Hoppr",
          "views/1_pipeline.py", "Open Pipeline →", locked=True)
with r2:
    _tile("📊", "Hoppr", "Usage, accounts &amp; MCP Beta",
          "views/7_hoppr.py", "Open Hoppr →", locked=True)
with r3:
    _tile("🧠", "Knowledge Base", "Source docs, decks &amp; KB health",
          "views/5_resources.py", "Open the KB →", locked=True)

st.markdown("")

# ── Security & compliance ────────────────────────────────────────────────────
# Sits at the foot of the page (Prem, 5 Nov: it was crowding the fold).
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
    st.page_link("views/6_collateral.py", label="Get the certificates →")

st.markdown("")
