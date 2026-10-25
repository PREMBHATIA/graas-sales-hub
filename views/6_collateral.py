"""Key Collateral — the OPEN page under All-e.

Resources (5_resources.py) is gated behind the team password and the sales
team doesn't have it (Prem, 25 Oct), so onboarding material every salesperson
needs cannot live there. It lives here instead.

This page shares the Resources store (content/resources.json) rather than
keeping a second list that drifts, but renders ONLY entries flagged
`"sales_facing": true`. That flag is the whole boundary: an item appears here
because someone decided it should, never because it happens to be in the file.

Three fixed sections, in this order — GTM Immersion, Videos, Creds Deck — set
per item with `"category"`. A section with nothing in it still renders, saying
what's missing, so a gap is visible rather than silently absent.
"""

from pathlib import Path
import json

import streamlit as st

st.set_page_config(page_title="Key Collateral | Graas", page_icon="🎒",
                   layout="wide")

RESOURCES_PATH = Path(__file__).parent.parent / "content" / "resources.json"

# Order matters — this is the order a new salesperson should meet them in.
SECTIONS = [
    ("GTM Immersion", "🎓",
     "The course. Routes to market, the Agent Fit Test, what we don't sell, "
     "the GT leak map. Start here if you're new."),
    ("Videos", "🎬",
     "Customer stories to send a prospect, or to watch before a first call. "
     "✅ All safe to share with customers."),
    ("Security & Compliance", "🔐",
     "SOC 2, ISO 27001, GDPR, PDPA. Procurement and security reviews ask "
     "for these — send the link, not the file."),
    ("Creds Deck", "📊",
     "Who Graas is, who we work with, what we've shipped. The deck you leave "
     "behind."),
]

# Self-contained HTML reports served from the repo rather than linked out —
# no hosting step, no link to go stale, and they work offline. Keep them
# self-contained (inline CSS, no external src) or they'll render broken.
LOCAL_REPORTS = [
    {"title": "2026 Funnel Overview — All-e, Jan to Sept",
     "file": "content/collateral/alle_funnel_overview_2026.html",
     "description": "104 net-new leads, 20 proposals, 5 won — and the same "
                    "funnel broken down by vertical. Trimmed to the headline "
                    "numbers; the full analysis sits with Prem.",
     "audience": "Internal only"},
]


@st.cache_data(ttl=300, show_spinner=False)
def _sales_items():
    """Sales-facing entries grouped by category.

    Empty on any read failure rather than raising — a missing or malformed
    file should read as "nothing here yet", never as a stack trace, and must
    never fall back to showing everything.
    """
    try:
        data = json.loads(RESOURCES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for r in (data.get("decks", []) + data.get("docs", [])):
        if isinstance(r, dict) and r.get("sales_facing") is True:
            out.setdefault(str(r.get("category", "")).strip(), []).append(r)
    return out


def _card_compact(item):
    """Title + one line. Used for Videos, where the per-card type, tag and
    audience captions tripled the height of a link and a sentence — and said
    the same thing on every card, so the section header says it once."""
    st.markdown(f"**[{item.get('title', 'Untitled')}]({item.get('url', '#')})**  \n"
                f"<span style='font-size:0.82rem;color:#6B7280'>"
                f"{item.get('description', '')}</span>",
                unsafe_allow_html=True)


def _card(item):
    with st.container(border=True):
        st.markdown(f"**[{item.get('title', 'Untitled')}]({item.get('url', '#')})**")
        if item.get("description"):
            st.markdown(item["description"])
        bits = []
        if item.get("type"):
            bits.append(item["type"])
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip(" '\"[]") for t in tags.split(",")]
        # Case-insensitive dedupe: type "Video" plus tag "video" rendered as
        # "Video · video · customer story".
        _seen = {b.lower() for b in bits}
        for _t in (str(t).strip() for t in tags):
            if _t and _t.lower() not in _seen:
                _seen.add(_t.lower())
                bits.append(_t)
        if bits:
            st.caption(" · ".join(bits))
        # Audience is shown, not implied. This page is ungated and a
        # salesperson will forward whatever is on it — the GTM course and the
        # funnel analysis are internal, the creds deck and the customer
        # stories are not, and nothing here should leave that to guesswork.
        _aud = str(item.get("audience", "")).strip()
        if _aud.lower().startswith("internal"):
            st.caption("🔒 **Internal only** — do not send to a customer.")
        elif _aud:
            st.caption(f"✅ {_aud}")
        if item.get("needs_review"):
            st.caption("⚠️ Pulled from a past campaign link — confirm this is "
                       "the right one before sending it to a customer.")


st.markdown("## 🎒 Key Collateral")
st.caption("Open to the whole team — no password. The decks, courses and "
           "videos a salesperson needs.")

_root_dir = Path(__file__).parent.parent
_items = _sales_items()

for _name, _icon, _blurb in SECTIONS:
    st.markdown(f"### {_icon} {_name}")
    st.caption(_blurb)
    _group = _items.get(_name, [])
    if not _group:
        st.info(f"No {_name} added yet. Add an entry to "
                "`content/resources.json` with "
                f"`\"category\": \"{_name}\"` and `\"sales_facing\": true`.")
    elif _name == "Videos":
        # Compact: these are all customer-safe and all the same type, so the
        # per-card badges were noise. Said once, above.
        _cols = st.columns(min(len(_group), 3))
        for _i, _r in enumerate(_group):
            with _cols[_i % len(_cols)]:
                _card_compact(_r)
    elif len(_group) == 1:
        _card(_group[0])
    else:
        _cols = st.columns(min(len(_group), 3))
        for _i, _r in enumerate(_group):
            with _cols[_i % len(_cols)]:
                _card(_r)
    st.markdown("")

# ── Monthly Ruminations ──────────────────────────────────────────────────────
# The Index emails, exported from the Sends log into the repo. Served as files
# rather than read from Sheets: this page is open and must stay fast, and the
# Creatives shelf that holds them otherwise is behind the CRM password.
#
# These are the composed bodies, before send-time link rewriting, so they carry
# no tracking pixel and no recipient id — checked, and it matters, because the
# whole point is forwarding them to a customer.
_RUMI = _root_dir / "content" / "collateral" / "ruminations" / "index.json"
_rumi = []
try:
    _rumi = json.loads(_RUMI.read_text(encoding="utf-8"))
except Exception:
    _rumi = []

if _rumi:
    st.markdown("### 📬 Monthly Ruminations")
    st.caption("The Index emails, newest first. Forward one to a customer — "
               "or open the original in your inbox from **insights@** and "
               "forward that, which keeps your name on it. No tracking pixel "
               "in these copies. ✅ Safe to share.")
    for _r in sorted(_rumi, key=lambda x: x.get("n", 0), reverse=True):
        _rp = _root_dir / _r.get("file", "")
        if not _rp.exists():
            continue
        with st.container(border=True):
            st.markdown(f"**{_r.get('subject', 'Untitled')}**")
            st.caption(f"Sent {_r.get('sent', '')} · "
                       f"{_r.get('recipients', 0)} recipients")
            if _r.get("sent_subject"):
                # Say it plainly rather than quietly showing a subject that
                # differs from the one in anyone's inbox.
                st.caption(f"⚠️ Went out as *“{_r['sent_subject']}”* — "
                           "grammar corrected here only.")
            try:
                _rhtml = _rp.read_text(encoding="utf-8")
            except Exception as _e:
                st.warning(f"Couldn't read it: {_e}")
                continue
            _q1, _q2, _ = st.columns([1, 1, 3])
            with _q1:
                st.download_button("⬇️ HTML", _rhtml.encode("utf-8"),
                                   file_name=_rp.name, mime="text/html",
                                   key=f"rumi_dl_{_r.get('n')}")
            with _q2:
                _rshow = st.toggle("Preview", key=f"rumi_pv_{_r.get('n')}")
            if _rshow:
                import streamlit.components.v1 as _cmp_r
                _cmp_r.html(_rhtml, height=700, scrolling=True)
    st.markdown("")

# ── Reports served from the repo ─────────────────────────────────────────────
_root = _root_dir
for _rep in LOCAL_REPORTS:
    _path = _root / _rep["file"]
    if not _path.exists():
        continue
    st.markdown("### 📈 Funnel & performance")
    st.caption("How the sales engine is actually doing. Read it before your "
               "first pipeline review.")
    with st.container(border=True):
        st.markdown(f"**{_rep['title']}**")
        st.markdown(_rep["description"])
        st.caption("🔒 **Internal only** — do not send to a customer. Names "
                   "live deals, lost deals and why they were lost.")
        try:
            _html = _path.read_text(encoding="utf-8")
        except Exception as _e:
            st.warning(f"Couldn't read the report: {_e}")
            continue
        _c1, _c2, _ = st.columns([1, 1, 3])
        with _c1:
            st.download_button("⬇️ HTML", _html.encode("utf-8"),
                               file_name=_path.name, mime="text/html",
                               key=f"rep_dl_{_path.stem}")
        with _c2:
            _open = st.toggle("Read it here", key=f"rep_pv_{_path.stem}")
        if _open:
            import streamlit.components.v1 as _cmp
            _cmp.html(_html, height=760, scrolling=True)
    st.markdown("")

st.markdown("---")
st.caption("Pipeline decks, the Knowledge Base and customer proposals are in "
           "**Resources**, which needs the team password.")
