"""Resources — Knowledge Base (Drive-backed) + Manual decks & docs.

Top section is the Knowledge Base, auto-populated from Drive:
  SalesHub Shared Drive / KB /
    1. eCom/
    2. GT-Offline/
    3. Graas Products/

Each bucket subfolder lists its Google Docs as tiles. To add to the KB,
drop a Doc in the appropriate Drive subfolder — it appears here on the
next 5-min cache refresh.

Bottom section is the existing manual resources grid (decks, docs from
content/resources.json), kept for slide decks / external links that
aren't Google Docs.
"""

import os
import re
import sys
import streamlit as st
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(dotenv_path=str(Path(__file__).resolve().parent.parent / ".env"))

st.set_page_config(page_title="Resources | Graas", page_icon="📚", layout="wide")

# ── Load resources ────────────────────────────────────────────────────────────

RESOURCES_PATH = Path(__file__).parent.parent / "content" / "resources.json"

def load_resources():
    if RESOURCES_PATH.exists():
        with open(RESOURCES_PATH) as f:
            return json.load(f)
    return {"decks": [], "docs": []}


def save_resources(data):
    with open(RESOURCES_PATH, "w") as f:
        json.dump(data, f, indent=2)


# ── Page ──────────────────────────────────────────────────────────────────────

st.markdown("## 📚 Resources")
st.caption("Knowledge Base (Drive-backed, auto) + manual decks & docs")


# ═════════════════════════════════════════════════════════════════════════════
# KNOWLEDGE BASE — auto-populated from Drive (top section)
# ═════════════════════════════════════════════════════════════════════════════

KB_FOLDER_ID = os.getenv(
    "KB_FOLDER_ID",
    "1gP7i2I6oKzXVKtD-nNZyCkiSM3imNANh",  # SalesHub Shared Drive / KB
)


def _clean_bucket_label(name: str) -> str:
    """Strip 'N. ' prefix and trailing slash from a bucket folder name."""
    s = re.sub(r"^\s*\d+\.\s*", "", name).strip()
    if s.endswith("/"):
        s = s[:-1].strip()
    return s


@st.cache_data(ttl=300)
def _list_kb_buckets() -> list:
    """Return KB bucket subfolders sorted by their numbered prefix."""
    from services.sheets_client import list_drive_subfolders
    subs = list_drive_subfolders(KB_FOLDER_ID)
    # Sort by numbered prefix when present, else alphabetical
    def _sort_key(s):
        m = re.match(r"^\s*(\d+)\.", s["name"])
        return (int(m.group(1)) if m else 999, s["name"].lower())
    return sorted(subs, key=_sort_key)


@st.cache_data(ttl=300)
def _list_bucket_docs(bucket_id: str) -> list:
    """Docs in a bucket folder, newest first."""
    from services.sheets_client import list_drive_folder_docs
    return list_drive_folder_docs(bucket_id)


st.markdown("### 🧠 Knowledge Base")
st.caption(
    f"Curated reference Docs in the SalesHub Shared Drive. To add: drop a Google "
    f"Doc in the appropriate bucket subfolder, then refresh."
)

_buckets = _list_kb_buckets()
if not _buckets:
    st.warning(
        f"No bucket subfolders found in the KB folder (`{KB_FOLDER_ID}`). "
        f"Check the folder exists in the Shared Drive and the service account "
        f"has access."
    )
else:
    _kb_refresh_col, _ = st.columns([1, 8])
    with _kb_refresh_col:
        if st.button("🔄 Refresh KB", key="kb_refresh"):
            _list_kb_buckets.clear()
            _list_bucket_docs.clear()
            st.rerun()

    for _bucket in _buckets:
        _bucket_label = _clean_bucket_label(_bucket["name"])
        _docs = _list_bucket_docs(_bucket["id"])
        with st.expander(f"**{_bucket_label}**  ·  {len(_docs)} doc(s)", expanded=True):
            if not _docs:
                st.caption("_Empty — drop a Doc into this bucket to populate it._")
            else:
                # 4-col tiles, compact
                _rows = [_docs[i:i + 4] for i in range(0, len(_docs), 4)]
                for _row in _rows:
                    _cols = st.columns(4)
                    for _col, _d in zip(_cols, _row):
                        _url = f"https://docs.google.com/document/d/{_d['id']}/edit"
                        _mod = (_d.get("modified_time") or "")[:10]  # YYYY-MM-DD slice
                        with _col:
                            with st.container(border=True):
                                st.markdown(
                                    f"<div style='font-size: 0.9em; font-weight: 600; "
                                    f"line-height: 1.25; margin-bottom: 2px;'>{_d['name']}</div>"
                                    f"<div style='font-size: 0.7em; color: #888; "
                                    f"margin-bottom: 4px;'>Last modified: {_mod}</div>"
                                    f"<a href='{_url}' target='_blank' "
                                    f"style='font-size: 0.78em;'>Open →</a>",
                                    unsafe_allow_html=True,
                                )

st.markdown("---")


# ═════════════════════════════════════════════════════════════════════════════
# MANUAL RESOURCES — existing card grid (decks, slides, external links)
# ═════════════════════════════════════════════════════════════════════════════

st.markdown("### 📂 Decks & Docs")
st.caption("Manually-curated decks, slides, and external links")

resources = load_resources()
decks = resources.get("decks", [])
docs = resources.get("docs", [])

# ── Add new resource ──────────────────────────────────────────────────────────

with st.expander("➕ Add a resource", expanded=False):
    with st.form("add_resource"):
        col1, col2 = st.columns([2, 1])
        with col1:
            new_title = st.text_input("Title", placeholder="All-e Business Overview — Jan 2026")
            new_url = st.text_input("URL", placeholder="https://docs.google.com/presentation/d/...")
            new_description = st.text_area("Description (optional)", height=80)
        with col2:
            new_type = st.selectbox("Type", ["Google Slides", "Google Doc", "PDF", "Notion", "Other"])
            new_tags = st.text_input("Tags (comma-separated)", placeholder="all-e, business review, Q1")

        submitted = st.form_submit_button("Add Resource", use_container_width=True)
        if submitted and new_title and new_url:
            new_entry = {
                "title": new_title.strip(),
                "description": new_description.strip(),
                "url": new_url.strip(),
                "type": new_type,
                "added": datetime.now().strftime("%Y-%m-%d"),
                "tags": [t.strip() for t in new_tags.split(",") if t.strip()],
            }
            resources["decks"].append(new_entry)
            save_resources(resources)
            st.success(f"Added: **{new_title}**")
            st.rerun()

st.markdown("---")

# ── Type icons ────────────────────────────────────────────────────────────────

TYPE_ICONS = {
    "Google Slides": "📊",
    "Google Doc": "📄",
    "PDF": "📑",
    "Notion": "📝",
    "Other": "🔗",
}

TAG_COLORS = {
    "all-e": "#4F46E5",
    "business review": "#7C3AED",
    "Q1": "#2563EB",
    "Q2": "#0891B2",
    "2026": "#059669",
}


def _tag_badge(tag: str) -> str:
    color = TAG_COLORS.get(tag.lower(), "#6B7280")
    return (
        f'<span style="background:{color};color:white;border-radius:4px;'
        f'padding:2px 8px;font-size:0.75rem;margin-right:4px;">{tag}</span>'
    )


# ── Render decks ──────────────────────────────────────────────────────────────

all_items = resources.get("decks", []) + resources.get("docs", [])

if not all_items:
    st.info("No resources yet. Add one above.")
else:
    # Search / filter
    search = st.text_input("🔍 Filter", placeholder="Search by title, tag, or type...", label_visibility="collapsed")

    filtered = all_items
    if search:
        q = search.lower()
        filtered = [
            r for r in all_items
            if q in r["title"].lower()
            or q in r.get("description", "").lower()
            or any(q in t.lower() for t in r.get("tags", []))
            or q in r.get("type", "").lower()
        ]

    if not filtered:
        st.warning("No resources match that search.")
    else:
        # Render as cards — 2 per row
        for i in range(0, len(filtered), 2):
            row = filtered[i:i+2]
            cols = st.columns(len(row))
            for col, item in zip(cols, row):
                with col:
                    icon = TYPE_ICONS.get(item.get("type", "Other"), "🔗")
                    tags_html = " ".join(_tag_badge(t) for t in item.get("tags", []))
                    added = item.get("added", "")

                    st.markdown(f"""
<div style="border:1px solid #E5E7EB;border-radius:10px;padding:18px 20px;margin-bottom:12px;height:100%;">
  <div style="font-size:1.05rem;font-weight:600;margin-bottom:4px;">{icon} {item['title']}</div>
  <div style="font-size:0.85rem;color:#6B7280;margin-bottom:10px;">{item.get('description', '')}</div>
  <div style="margin-bottom:10px;">{tags_html}</div>
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <span style="font-size:0.78rem;color:#9CA3AF;">{item.get('type','')}{(' · Added ' + added) if added else ''}</span>
    <a href="{item['url']}" target="_blank" style="background:#4F46E5;color:white;padding:5px 14px;border-radius:6px;text-decoration:none;font-size:0.85rem;">Open →</a>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Sidebar: quick links ──────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 📚 Quick Links")
    for item in all_items[:8]:
        icon = TYPE_ICONS.get(item.get("type", "Other"), "🔗")
        st.markdown(f"[{icon} {item['title']}]({item['url']})")
