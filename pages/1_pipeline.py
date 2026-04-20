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

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CURRENT_MONTH = MONTH_NAMES[datetime.now().month - 1]

@st.cache_data(ttl=1800)
def load_proposals():
    from services.sheets_client import fetch_sheet_tab
    sheet_id = os.getenv("REVENUE_SHEET_ID", "")
    if not sheet_id:
        return pd.DataFrame()
    return fetch_sheet_tab(sheet_id, "Proposals")

@st.cache_data(ttl=1800)
def load_current_pipeline():
    """Load the current month All-e pipeline tab."""
    from services.sheets_client import fetch_sheet_tab
    sheet_id = os.getenv("ALLE_SHEET_ID", "")
    if not sheet_id:
        return pd.DataFrame()
    tab_name = f"All-e Pipeline (IN) - {CURRENT_MONTH}"
    return fetch_sheet_tab(sheet_id, tab_name)

@st.cache_data(ttl=1800)
def load_meetings_summary():
    """Load Revised - Summary of Meetings tab from All-e sheet."""
    from services.sheets_client import fetch_sheet_tab
    sheet_id = os.getenv("ALLE_SHEET_ID", "")
    if not sheet_id:
        return {}
    try:
        df = fetch_sheet_tab(sheet_id, "Revised - Summary of Meetings")
    except Exception:
        return {}
    if df.empty:
        return {}

    months = ["Jan", "Feb", "Mar", "Apr"]

    def _safe_int(v):
        try:
            return int(str(v).strip())
        except (ValueError, TypeError):
            return 0

    def _parse_section(df, row_start, col_start):
        """Parse a source block (9 cols wide) starting at given row/col."""
        result = {}
        funnel_keys = {
            "meetings completed": "meetings",
            "- positive interest": "positive",
            "-others (interest yet to confirm)": "others",
            "pocs completed": "pocs",
            "pilots started": "pilots",
            "in production": "production",
        }
        for i in range(row_start + 2, min(row_start + 8, len(df))):
            row = df.iloc[i]
            label = str(row.iloc[col_start]).strip().lower()
            for key, name in funnel_keys.items():
                if label == key:
                    result[name] = {}
                    for mi, month in enumerate(months):
                        count_col = col_start + 1 + mi * 2
                        names_col = col_start + 2 + mi * 2
                        if count_col < len(row):
                            result[name][month] = {
                                "count": _safe_int(row.iloc[count_col]),
                                "companies": str(row.iloc[names_col]).strip() if names_col < len(row) else "",
                            }
                    break
        return result

    def _parse_overall(df, row_start, col_start):
        """Parse the Overall section with Actual/Target columns."""
        result = {}
        funnel_keys = {
            "meetings completed": "meetings",
            "- positive interest": "positive",
            "-others (interest yet to confirm)": "others",
        }
        for i in range(row_start + 2, min(row_start + 5, len(df))):
            row = df.iloc[i]
            label = str(row.iloc[col_start]).strip().lower()
            for key, name in funnel_keys.items():
                if label == key:
                    result[name] = {}
                    for mi, month in enumerate(months):
                        actual_col = col_start + 1 + mi * 2
                        target_col = col_start + 2 + mi * 2
                        if actual_col < len(row):
                            result[name][month] = {
                                "actual": _safe_int(row.iloc[actual_col]),
                                "target": _safe_int(row.iloc[target_col]),
                            }
                    break
        return result

    def _parse_overall_funnel(df, row_start, col_start):
        """Parse the Overall Graas funnel (POCs, Pilots, Production) with Actual/Target."""
        result = {}
        funnel_keys = {
            "pocs completed": "pocs",
            "pilots started": "pilots",
            "in production": "production",
        }
        for i in range(row_start, min(row_start + 4, len(df))):
            row = df.iloc[i]
            label = str(row.iloc[col_start]).strip().lower()
            for key, name in funnel_keys.items():
                if label == key:
                    result[name] = {}
                    for mi, month in enumerate(months):
                        actual_col = col_start + 1 + mi * 2
                        target_col = col_start + 2 + mi * 2
                        if actual_col < len(row):
                            result[name][month] = {
                                "actual": _safe_int(row.iloc[actual_col]),
                                "target": _safe_int(row.iloc[target_col]),
                            }
                    break
        return result

    data = {
        "sources": {
            "Partner India": _parse_section(df, 0, 0),
            "Partner SEA": _parse_section(df, 0, 10),
            "Graas Network India": _parse_section(df, 9, 0),
            "Graas Network SEA": _parse_section(df, 9, 10),
        },
        "overall_india": _parse_overall(df, 18, 0),
        "overall_sea": _parse_overall(df, 18, 10),
        "overall_funnel": _parse_overall_funnel(df, 24, 0),
    }
    return data

raw = load_proposals()
pipeline_raw = load_current_pipeline()
meetings_data = load_meetings_summary()

if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# 1. MEETINGS — Q1+ VIEW (from "Revised - Summary of Meetings" tab)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 🤝 Meetings — Q1 2026 + Apr")
st.caption("All products — source: All-e 'Revised - Summary of Meetings' tab")

if meetings_data:
    _MONTHS = ["Jan", "Feb", "Mar", "Apr"]
    ov_in = meetings_data.get("overall_india", {})
    ov_sea = meetings_data.get("overall_sea", {})
    ov_funnel = meetings_data.get("overall_funnel", {})

    # ── Helper: sum a metric across months ────────────────────────────────────
    def _sum_metric(overall, metric, field, month_list):
        total = 0
        for m in month_list:
            total += overall.get(metric, {}).get(m, {}).get(field, 0)
        return total

    # ── Grand totals ──────────────────────────────────────────────────────────
    q1 = ["Jan", "Feb", "Mar"]
    india_q1 = _sum_metric(ov_in, "meetings", "actual", q1)
    sea_q1 = _sum_metric(ov_sea, "meetings", "actual", q1)
    india_apr = _sum_metric(ov_in, "meetings", "actual", ["Apr"])
    sea_apr = _sum_metric(ov_sea, "meetings", "actual", ["Apr"])
    total_q1 = india_q1 + sea_q1
    total_apr = india_apr + sea_apr
    total_ytd = total_q1 + total_apr

    target_q1 = _sum_metric(ov_in, "meetings", "target", q1) + _sum_metric(ov_sea, "meetings", "target", q1)
    target_apr = _sum_metric(ov_in, "meetings", "target", ["Apr"]) + _sum_metric(ov_sea, "meetings", "target", ["Apr"])
    target_ytd = target_q1 + target_apr

    positive_ytd = (
        _sum_metric(ov_in, "positive", "actual", _MONTHS) +
        _sum_metric(ov_sea, "positive", "actual", _MONTHS)
    )

    pocs_ytd = _sum_metric(ov_funnel, "pocs", "actual", _MONTHS)
    pilots_ytd = _sum_metric(ov_funnel, "pilots", "actual", _MONTHS)

    # ── Top-line KPIs ────────────────────────────────────────────────────────
    mk1, mk2, mk3, mk4 = st.columns(4)
    with mk1:
        pct = f"{total_ytd/target_ytd*100:.0f}%" if target_ytd else "—"
        st.metric("Meetings (YTD)", total_ytd, f"vs {target_ytd} target ({pct})")
    with mk2:
        conv = f"{positive_ytd/total_ytd*100:.0f}%" if total_ytd else "—"
        st.metric("Positive Interest", positive_ytd, conv)
    with mk3:
        st.metric("POCs Done", pocs_ytd)
    with mk4:
        st.metric("Pilots Started", pilots_ytd)

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

    for src_key, color in _SOURCE_ROWS:
        src_data = sources.get(src_key, {})
        mtg_info = src_data.get("meetings", {})
        row_total = sum(mtg_info.get(m, {}).get("count", 0) for m in _MONTHS)
        if row_total == 0:
            continue

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
                names_raw = mtg_info.get(m, {}).get("companies", "")
                names = [n.strip() for n in names_raw.split(",") if n.strip()] if names_raw and names_raw != "nan" else []

                # Compact: join names with " · " separator instead of line breaks
                names_str = " · ".join(names) if names else "—"

                st.markdown(
                    f'<div style="text-align:center; padding:8px 4px; background:#1E1E2E; '
                    f'border-radius:6px; border-top:2px solid {color};">'
                    f'<div style="font-size:0.7rem; color:#9CA3AF;">{m}</div>'
                    f'<div style="font-size:1.3rem; font-weight:700; color:{color};">{count}</div>'
                    f'<div style="font-size:0.6rem; color:#E5E7EB; line-height:1.3; margin-top:4px;">'
                    f'{names_str}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # ── India & SEA totals vs target ──────────────────────────────────────────
    _REGION_ROWS = [
        ("India", ov_in, _INDIA_COLOR),
        ("SEA", ov_sea, _SEA_COLOR),
    ]
    for region, ov_data, color in _REGION_ROWS:
        mtg = ov_data.get("meetings", {})
        ytd_actual = sum(mtg.get(m, {}).get("actual", 0) for m in _MONTHS)
        ytd_target = sum(mtg.get(m, {}).get("target", 0) for m in _MONTHS)
        ytd_pct = f"{ytd_actual/ytd_target*100:.0f}%" if ytd_target else "—"

        label_col, *month_cols = st.columns([1.2] + [1] * len(_MONTHS))
        with label_col:
            st.markdown(
                f'<div style="padding:10px 6px; min-height:60px; display:flex; '
                f'align-items:center; border-top:1px solid #374151;">'
                f'<div>'
                f'<div style="font-size:0.8rem; font-weight:700; color:{color};">Total {region}</div>'
                f'<div style="font-size:1rem; font-weight:700; color:{color};">'
                f'{ytd_actual} / {ytd_target} ({ytd_pct})</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        for col, m in zip(month_cols, _MONTHS):
            with col:
                actual = mtg.get(m, {}).get("actual", 0)
                target = mtg.get(m, {}).get("target", 0)
                pct = actual / target * 100 if target else 0
                pct_color = "#10B981" if pct >= 90 else "#F59E0B" if pct >= 60 else "#EF4444"

                st.markdown(
                    f'<div style="text-align:center; padding:8px 4px; background:#1E1E2E; '
                    f'border-radius:6px; border-top:2px solid {color}; min-height:60px;">'
                    f'<div style="font-size:0.7rem; color:#9CA3AF;">{m}</div>'
                    f'<div style="font-size:1.1rem; font-weight:700; color:{color};">'
                    f'{actual} <span style="font-size:0.75rem; color:#6B7280;">/ {target}</span></div>'
                    f'<div style="font-size:0.7rem; font-weight:600; color:{pct_color};">{pct:.0f}%</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # ── Funnel progression ────────────────────────────────────────────────────
    st.markdown("#### 📊 Funnel Progression (YTD)")
    funnel_stages = [
        ("Meetings", total_ytd, "#3B82F6"),
        ("Positive Interest", positive_ytd, "#10B981"),
        ("POCs", pocs_ytd, "#F59E0B"),
        ("Pilots", pilots_ytd, "#A855F7"),
    ]
    fc = st.columns(len(funnel_stages))
    for col, (label, val, color) in zip(fc, funnel_stages):
        with col:
            st.markdown(
                f'<div style="text-align:center; padding:15px; background:#1E1E2E; '
                f'border-radius:8px; border-top:3px solid {color};">'
                f'<div style="font-size:2rem; font-weight:700; color:{color};">{val}</div>'
                f'<div style="font-size:0.85rem; color:#9CA3AF;">{label}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    # Conversion rates
    conv_parts = []
    if total_ytd > 0:
        conv_parts.append(f"Meeting → Positive: **{positive_ytd/total_ytd*100:.0f}%**")
    if positive_ytd > 0:
        conv_parts.append(f"Positive → POC: **{pocs_ytd/positive_ytd*100:.0f}%**")
    if conv_parts:
        st.caption(" &nbsp;|&nbsp; ".join(conv_parts))

else:
    st.info("Meetings summary not available — check 'Revised - Summary of Meetings' tab in the All-e sheet.")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# 2. CURRENT MONTH PIPELINE STATUS (Kanban — from "All-e Pipeline (IN) - {month}" tab)
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown(f"### 🗓️ {CURRENT_MONTH} Pipeline Status")
st.caption("Live pipeline status — meetings being set, MOF, BOF | Source: All-e Pipeline tab")

# ── CSS for pipeline cards ──
st.markdown("""
<style>
.pipeline-item {
    background: #1E1E2E;
    border-radius: 6px;
    padding: 6px 10px;
    margin-bottom: 4px;
    border-left: 3px solid;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}
.pipeline-name { font-weight: 600; font-size: 0.85rem; }
.pipeline-detail { font-size: 0.75rem; color: #9CA3AF; }
.pipeline-notes { font-size: 0.78rem; margin-top: 1px; }
</style>
""", unsafe_allow_html=True)

# ── All-e India pipeline from sheet ──
alle_sections = {}
if not pipeline_raw.empty:
    SECTION_KEYS = {
        "meetings already set": ("Meetings Set", "#10B981", "✅"),
        "meetings in the process": ("Meetings Being Set", "#3B82F6", "🔵"),
        "mof": ("MOF — Met, No Proposal Yet", "#F59E0B", "🟡"),
        "bof": ("BOF — Proposal Sent, In Play", "#A855F7", "🟣"),
    }

    current_section = None
    for i in range(len(pipeline_raw)):
        row = pipeline_raw.iloc[i]
        first_cell = str(row.iloc[0]).strip().lower() if len(row) > 0 else ""

        matched = False
        for key, val in SECTION_KEYS.items():
            if key in first_cell:
                current_section = val[0]
                alle_sections[current_section] = {"color": val[1], "icon": val[2], "items": []}
                matched = True
                break

        if matched or current_section is None:
            continue

        name = str(row.iloc[0]).strip() if len(row) > 0 else ""
        if not name or name.lower() in ("name", ""):
            continue
        source = str(row.iloc[1]).strip() if len(row) > 1 else ""
        notes = str(row.iloc[2]).strip() if len(row) > 2 else ""
        if notes == "nan":
            notes = ""
        alle_sections[current_section]["items"].append({"name": name, "source": source, "notes": notes})

# ── Hoppr / Extract pipeline (manual for now) ──
hoppr_extract_sections = {
    "MOF — Meeting Done": {
        "color": "#F59E0B", "icon": "🟡",
        "items": [
            {"name": "Hitachi Thailand", "source": "Hoppr", "notes": ""},
            {"name": "Rinse", "source": "Hoppr", "notes": ""},
            {"name": "Estée Lauder", "source": "Extract", "notes": ""},
            {"name": "Beacon Mart", "source": "Hoppr", "notes": ""},
            {"name": "Bata", "source": "Hoppr", "notes": ""},
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
                notes_html = f'<div class="pipeline-notes" style="color:{color};">{item["notes"]}</div>' if item["notes"] else ""
                st.markdown(
                    f'<div class="pipeline-item" style="border-color:{color};">'
                    f'<div>'
                    f'<span class="pipeline-name">{item["name"]}</span>'
                    f'{notes_html}'
                    f'</div>'
                    f'<span class="pipeline-detail">{item["source"]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

render_kanban_row("All-e India", alle_sections)
st.markdown("")
render_kanban_row("Hoppr / Extract", hoppr_extract_sections)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# 3. PROPOSALS (by product — from "Proposals" tab in Weekly Revenue Call Sheet)
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
    "Execute": "Execute",
    "Integration": "Execute",
    "Hoppr": "Hoppr",
    "Extract": "Extract",
    "Extract ": "Extract",
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
}
.kanban-meta {
    font-size: 0.75rem;
    color: #9CA3AF;
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
    GP=("GP", "sum"),
    Won_GP=("GP", lambda x: x[df.loc[x.index, "Status"] == "Won"].sum()),
).reset_index().sort_values("GP", ascending=False)

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
        "Pipeline GP": fmt(r["GP"]),
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
    .applymap(green_cell, subset=["Won", "Won GP"])
    .applymap(red_cell, subset=["Lost"])
)
st.dataframe(styled_prod, use_container_width=True, hide_index=True, height=220)

fig_pg = go.Figure()
fig_pg.add_trace(go.Bar(
    y=prod_group["Product Group"], x=prod_group["GP"], orientation="h",
    name="Pipeline GP",
    text=[fmt(v) for v in prod_group["GP"]], textposition="outside",
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

st.markdown("### Monthly Detail")

for m in months:
    md = df[df["Month"] == m]
    won_m = md[md["Status"] == "Won"]
    lost_m = md[md["Status"] == "Lost"]
    open_m = md[md["Status"] == "Open"]
    new_m = md[md["Type"] == "New"]
    ex_m = md[md["Type"] == "Existing"]

    with st.expander(
        f"**{m}**  —  {len(md)} proposals  |  "
        f"✅ {len(won_m)} won  |  ❌ {len(lost_m)} lost  |  ⏳ {len(open_m)} open",
        expanded=(m == months[-1]),
    ):
        if not new_m.empty:
            won_names = [r["Client"] for _, r in new_m.iterrows() if r["Status"] == "Won"]
            lost_names = [r["Client"] for _, r in new_m.iterrows() if r["Status"] == "Lost"]
            open_names = [r["Client"] for _, r in new_m.iterrows() if r["Status"] == "Open"]
            parts = [f"**New** ({len(new_m)}):"]
            if won_names: parts.append(f"✅ {', '.join(won_names)}")
            if lost_names: parts.append(f"❌ {', '.join(lost_names)}")
            if open_names: parts.append(f"⏳ {', '.join(open_names)}")
            st.markdown("  \n".join(parts))

        if not ex_m.empty:
            won_names = [r["Client"] for _, r in ex_m.iterrows() if r["Status"] == "Won"]
            open_names = [r["Client"] for _, r in ex_m.iterrows() if r["Status"] == "Open"]
            parts = [f"**Existing** ({len(ex_m)}):"]
            if won_names: parts.append(f"✅ {', '.join(won_names)}")
            if open_names: parts.append(f"⏳ {', '.join(open_names)}")
            st.markdown("  \n".join(parts))

        detail = md[["Type", "Client", "Product Group", "GP", "Status", "PIC"]].copy()
        detail["GP"] = detail["GP"].apply(lambda v: fmt(v) if v > 0 else "TBD")

        def sc(val):
            if val == "Won": return "color: #10B981; font-weight: bold"
            if val == "Lost": return "color: #EF4444"
            return "color: #F59E0B"

        st.dataframe(detail.style.applymap(sc, subset=["Status"]),
                      use_container_width=True, hide_index=True)
