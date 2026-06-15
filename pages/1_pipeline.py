"""Pipeline Dashboard — Proposals Tracker (All Products)."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

_env_path = str(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(_env_path, override=True)

from datetime import datetime, timedelta

st.set_page_config(page_title="Pipeline | Graas", page_icon="📋", layout="wide")
st.markdown("## 📋 Pipeline — Meetings & Proposals")
st.caption("Meetings (all products, from All-e Summary of Meetings) → Proposals (by product, from Weekly Revenue Call Sheet)")

# ── Data Loading ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=1800)
def load_proposals():
    from services.sheets_client import fetch_sheet_tab
    sheet_id = os.getenv("REVENUE_SHEET_ID", "")
    if not sheet_id:
        return pd.DataFrame()
    try:
        return fetch_sheet_tab(sheet_id, "Proposals")
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=1800)
def load_current_pipeline():
    """Load the unified IN+SEA All-e pipeline tab."""
    from services.sheets_client import fetch_sheet_tab
    sheet_id = os.getenv("ALLE_SHEET_ID", "")
    if not sheet_id:
        return pd.DataFrame()
    try:
        return fetch_sheet_tab(sheet_id, "Overall Pipeline for IN and SEA")
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=1800)
def load_meetings_summary():
    """Derive meetings summary.

    SOURCE OF TRUTH per metric:
      • Meetings count (Companies Met) → OLD tabs 'Active presales' + 'Dropped
        leads' — these still have a populated 'First conv date' column, which
        is the correct semantic for "when did we first meet this company".
      • POCs / Pilots / Production → NEW 'Overall Pipeline for IN and SEA' tab
        which carries the pipeline-progression date columns.

    Why split: the team is migrating to the unified tab but dropped
    'First conv date' along the way, and many rows have no 'Latest conv date'
    either. Reading meetings from the new tab under-counts (only 26 of 79
    rows have any date) and using Latest conv date is semantically wrong
    (over-counts late months for leads we met months ago).

    TODO when 'Active presales' + 'Dropped leads' tabs are archived:
      - Either ask Dhanashree to restore 'First conv date' on the unified
        tab, or move this calc to use the unified tab's Latest conv date
        and accept the over-counting tradeoff.
    """
    from services.sheets_client import fetch_sheet_tab
    sheet_id = os.getenv("ALLE_SHEET_ID", "")
    if not sheet_id:
        return {}

    import pandas as _pd

    YEAR = 2026
    MONTHS_ALL = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    # ── Load: old tabs (for meetings) + unified tab (for pipeline progression) ──
    # Schema sentry runs at the page level (outside this cache) because
    # @st.cache_data only replays UI side-effects on cache miss — we want
    # the missing-column banner to render on every page load until fixed.
    df_active = pd.DataFrame()
    df_dropped = pd.DataFrame()
    df_unified = pd.DataFrame()
    try:
        df_active  = fetch_sheet_tab(sheet_id, "Active presales")
        df_dropped = fetch_sheet_tab(sheet_id, "Dropped leads")
        df_unified = fetch_sheet_tab(sheet_id, "Overall Pipeline for IN and SEA")
    except Exception as e:
        import streamlit as _st
        _st.warning(f"Pipeline load error: {e}")

    # Normalize the region column name — Active presales uses 'Country',
    # Dropped leads uses 'Region'. Standardize to 'Region' for both.
    if not df_active.empty and "Country" in df_active.columns and "Region" not in df_active.columns:
        df_active = df_active.rename(columns={"Country": "Region"})

    # Concat old tabs into a single meetings dataframe
    if not df_active.empty or not df_dropped.empty:
        df_mtg = _pd.concat([df_active, df_dropped], ignore_index=True, sort=False)
    else:
        # Fallback if old tabs are gone (archived) — use unified tab with whatever
        # date column it has
        df_mtg = df_unified.copy()

    if df_mtg.empty or "Lead name" not in df_mtg.columns:
        return {}

    # Parse all date columns we might use
    for _df in (df_mtg, df_unified):
        if _df.empty:
            continue
        for c in ["First conv date", "Latest conv date", "POC Delivery Date",
                  "Proposal Sent Date", "Pilot Start Date",
                  "Production Start Date"]:
            if c in _df.columns:
                _df[c] = _pd.to_datetime(_df[c], format="mixed", errors="coerce")

    df_mtg = df_mtg[df_mtg["Lead name"].astype(str).str.strip() != ""].copy()

    # If the old tabs disappear, we have to live with Latest conv date
    _MTG_COL = "First conv date" if "First conv date" in df_mtg.columns else "Latest conv date"
    _using_fallback = (_MTG_COL == "Latest conv date")

    def _bucket(src: str) -> str:
        s = str(src).strip().lower()
        return "partner" if s in ("greentern", "cartlyst website") else "graas"

    def _region_key(r: str) -> str:
        r = str(r).strip().lower()
        if r == "india": return "india"
        if r == "sea":   return "sea"
        # Dropped-leads rows often have an empty Region (~20 of them — AB Inbev,
        # Samsung, Wipro, Kajaria, TTK Prestige, etc.). All are Indian accounts,
        # so default empty → india instead of dropping them from every count.
        # If anything starts coming through that's actually SEA-but-blank, flag
        # and revisit.
        if r in ("", "nan", "none"):
            return "india"
        return ""

    df_mtg["_region"] = df_mtg.get("Region", "").apply(_region_key)
    df_mtg["_bucket"] = df_mtg.get("Source of lead", "").apply(_bucket)
    # For the pipeline-progression dataframe, do the same so POC/Pilot/Production
    # slicing works on the same region×bucket grid as meetings.
    if not df_unified.empty:
        df_unified["_region"] = df_unified.get("Region", "").apply(_region_key)
        df_unified["_bucket"] = df_unified.get("Source of lead", "").apply(_bucket)
    # Keep the meetings dataframe as the primary `df` for the existing helpers below
    df = df_mtg

    # Positive interest proxy: leads that progressed past TOF
    if "Lead status" in df.columns:
        df["_positive"] = ~df["Lead status"].astype(str).str.strip().str.lower().isin(["", "4-tof"])
    else:
        df["_positive"] = False

    def _by_month(sub_df, date_col, positive_only=False):
        out = {m: {"count": 0, "companies": ""} for m in MONTHS_ALL}
        if date_col not in sub_df.columns or sub_df.empty:
            return out
        mask = sub_df[date_col].notna() & (sub_df[date_col].dt.year == YEAR)
        if positive_only:
            mask = mask & sub_df["_positive"]
        valid = sub_df[mask]
        for m_num, grp in valid.groupby(valid[date_col].dt.month):
            mn = int(m_num)
            if 1 <= mn <= 12:
                names = grp["Lead name"].dropna().astype(str).tolist()
                out[MONTHS_ALL[mn - 1]] = {"count": len(grp), "companies": ", ".join(names)}
        return out

    def _slice(region_key, bucket_key=None):
        s = df[df["_region"] == region_key]
        if bucket_key is not None:
            s = s[s["_bucket"] == bucket_key]
        return s

    def _slice_unified(region_key, bucket_key=None):
        if df_unified.empty or "_region" not in df_unified.columns:
            return df_unified
        s = df_unified[df_unified["_region"] == region_key]
        if bucket_key is not None:
            s = s[s["_bucket"] == bucket_key]
        return s

    def _build_source(region_key, bucket_key):
        sub_m = _slice(region_key, bucket_key)
        sub_p = _slice_unified(region_key, bucket_key)
        return {
            "meetings":   _by_month(sub_m, _MTG_COL),
            "positive":   _by_month(sub_m, _MTG_COL, positive_only=True),
            "others":     {m: {"count": 0, "companies": ""} for m in MONTHS_ALL},
            "pocs":       _by_month(sub_p, "POC Delivery Date"),
            "pilots":     _by_month(sub_p, "Pilot Start Date"),
            "production": _by_month(sub_p, "Production Start Date"),
        }

    def _build_overall_region(region_key):
        sub = _slice(region_key)
        mtg = _by_month(sub, _MTG_COL)
        pos = _by_month(sub, _MTG_COL, positive_only=True)
        return {
            "meetings": {m: {"actual": mtg[m]["count"], "target": 0} for m in MONTHS_ALL},
            "positive": {m: {"actual": pos[m]["count"], "target": 0} for m in MONTHS_ALL},
            "others":   {m: {"actual": 0, "target": 0} for m in MONTHS_ALL},
        }

    def _build_overall_funnel():
        # Pipeline-progression dates live only on the unified tab, not the old tabs
        return {
            "pocs":       {m: {"actual": _by_month(df_unified, "POC Delivery Date")[m]["count"],     "target": 0} for m in MONTHS_ALL},
            "pilots":     {m: {"actual": _by_month(df_unified, "Pilot Start Date")[m]["count"],      "target": 0} for m in MONTHS_ALL},
            "production": {m: {"actual": _by_month(df_unified, "Production Start Date")[m]["count"], "target": 0} for m in MONTHS_ALL},
        }

    return {
        "_mtg_col_used":   _MTG_COL,
        "_using_fallback": _using_fallback,
        "sources": {
            "Partner India":       _build_source("india", "partner"),
            "Partner SEA":         _build_source("sea",   "partner"),
            "Graas Network India": _build_source("india", "graas"),
            "Graas Network SEA":   _build_source("sea",   "graas"),
        },
        "overall_india":  _build_overall_region("india"),
        "overall_sea":    _build_overall_region("sea"),
        "overall_funnel": _build_overall_funnel(),
    }

raw = load_proposals()
pipeline_raw = load_current_pipeline()
meetings_data = load_meetings_summary()

if st.button("🔄 Refresh", help="Clears both Streamlit's in-memory cache AND the parquet disk cache so the next read goes back to Google."):
    from services.sheets_client import clear_disk_cache
    removed = clear_disk_cache()
    st.cache_data.clear()
    st.toast(f"Cleared {removed} cached file(s). Reloading from sheet…")
    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# 1. MEETINGS — Q1+ VIEW (from "Revised - Summary of Meetings" tab)
# ══════════════════════════════════════════════════════════════════════════════
_ALL_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_YTD_MONTHS = _ALL_MONTHS[:datetime.now().month]

# ── Schema sentry — visible warnings if any tab we depend on is missing
# expected columns. Runs on every render (NOT inside @st.cache_data) so the
# banners stay visible until the underlying sheet is fixed.
from services.schema import validate_schema as _validate_schema
from services.sheets_client import fetch_sheet_tab as _fetch_tab
_alle_id = os.getenv("ALLE_SHEET_ID", "")
if _alle_id:
    # These fetches are cache hits (the data was loaded above) — essentially free.
    _validate_schema(_fetch_tab(_alle_id, "Active presales"),
                     "Active presales", context="Pipeline Meetings YTD")
    _validate_schema(_fetch_tab(_alle_id, "Dropped leads"),
                     "Dropped leads", context="Pipeline Meetings YTD")
    _validate_schema(_fetch_tab(_alle_id, "Overall Pipeline for IN and SEA"),
                     "Overall Pipeline for IN and SEA",
                     context="Pipeline progression (POC / Pilot / Production)")

st.markdown(f"### 🤝 Meetings — YTD 2026 (through {_YTD_MONTHS[-1]})")
_mtg_col_used = (meetings_data or {}).get("_mtg_col_used", "First conv date")
_using_fallback = (meetings_data or {}).get("_using_fallback", False)
st.caption(
    f"All products — meetings from **Active presales + Dropped leads** tabs "
    f"(derived from **{_mtg_col_used}**); pipeline progression (POC / Pilot / "
    f"Production) from the unified 'Overall Pipeline for IN and SEA' tab."
    + (" ⚠️ Old tabs unavailable — falling back to unified tab's Latest conv date "
       "(over-counts late months)." if _using_fallback else "")
)

if meetings_data:
    _MONTHS = _YTD_MONTHS
    ov_in = meetings_data.get("overall_india", {})
    ov_sea = meetings_data.get("overall_sea", {})

    # ── Companies Met — by source × month ─────────────────────────────────────
    sources = meetings_data.get("sources", {})
    st.markdown("#### 🏢 Companies Met")

    _INDIA_COLOR = "#3B82F6"   # blue for all India rows
    _SEA_COLOR = "#A855F7"     # purple for all SEA rows

    _SOURCE_ROWS = [
        ("Graas Network India", _INDIA_COLOR),
        ("Partner India", _INDIA_COLOR),
        ("Graas Network SEA", _SEA_COLOR),
        ("Partner SEA", _SEA_COLOR),
    ]

    # ── Month header row ──────────────────────────────────────────────────────
    hdr_label, *hdr_months = st.columns([1.2] + [1] * len(_MONTHS))
    for col, m in zip(hdr_months, _MONTHS):
        with col:
            st.markdown(
                f'<div style="text-align:center; font-size:0.8rem; font-weight:600; '
                f'color:#9CA3AF; padding:4px 0;">{m}</div>',
                unsafe_allow_html=True,
            )

    for src_key, color in _SOURCE_ROWS:
        src_data = sources.get(src_key, {})
        mtg_info = src_data.get("meetings", {})
        row_total = sum(mtg_info.get(m, {}).get("count", 0) for m in _MONTHS)
        # Always show every source row (even at 0) — visibility = accountability.

        # Label column + month columns
        label_col, *month_cols = st.columns([1.2] + [1] * len(_MONTHS))
        with label_col:
            st.markdown(
                f'<div style="padding:10px 6px; min-height:80px; display:flex; '
                f'align-items:center;">'
                f'<div>'
                f'<div style="font-size:0.8rem; font-weight:700; color:{color};">{src_key}</div>'
                f'<div style="font-size:1.2rem; font-weight:700; color:{color};">{row_total} mtgs</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        for col, m in zip(month_cols, _MONTHS):
            with col:
                count = mtg_info.get(m, {}).get("count", 0)
                st.markdown(
                    f'<div style="text-align:center; padding:10px 4px; background:#1E1E2E; '
                    f'border-radius:6px; border-top:2px solid {color}; min-height:42px;">'
                    f'<div style="font-size:1.3rem; font-weight:700; color:{color};">{count}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # ── Per-region + Grand Total rows ─────────────────────────────────────────
    def _names_for_sources(src_keys, month):
        names = []
        seen = set()
        for sk in src_keys:
            raw = sources.get(sk, {}).get("meetings", {}).get(month, {}).get("companies", "")
            for n in (raw.split(",") if raw else []):
                n = n.strip()
                if n and n.lower() != "nan" and n not in seen:
                    seen.add(n)
                    names.append(n)
        return names

    _TOTAL_ROWS = [
        ("Total India", ["Graas Network India", "Partner India"], _INDIA_COLOR),
        ("Total SEA",   ["Graas Network SEA",   "Partner SEA"],   _SEA_COLOR),
    ]
    for label, src_keys, color in _TOTAL_ROWS:
        monthly = {m: sum(sources.get(sk, {}).get("meetings", {}).get(m, {}).get("count", 0)
                          for sk in src_keys)
                   for m in _MONTHS}
        ytd_actual = sum(monthly.values())

        label_col, *month_cols = st.columns([1.2] + [1] * len(_MONTHS))
        with label_col:
            st.markdown(
                f'<div style="padding:10px 6px; min-height:70px; display:flex; '
                f'align-items:center; border-top:2px solid #374151;">'
                f'<div>'
                f'<div style="font-size:0.8rem; font-weight:700; color:{color};">{label}</div>'
                f'<div style="font-size:1.3rem; font-weight:700; color:{color};">{ytd_actual}</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        for col, m in zip(month_cols, _MONTHS):
            with col:
                actual = monthly[m]
                names = _names_for_sources(src_keys, m)
                names_str = " · ".join(names) if names else "—"
                st.markdown(
                    f'<div style="text-align:center; padding:8px 4px; background:#1E1E2E; '
                    f'border-radius:6px; border-top:2px solid {color}; min-height:70px; '
                    f'display:flex; flex-direction:column;">'
                    f'<div style="font-size:1.3rem; font-weight:700; color:{color};">{actual}</div>'
                    f'<div style="font-size:0.5rem; color:#E5E7EB; line-height:1.25; '
                    f'margin-top:4px; flex:1;">{names_str}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

else:
    st.info("Meetings summary not available — check 'Overall Pipeline for IN and SEA' tab in the All-e sheet.")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# 2. PROPOSALS (by product — from "Proposals" tab in Weekly Revenue Call Sheet)
# ═══════════════════════════════════════════════════════════════════════════════

if raw.empty:
    st.warning("No proposals data. Check REVENUE_SHEET_ID in .env.")
    st.stop()

# ── Parse ────────────────────────────────────────────────────────────────────

def parse_gp(s):
    s = str(s).strip().replace("$", "").replace(",", "")
    try:
        return float(s)
    except:
        return 0.0

def normalise_month(s):
    s = str(s).strip()
    if not s or s == "Date sent":
        return None
    s = s.replace("'26", "").replace("'25", "").strip()
    m = {"jan": "Jan", "feb": "Feb", "mar": "Mar", "march": "Mar",
         "apr": "Apr", "april": "Apr", "may": "May", "jun": "Jun",
         "jul": "Jul", "aug": "Aug", "sep": "Sep", "oct": "Oct",
         "nov": "Nov", "dec": "Dec"}
    return m.get(s.lower().strip(), None)

def classify(s):
    s = str(s).strip().lower()
    # "Lost" takes priority — catches "Won; ... Lost in Apr" scenarios
    if "lost" in s:
        return "Lost"
    if "won" in s:
        return "Won"
    return "Open"

proposals = []
for i in range(len(raw)):
    row = raw.iloc[i]
    month = normalise_month(str(row.iloc[1]).strip()) if len(row) > 1 else None
    ctype = str(row.iloc[2]).strip() if len(row) > 2 else ""
    client = str(row.iloc[3]).strip() if len(row) > 3 else ""
    product = str(row.iloc[4]).strip() if len(row) > 4 else ""
    gp = parse_gp(row.iloc[5]) if len(row) > 5 else 0
    conclusion = str(row.iloc[6]).strip() if len(row) > 6 else ""
    pic = str(row.iloc[7]).strip() if len(row) > 7 else ""

    if not month or ctype not in ("New", "Existing"):
        continue
    proposals.append({
        "Month": month, "Type": ctype, "Client": client,
        "Product": product, "GP": gp, "Conclusion": conclusion,
        "Status": classify(conclusion), "PIC": pic,
    })

if not proposals:
    st.warning("No proposals parsed.")
    st.stop()

df = pd.DataFrame(proposals)
MO = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
df["_idx"] = df["Month"].apply(lambda m: MO.index(m) if m in MO else 99)
df = df.sort_values("_idx")
months = [m for m in MO if m in df["Month"].values]

def fmt(v):
    if v == 0: return "$0"
    if abs(v) >= 1_000_000: return f"${v/1_000_000:.1f}M"
    if abs(v) >= 1_000: return f"${v/1_000:.0f}K"
    return f"${v:,.0f}"

st.markdown("### 📋 Proposals")
st.caption("By product | Source: Weekly Revenue Call Sheet — Proposals tab")

# ── Total / New / Existing KPI rows ─────────────────────────────────────────

total_won = len(df[df["Status"] == "Won"])
total_lost = len(df[df["Status"] == "Lost"])
total_open = len(df[df["Status"] == "Open"])
total_gp = df["GP"].sum()
won_gp_all = df[df["Status"] == "Won"]["GP"].sum()
wr = total_won / (total_won + total_lost) * 100 if (total_won + total_lost) > 0 else 0

st.markdown("#### Total")
k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    st.metric("Proposals", len(df))
with k2:
    st.metric("Won", total_won, fmt(won_gp_all))
with k3:
    st.metric("Lost", total_lost, delta_color="inverse")
with k4:
    st.metric("Open", total_open, fmt(df[df["Status"] == "Open"]["GP"].sum()))
with k5:
    st.metric("Win Rate", f"{wr:.0f}%")

new_df = df[df["Type"] == "New"]
ex_df = df[df["Type"] == "Existing"]

st.markdown("#### New Customers")
n1, n2, n3, n4, n5 = st.columns(5)
nw = new_df[new_df["Status"] == "Won"]
nl = new_df[new_df["Status"] == "Lost"]
no = new_df[new_df["Status"] == "Open"]
nwr = len(nw) / (len(nw) + len(nl)) * 100 if (len(nw) + len(nl)) > 0 else 0
with n1:
    st.metric("Proposals", len(new_df))
with n2:
    st.metric("Won", len(nw), fmt(nw["GP"].sum()))
with n3:
    st.metric("Lost", len(nl), delta_color="inverse")
with n4:
    st.metric("Open", len(no), fmt(no["GP"].sum()))
with n5:
    st.metric("Win Rate", f"{nwr:.0f}%")

st.markdown("#### Existing Customers")
e1, e2, e3, e4, e5 = st.columns(5)
ew = ex_df[ex_df["Status"] == "Won"]
el = ex_df[ex_df["Status"] == "Lost"]
eo = ex_df[ex_df["Status"] == "Open"]
ewr = len(ew) / (len(ew) + len(el)) * 100 if (len(ew) + len(el)) > 0 else 0
with e1:
    st.metric("Proposals", len(ex_df))
with e2:
    st.metric("Won", len(ew), fmt(ew["GP"].sum()))
with e3:
    st.metric("Lost", len(el), delta_color="inverse")
with e4:
    st.metric("Open", len(eo), fmt(eo["GP"].sum()))
with e5:
    st.metric("Win Rate", f"{ewr:.0f}%")

st.markdown("---")

# ── Product grouping (used by Kanban + Product table) ─────────────────────────
PRODUCT_GROUPS = {
    "All-e B2B": "All-e",
    "All-e B2C": "All-e",
    "All-e": "All-e",
    "Replenishment Intelligence": "All-e",  # pharmacy/retail All-e play (e.g. Sunway MY)
    "Execute": "Execute",
    "Integration": "Execute",
    "Hoppr": "Hoppr",
    "Extract": "Extract",
    "Extract ": "Extract",
    "Analysis/Extract": "Extract",
    "MP Enablement": "MP Enablement",
}

df["Product Group"] = df["Product"].map(PRODUCT_GROUPS).fillna("Other")

# ═══════════════════════════════════════════════════════════════════════════════
# 2. KANBAN VIEW
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("### Proposal Board")

# Determine which open proposals are <60 days vs >60 days
today = datetime.now()
cutoff = today - timedelta(days=60)

MONTH_TO_DATE = {
    "Jan": datetime(2026, 1, 15), "Feb": datetime(2026, 2, 15),
    "Mar": datetime(2026, 3, 15), "Apr": datetime(2026, 4, 15),
    "May": datetime(2026, 5, 15), "Jun": datetime(2026, 6, 15),
    "Jul": datetime(2026, 7, 15), "Aug": datetime(2026, 8, 15),
    "Sep": datetime(2026, 9, 15), "Oct": datetime(2026, 10, 15),
    "Nov": datetime(2026, 11, 15), "Dec": datetime(2026, 12, 15),
}

def get_kanban_stage(row):
    if row["Status"] == "Won":
        return "Won New" if row["Type"] == "New" else "Won Existing"
    if row["Status"] == "Lost":
        return "Lost"
    # Open — check age
    proposal_date = MONTH_TO_DATE.get(row["Month"], today)
    if proposal_date >= cutoff:
        return "In Nego (<60d)"
    return "In Nego (>60d)"

df["Stage"] = df.apply(get_kanban_stage, axis=1)

# Product group filter
product_groups = ["All"] + sorted(df["Product Group"].unique().tolist())
selected_pg = st.selectbox("Filter by Product", product_groups, index=0)

kanban_df = df if selected_pg == "All" else df[df["Product Group"] == selected_pg]

# Define stages and colors
STAGES = [
    ("In Nego (<60d)", "#3B82F6", "🔵"),
    ("In Nego (>60d)", "#F59E0B", "🟡"),
    ("Won New", "#10B981", "✅"),
    ("Won Existing", "#34D399", "✅"),
    ("Lost", "#EF4444", "❌"),
]

# Kanban CSS
st.markdown("""
<style>
.kanban-card {
    background: #1E1E2E;
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 5px;
    border-left: 3px solid;
}
.kanban-row1 {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}
.kanban-client {
    font-weight: 600;
    font-size: 0.85rem;
    color: #E2E8F0;
}
.kanban-meta {
    font-size: 0.75rem;
    color: #9CA3AF;
    background: rgba(255,255,255,0.08);
    border-radius: 4px;
    padding: 2px 6px;
}
.kanban-row2 {
    font-size: 0.8rem;
    margin-top: 2px;
}
.kanban-header {
    font-weight: 700;
    font-size: 1.1rem;
    padding: 8px 0;
    margin-bottom: 8px;
    border-bottom: 2px solid;
}
</style>
""", unsafe_allow_html=True)

cols = st.columns(len(STAGES))

for col, (stage, color, icon) in zip(cols, STAGES):
    with col:
        stage_df = kanban_df[kanban_df["Stage"] == stage].sort_values("GP", ascending=False)
        stage_gp = stage_df["GP"].sum()
        count = len(stage_df)

        st.markdown(
            f'<div class="kanban-header" style="border-color: {color}; color: {color};">'
            f'{icon} {stage} ({count})<br>'
            f'<span style="font-size: 0.85rem;">{fmt(stage_gp)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        for _, r in stage_df.iterrows():
            gp_str = fmt(r["GP"]) if r["GP"] > 0 else "TBD"
            conclusion = r["Conclusion"] if r["Conclusion"] else ""
            note_str = f" — {conclusion}" if conclusion else ""

            st.markdown(
                f'<div class="kanban-card" style="border-color: {color};">'
                f'<div class="kanban-row1">'
                f'<span class="kanban-client">{r["Client"]}</span>'
                f'<span class="kanban-meta">{r["Product Group"]} | {r["Type"]} | {r["Month"]}</span>'
                f'</div>'
                f'<div class="kanban-row2" style="color: {color};">{gp_str}{note_str}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        if count == 0:
            st.markdown(
                '<div style="color: #6B7280; text-align: center; padding: 20px;">No proposals</div>',
                unsafe_allow_html=True,
            )

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# 3. BY PRODUCT GROUP
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("### Pipeline by Product")

prod_group = df.groupby("Product Group").agg(
    Sent=("Client", "count"),
    Won=("Status", lambda x: (x == "Won").sum()),
    Lost=("Status", lambda x: (x == "Lost").sum()),
    Open=("Status", lambda x: (x == "Open").sum()),
    # Open_GP is what "Pipeline GP" should mean — future revenue from deals
    # still in play. Summing all rows would conflate it with Won + Lost value.
    Open_GP=("GP", lambda x: x[df.loc[x.index, "Status"] == "Open"].sum()),
    Won_GP=("GP", lambda x: x[df.loc[x.index, "Status"] == "Won"].sum()),
).reset_index().sort_values("Open_GP", ascending=False)

prod_table = []
for _, r in prod_group.iterrows():
    wr_p = r["Won"] / (r["Won"] + r["Lost"]) * 100 if (r["Won"] + r["Lost"]) > 0 else 0
    prod_table.append({
        "Product": r["Product Group"],
        "Sent": int(r["Sent"]),
        "Won": int(r["Won"]),
        "Won GP": fmt(r["Won_GP"]),
        "Lost": int(r["Lost"]),
        "Open": int(r["Open"]),
        "Pipeline GP": fmt(r["Open_GP"]),
        "Win Rate": f"{wr_p:.0f}%",
    })

prod_df = pd.DataFrame(prod_table)

def green_cell(val):
    try:
        if int(val) > 0: return "color: #10B981; font-weight: bold"
    except: pass
    if isinstance(val, str) and val.startswith("$") and val != "$0":
        return "color: #10B981; font-weight: bold"
    return ""

def red_cell(val):
    try:
        if int(val) > 0: return "color: #EF4444"
    except: pass
    return ""

styled_prod = (prod_df.style
    .map(green_cell, subset=["Won", "Won GP"])
    .map(red_cell, subset=["Lost"])
)
st.dataframe(styled_prod, use_container_width=True, hide_index=True, height=220)

fig_pg = go.Figure()
fig_pg.add_trace(go.Bar(
    y=prod_group["Product Group"], x=prod_group["Open_GP"], orientation="h",
    name="Pipeline GP",
    text=[fmt(v) for v in prod_group["Open_GP"]], textposition="outside",
    marker_color="#7C3AED",
))
fig_pg.add_trace(go.Bar(
    y=prod_group["Product Group"], x=prod_group["Won_GP"], orientation="h",
    name="Won GP",
    text=[fmt(v) for v in prod_group["Won_GP"]], textposition="outside",
    marker_color="#10B981",
))
fig_pg.update_layout(barmode="group", height=350, template="plotly_dark",
                      xaxis_title="GP ($)", margin=dict(l=20, r=100, t=10, b=20),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02))
st.plotly_chart(fig_pg, use_container_width=True)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# 4. ALL-E PIPELINE STATUS — IN + SEA (from "Overall Pipeline for IN and SEA" tab)
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("### 🗓️ All-e Pipeline — IN + SEA")
st.caption("Active leads by stage | Source: All-e 'Overall Pipeline for IN and SEA' tab")

# ── CSS for pipeline cards ──
st.markdown("""
<style>
.pipeline-item {
    background: #1E1E2E;
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 5px;
    border-left: 3px solid;
}
.pipeline-row1 {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}
.pipeline-name { font-weight: 600; font-size: 0.88rem; color: #E2E8F0; }
.pipeline-region-in { font-size: 0.65rem; font-weight: 700; color: #3B82F6; background: rgba(59,130,246,0.15); padding: 2px 6px; border-radius: 4px; }
.pipeline-region-sea { font-size: 0.65rem; font-weight: 700; color: #A855F7; background: rgba(168,85,247,0.15); padding: 2px 6px; border-radius: 4px; }
.pipeline-meta { font-size: 0.7rem; color: #9CA3AF; margin-top: 2px; }
.pipeline-notes { font-size: 0.72rem; color: #CBD5E1; margin-top: 4px; line-height: 1.3; }
</style>
""", unsafe_allow_html=True)

# ── All-e pipeline from sheet (IN + SEA combined) ──
# Stage order: funnel progression earliest → latest
STAGE_ORDER = [
    ("4-TOF", "TOF", "#3B82F6", "🔵"),
    ("2-POC", "POC", "#F59E0B", "🟡"),
    ("3-Proposal sent", "Proposal Sent", "#A855F7", "🟣"),
    ("1-Pilot", "Pilot", "#10B981", "✅"),
]

alle_sections = {label: {"color": color, "icon": icon, "items": []}
                  for _, label, color, icon in STAGE_ORDER}

if not pipeline_raw.empty:
    df_p = pipeline_raw.copy()
    if "Active / Dropped" in df_p.columns:
        df_p = df_p[df_p["Active / Dropped"].astype(str).str.strip().str.lower() == "active"]

    def _truncate(s, n=140):
        s = str(s or "").strip()
        if s in ("", "nan"):
            return ""
        s = s.split("\n")[0].strip()
        return s if len(s) <= n else s[:n].rstrip() + "…"

    for _, row in df_p.iterrows():
        status = str(row.get("Lead status", "")).strip()
        match_key = next((k for k, *_ in STAGE_ORDER if k.lower() == status.lower()), None)
        if not match_key:
            continue
        label = next(lbl for k, lbl, *_ in STAGE_ORDER if k == match_key)
        alle_sections[label]["items"].append({
            "name": str(row.get("Lead name", "")).strip(),
            "owner": str(row.get("Source of lead", "")).strip(),
            "region": str(row.get("Region", "")).strip(),
            "vertical": str(row.get("Vertical", "")).strip(),
            "notes": _truncate(row.get("Latest Conv details", "")),
        })

# ── Hoppr / Extract pipeline (manual for now) ──
hoppr_extract_sections = {
    "MOF — Meeting Done": {
        "color": "#F59E0B", "icon": "🟡",
        "items": [
            {"name": "Hitachi Thailand", "owner": "Hoppr", "region": "", "vertical": "", "notes": ""},
            {"name": "Rinse", "owner": "Hoppr", "region": "", "vertical": "", "notes": ""},
            {"name": "Estée Lauder", "owner": "Extract", "region": "", "vertical": "", "notes": ""},
            {"name": "Beacon Mart", "owner": "Hoppr", "region": "", "vertical": "", "notes": ""},
            {"name": "Bata", "owner": "Hoppr", "region": "", "vertical": "", "notes": ""},
        ],
    },
}

# ── Helper to render a Kanban row ──
def render_kanban_row(label, sections_dict):
    sec_list = [(k, v) for k, v in sections_dict.items() if v["items"]]
    if not sec_list:
        return
    st.markdown(f"#### {label}")
    kcols = st.columns(len(sec_list))
    for col, (sec_name, sec_data) in zip(kcols, sec_list):
        with col:
            color = sec_data["color"]
            icon = sec_data["icon"]
            count = len(sec_data["items"])
            st.markdown(
                f'<div style="font-weight:700; font-size:0.95rem; color:{color}; '
                f'border-bottom:2px solid {color}; padding-bottom:4px; margin-bottom:6px;">'
                f'{icon} {sec_name} ({count})</div>',
                unsafe_allow_html=True,
            )
            for item in sec_data["items"]:
                region = item.get("region", "")
                region_cls = "pipeline-region-sea" if region.lower() == "sea" else "pipeline-region-in"
                region_html = f'<span class="{region_cls}">{region}</span>' if region else ""
                meta_parts = [p for p in [item.get("owner", ""), item.get("vertical", "")] if p]
                meta_html = (
                    f'<div class="pipeline-meta">{" · ".join(meta_parts)}</div>'
                    if meta_parts else ""
                )
                notes_html = (
                    f'<div class="pipeline-notes">{item["notes"]}</div>'
                    if item.get("notes") else ""
                )
                st.markdown(
                    f'<div class="pipeline-item" style="border-color:{color};">'
                    f'<div class="pipeline-row1">'
                    f'<span class="pipeline-name">{item["name"]}</span>'
                    f'{region_html}'
                    f'</div>'
                    f'{meta_html}'
                    f'{notes_html}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

render_kanban_row("All-e (IN + SEA)", alle_sections)
st.markdown("")
render_kanban_row("Hoppr / Extract", hoppr_extract_sections)
