"""Proposal Bank — a searchable summary of every proposal we've sent.

Reads the Reference Proposals Drive folder and, for each proposal, extracts a
compact profile with an LLM (cached): brand · use case · who the agent faces ·
which surfaces (WhatsApp / Website / In-app / Voice). The extraction is
auto-derived from the doc text; a proposal dropped into the folder shows up on
the next scan. Corrections can be layered on later — the source of truth is the
doc itself.
"""

import json
import os
import re
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

st.set_page_config(page_title="Proposal Bank | Graas", page_icon="📑", layout="wide")

# ── Anthropic key (same pattern as the other All-e pages) ─────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    try:
        ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        ANTHROPIC_API_KEY = ""

REFERENCE_PROPOSALS_FOLDER_ID = os.getenv(
    "REFERENCE_PROPOSALS_FOLDER_ID", "1tBMrcpiIDVhg5e0-N1ytjuzbDexQyheX"
)
EXTRACT_MODEL = os.getenv("PROPOSAL_BANK_MODEL", "claude-sonnet-4-6")

_SURFACES = ["WhatsApp", "Website", "In-app", "Voice", "Email", "Marketplace"]
# The Graas offering a proposal primarily maps to — same 4-pillar vocabulary as
# the Prospect Brief. Single DOMINANT pillar per proposal (keeps the column +
# filter crisp); the summary carries any secondary pillar.
_PILLARS = ["Search & Discovery", "Sales & Ordering", "Channel Operations", "Decision Intelligence"]

# Hand corrections that WIN over the LLM extraction — keyed by a distinctive
# substring of the proposal's filename. The LLM over-tags when a doc mentions
# many parties; this is where we set the record straight (survives redeploys
# because it's code). Prem flags a miss → add a line here.
MANUAL_OVERRIDES = {
    "PaidPOC": {
        "brand": "Castrol · Voice",
        "use_case": "Retailer",
        "facing": "External",
        "surfaces": ["Voice", "WhatsApp"],
        "summary": "Voice + WhatsApp agent for 40K rural retailers — order-taking + scheme comms in Hindi/English, writes to Elevate DMS. Revenue-uplift play (~76.8K extra orders/yr).",
        "pillar": "Sales & Ordering",
    },
    "Castrol COPS": {
        "brand": "Castrol · COPs",
        "use_case": "RevOps (order processing)",
        "facing": "Internal",
        "surfaces": ["Email"],
        "summary": "Internal RevOps agent — parses B2B/ILS order emails + POs, runs the 13-point validation against Keris/ODT, preps the COPS sheet for one-click human sign-off before ERP entry. TAT 45min → <10min.",
        "pillar": "Channel Operations",
    },
    "Canon": {
        "use_case": "Consumer",
        "facing": "External",
        "surfaces": ["Website", "Marketplace"],
        "summary": "Ad/QR-led consumer agent — chat about products & promos, then route to Amazon or nearby stores.",
        "pillar": "Search & Discovery",
    },
    "LK India": {
        "brand": "Lauritz Knudsen (LK)",
        "use_case": "Mixed",
        "facing": "External",
        "surfaces": ["WhatsApp", "Website", "Voice"],
        "summary": "WhatsApp ordering + SmartShop search + voice on one Commerce KG; BOQ-to-cart for contractors/retailers/homeowners across 5,000+ electrical SKUs.",
        "pillar": "Sales & Ordering",
    },
    # The one SEARCH-only proposal — no WhatsApp/ordering. Intent-led search on
    # havells.com via the Adobe Commerce SDK, over the Product KG. Consumer/D2C.
    "Havells": {
        "brand": "Havells (India)",
        "use_case": "Consumer",
        "facing": "External",
        "surfaces": ["Website", "Voice"],
        "summary": "Advanced intent-led search on havells.com (Adobe Commerce SDK) over a Product KG — cut null results ≥50% on Fans/Appliances/Circuit Protection. 6-wk D2C pilot.",
        "pillar": "Search & Discovery",
        "date": "2026-07-24",
    },
}

_SCHEMA = """{
  "brand": "the customer / brand the proposal is for (e.g. 'Nippon Paint', 'Tata 1mg', 'Castrol'). Strip 'Copy of', 'All-e', 'Proposal', dates.",
  "pillar": "The PRIMARY Graas offering this proposal maps to — pick the SINGLE dominant one: 'Search & Discovery' (intent search, product discovery, fitment, compare, cross-sell) | 'Sales & Ordering' (ordering, BOQ/SKU recognition, scheme, credit, pricing, voice/photo order capture) | 'Channel Operations' (OCR/invoice capture, push-to-ERP, order-email processing, fraud, first-contact/triage) | 'Decision Intelligence' (analytics/forecasts that feed a conversational action). A proposal may touch several — name only the dominant one.",
  "use_case": "Who the agent ULTIMATELY serves in the live interaction — pick the SINGLE dominant one: 'Consumer' (end shopper / D2C) | 'Retailer' | 'Distributor / Dealer' | 'Field agent'. Use 'Mixed' ONLY if two are truly co-equal. Do NOT list every party the doc mentions — a consumer agent that happens to route to retailers is still 'Consumer'.",
  "facing": "ONE of: 'External' (customer/partner-facing agent) | 'Internal' (employee/ops-facing) | 'Both'.",
  "surfaces": "array from ['WhatsApp','Website','In-app','Voice','Marketplace'] — the channels the agent runs on. Empty if unclear.",
  "summary": "ONE line, <=18 words — what the proposal actually proposes.",
  "date": "the proposal date if stated (YYYY-MM-DD or 'Mon YYYY'), else ''."
}"""


@st.cache_data(ttl=3600, show_spinner=False)
def _list_proposals():
    from services.sheets_client import list_drive_folder_docs
    docs = list_drive_folder_docs(REFERENCE_PROPOSALS_FOLDER_ID)
    return sorted(docs, key=lambda d: d["name"].lower())


def _clean_brand_from_name(name: str) -> str:
    n = re.sub(r"(?i)copy of|proposal|all-e|graas|poc|pilot|discovery|questionnaire|final|internal", "", name)
    n = re.sub(r"[_\-—]+", " ", n)
    n = re.sub(r"\b\d{1,2}\s*\w{0,4}\s*20\d{2}\b", "", n)  # dates
    n = re.sub(r"v\d+", "", n)
    return re.sub(r"\s+", " ", n).strip(" .·") or name


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


@st.cache_data(ttl=86400, show_spinner=False)
def _profile_proposal(doc_id: str, doc_name: str) -> dict:
    """LLM-extract the compact profile for one proposal. Cached 24h per doc."""
    from services.sheets_client import fetch_drive_doc_text
    fallback = {
        "brand": _clean_brand_from_name(doc_name), "pillar": "Unknown",
        "use_case": "Unknown", "facing": "Unknown", "surfaces": [],
        "summary": "", "date": "",
    }
    if not ANTHROPIC_API_KEY:
        fallback["summary"] = "(no ANTHROPIC_API_KEY — can't extract)"
        return fallback
    try:
        text = (fetch_drive_doc_text(doc_id) or "").strip()
    except Exception as e:
        fallback["summary"] = f"(couldn't read doc: {type(e).__name__})"
        return fallback
    if not text:
        fallback["summary"] = "(empty / unreadable doc)"
        return fallback
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = (
            "Extract a compact profile of this Graas sales proposal. Return ONLY a "
            "JSON object in exactly this shape (no prose, no fences):\n"
            f"{_SCHEMA}\n\n"
            f"Filename: {doc_name}\n\n=== PROPOSAL TEXT ===\n{text[:24000]}"
        )
        resp = client.messages.create(
            model=EXTRACT_MODEL, max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        data = _extract_json(raw)
    except Exception as e:
        fallback["summary"] = f"(extract failed: {type(e).__name__})"
        return fallback
    if not data:
        return fallback
    # Normalise
    data.setdefault("brand", fallback["brand"])
    data["brand"] = (data.get("brand") or fallback["brand"]).strip()
    surf = data.get("surfaces") or []
    if isinstance(surf, str):
        surf = [s.strip() for s in re.split(r"[,/]", surf) if s.strip()]
    data["surfaces"] = [s for s in _SURFACES if any(s.lower() in x.lower() for x in surf)]
    # Normalise pillar to one of the canonical four (tolerant substring match).
    _pil = (data.get("pillar") or "").strip()
    data["pillar"] = next(
        (P for P in _PILLARS if P.lower() in _pil.lower() or _pil.lower() in P.lower()),
        "Unknown",
    ) if _pil else "Unknown"
    for k in ("use_case", "facing", "summary", "date"):
        data.setdefault(k, fallback[k])
    return data


# ── Page ──────────────────────────────────────────────────────────────────────
st.markdown("### 📑 Proposal Bank")
st.caption(
    "Every proposal we've sent, summarised — brand · use case · who the agent "
    "faces · which surfaces. Auto-read from the Reference Proposals Drive folder; "
    "drop a new proposal in and it shows up on the next scan."
)

_hc1, _hc2 = st.columns([1, 5])
with _hc1:
    if st.button("🔄 Re-scan"):
        _list_proposals.clear()
        _profile_proposal.clear()
        st.rerun()

docs = _list_proposals()
if not docs:
    st.warning(
        "No proposals found in the Reference Proposals folder — or the service "
        "account can't read it. Folder id: "
        f"`{REFERENCE_PROPOSALS_FOLDER_ID}`."
    )
    st.stop()

with st.spinner(f"Reading {len(docs)} proposals…"):
    rows = []
    for d in docs:
        p = _profile_proposal(d["id"], d["name"])
        # Hand corrections win over the auto-extraction.
        for _k, _ov in MANUAL_OVERRIDES.items():
            if _k.lower() in d["name"].lower():
                p = {**p, **_ov}
                break
        rows.append({
            "Brand": p["brand"],
            "Pillar": p.get("pillar", "Unknown"),
            "Use case": p["use_case"],
            "Agent faces": p["facing"],
            "Surfaces": " · ".join(p["surfaces"]) if p["surfaces"] else "—",
            "What it proposes": p["summary"],
            "Date": p["date"],
            "Doc": f"https://drive.google.com/file/d/{d['id']}/view",
            "_surfaces": p["surfaces"],
            "_name": d["name"],
        })

df = pd.DataFrame(rows)

# ── Filters ───────────────────────────────────────────────────────────────────
fc0, fc1, fc2, fc3 = st.columns(4)
with fc0:
    pil = st.multiselect("Pillar", [p for p in _PILLARS if p in set(df["Pillar"])])
with fc1:
    uc = st.multiselect("Use case", sorted([x for x in df["Use case"].unique() if x]))
with fc2:
    fac = st.multiselect("Agent faces", sorted([x for x in df["Agent faces"].unique() if x]))
with fc3:
    surf = st.multiselect("Surface", _SURFACES)

view = df.copy()
if pil:
    view = view[view["Pillar"].isin(pil)]
if uc:
    view = view[view["Use case"].isin(uc)]
if fac:
    view = view[view["Agent faces"].isin(fac)]
if surf:
    view = view[view["_surfaces"].apply(lambda ss: any(s in ss for s in surf))]

st.caption(f"**{len(view)}** of {len(df)} proposals")

st.dataframe(
    view[["Brand", "Pillar", "Use case", "Agent faces", "Surfaces", "What it proposes", "Date", "Doc"]],
    use_container_width=True, hide_index=True,
    column_config={
        "Doc": st.column_config.LinkColumn("Doc", display_text="Open ↗"),
        "What it proposes": st.column_config.TextColumn("What it proposes", width="large"),
    },
    height=min(680, 90 + 38 * len(view)),
)

# ── At-a-glance rollups ───────────────────────────────────────────────────────
with st.expander("📊 At a glance", expanded=True):
    gc0, gc1, gc2, gc3 = st.columns(4)
    with gc0:
        st.markdown("**By pillar**")
        st.dataframe(df["Pillar"].value_counts().rename_axis("Pillar").reset_index(name="Proposals"),
                     hide_index=True, use_container_width=True)
    with gc1:
        st.markdown("**By use case**")
        st.dataframe(df["Use case"].value_counts().rename_axis("Use case").reset_index(name="Proposals"),
                     hide_index=True, use_container_width=True)
    with gc2:
        st.markdown("**Agent faces**")
        st.dataframe(df["Agent faces"].value_counts().rename_axis("Faces").reset_index(name="Proposals"),
                     hide_index=True, use_container_width=True)
    with gc3:
        st.markdown("**By surface**")
        _sf = pd.Series([s for ss in df["_surfaces"] for s in ss]).value_counts()
        st.dataframe(_sf.rename_axis("Surface").reset_index(name="Proposals"),
                     hide_index=True, use_container_width=True)
