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
     "Short films to send a prospect, or to watch before a first call."),
    ("Creds Deck", "📊",
     "Who Graas is, who we work with, what we've shipped. The deck you leave "
     "behind."),
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
        bits += [str(t) for t in tags if str(t).strip()]
        if bits:
            st.caption(" · ".join(bits))
        if item.get("needs_review"):
            st.caption("⚠️ Pulled from a past campaign link — confirm this is "
                       "the right one before sending it to a customer.")


st.markdown("## 🎒 Key Collateral")
st.caption("Open to the whole team — no password. The decks, courses and "
           "videos a salesperson needs.")

_items = _sales_items()

for _name, _icon, _blurb in SECTIONS:
    st.markdown(f"### {_icon} {_name}")
    st.caption(_blurb)
    _group = _items.get(_name, [])
    if not _group:
        st.info(f"No {_name} added yet. Add an entry to "
                "`content/resources.json` with "
                f"`\"category\": \"{_name}\"` and `\"sales_facing\": true`.")
    elif len(_group) == 1:
        _card(_group[0])
    else:
        _cols = st.columns(min(len(_group), 3))
        for _i, _r in enumerate(_group):
            with _cols[_i % len(_cols)]:
                _card(_r)
    st.markdown("")

st.markdown("---")
st.caption("Pipeline decks, the Knowledge Base and customer proposals are in "
           "**Resources**, which needs the team password.")
