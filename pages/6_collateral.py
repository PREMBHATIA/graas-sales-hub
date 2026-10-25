"""Sales collateral — the OPEN page.

Resources (5_resources.py) is gated behind the team password, and the sales
team doesn't have it (Prem, 25 Oct). Onboarding material that every
salesperson needs cannot live behind a lock, so it lives here instead.

This page deliberately shares the Resources store (content/resources.json)
rather than keeping a second list that drifts, but it renders ONLY items
explicitly marked `"sales_facing": true`. That flag is the whole security
boundary: an item is visible here because someone decided it should be, never
because it happened to be in the file. Nothing is listed by default.
"""

from pathlib import Path
import json

import streamlit as st

st.set_page_config(page_title="Sales Collateral | Graas", page_icon="🎒",
                   layout="wide")

RESOURCES_PATH = Path(__file__).parent.parent / "content" / "resources.json"


@st.cache_data(ttl=300, show_spinner=False)
def _sales_items():
    """(featured, rest) — only entries flagged sales_facing.

    Returns empty lists on any read failure rather than raising: a missing or
    malformed file should show "nothing here yet", not a stack trace, but it
    must never fall back to showing everything.
    """
    try:
        data = json.loads(RESOURCES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return [], []
    items = [r for r in (data.get("decks", []) + data.get("docs", []))
             if isinstance(r, dict) and r.get("sales_facing") is True]
    return ([r for r in items if r.get("featured")],
            [r for r in items if not r.get("featured")])


def _tags(item):
    t = item.get("tags") or []
    if isinstance(t, str):                      # older rows stored a str(list)
        t = [x.strip(" '\"[]") for x in t.split(",")]
    return [str(x) for x in t if str(x).strip()]


def _card(item, big=False):
    with st.container(border=True):
        if big:
            st.markdown(f"#### [{item.get('title', 'Untitled')}]({item.get('url', '#')})")
        else:
            st.markdown(f"**[{item.get('title', 'Untitled')}]({item.get('url', '#')})**")
        if item.get("description"):
            st.markdown(item["description"])
        bits = _tags(item)
        if item.get("type"):
            bits = [item["type"]] + bits
        if bits:
            st.caption(" · ".join(bits))


st.markdown("## 🎒 Sales Collateral")
st.caption("Everything a salesperson needs, open to the whole team — no "
           "password. Decks, courses and links you can share internally.")

_feat, _rest = _sales_items()

if not _feat and not _rest:
    st.info(
        "Nothing here yet. Collateral is added in **Resources** — set "
        "`\"sales_facing\": true` on an entry in `content/resources.json` and "
        "it appears on this page. Items without that flag stay in Resources, "
        "which is password-protected."
    )
else:
    if _feat:
        st.markdown("### 🚀 Start here")
        for _f in _feat:
            _card(_f, big=True)
        st.markdown("")
    if _rest:
        st.markdown("### 📂 More collateral")
        _cols = st.columns(2)
        for _i, _r in enumerate(_rest):
            with _cols[_i % 2]:
                _card(_r)

st.markdown("---")
st.caption("Looking for pipeline decks, the Knowledge Base or customer "
           "proposals? Those are in **Resources** and need the team password.")
