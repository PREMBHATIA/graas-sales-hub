"""All-e — Foundry Presales Pipeline & CRM."""

import os
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime, timedelta
import re
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

_env_path = str(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(_env_path, override=True)

st.set_page_config(page_title="All-e Pipeline | Graas", page_icon="🤖", layout="wide")
st.markdown("## 🤖 All-e — Presales Pipeline & CRM")
st.markdown("[Open Source Sheet →](https://docs.google.com/spreadsheets/d/1lK9AJNA8-vVLPtkUWEq818DHnHWAsrCXgCq7vrvWLnI/edit)")

# ── Data Loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def load_alle_data():
    """Load All-e leads from 'Overall Pipeline for IN and SEA' tab."""
    try:
        from services.sheets_client import fetch_sheet_tab
        sheet_id = os.getenv("ALLE_SHEET_ID", "")
        if sheet_id:
            df = fetch_sheet_tab(sheet_id, "Overall Pipeline for IN and SEA")
            if not df.empty:
                return df
            else:
                st.info("All-e API returned empty DataFrame")
    except Exception as e:
        st.warning(f"All-e load error: {e}")
    # CSV fallback
    candidates = [
        "All-e - Foundry Presales Tracker - Overall Pipeline for IN and SEA.csv",
        "All-e - Foundry Presales Tracker - Active presales.csv",
    ]
    for name in candidates:
        path = Path.home() / "Downloads" / name
        if path.exists():
            return pd.read_csv(path)
    return pd.DataFrame()

raw = load_alle_data()

if raw.empty:
    st.warning("No All-e data found. Check the 'Overall Pipeline for IN and SEA' tab in the All-e Foundry Presales Tracker sheet.")
    st.stop()

# Schema sentry — surface missing-column issues before the page renders metrics
# derived from this tab.
from services.schema import validate_schema as _validate_schema
_validate_schema(raw, "Overall Pipeline for IN and SEA", context="All-e Presales page")

if st.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# ── Data Processing ───────────────────────────────────────────────────────────

df = raw.copy()

# Standardize column names
col_map = {}
for col in df.columns:
    cl = col.strip().lower()
    if 'lead name' in cl:
        col_map[col] = 'lead_name'
    elif 'vertical' in cl:
        col_map[col] = 'vertical'
    elif cl == 'region':
        col_map[col] = 'region'
    elif 'active' in cl and 'dropped' in cl:
        col_map[col] = 'active_status'
    elif 'source' in cl:
        col_map[col] = 'source'
    elif 'agents of interest' in cl:
        col_map[col] = 'agents'
    elif 'lead status' in cl:
        col_map[col] = 'status'
    elif 'first conv' in cl:
        col_map[col] = 'first_conv'
    elif 'latest conv date' in cl:
        col_map[col] = 'latest_conv'
    elif 'latest conv detail' in cl:
        col_map[col] = 'conv_details'
    elif 'poc delivery' in cl:
        col_map[col] = 'poc_delivery_date'
    elif 'proposal sent' in cl:
        col_map[col] = 'proposal_sent_date'
    elif 'pilot start' in cl:
        col_map[col] = 'pilot_start_date'
    elif 'production start' in cl:
        col_map[col] = 'production_start_date'
    elif 'nda' in cl:
        col_map[col] = 'nda'
    elif 'poc required' in cl:
        col_map[col] = 'poc_required'
    elif 'poc scope' in cl:
        col_map[col] = 'poc_scope'
    elif 'poc eta' in cl:
        col_map[col] = 'poc_eta'
    elif col.strip().lower() == 'status':
        col_map[col] = 'deal_status'
    elif 'converted' in cl:
        col_map[col] = 'converted'
    elif 'comment' in cl:
        col_map[col] = 'comments'
    elif 'entity' in cl:
        col_map[col] = 'entity_type'
    elif 'email' in cl:
        col_map[col] = 'contacts'
    elif 'link' in cl and 'note' in cl:
        col_map[col] = 'notes_link'

df = df.rename(columns=col_map)

# Filter out empty rows
if 'lead_name' in df.columns:
    df = df[df['lead_name'].notna() & (df['lead_name'].str.strip() != '')].copy()
else:
    st.warning("Could not find 'Lead name' column in the data.")
    st.stop()

# Parse dates (mixed formats: "11 Dec 2025", "Apr 15, 2026", "May 15 2026", etc.)
for date_col in ['first_conv', 'latest_conv', 'poc_delivery_date',
                 'proposal_sent_date', 'pilot_start_date', 'production_start_date']:
    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')

# Keep full dataset (Active + Dropped) for historical monthly metrics
df_all = df.copy()

# Filter to Active leads for pipeline / deal / follow-up views
if 'active_status' in df.columns:
    df = df[df['active_status'].astype(str).str.strip().str.lower() == 'active'].copy()

# Calculate days since last contact
if 'latest_conv' in df.columns:
    today = pd.Timestamp.now()
    df['days_since_contact'] = (today - df['latest_conv']).dt.days
    # Use first_conv if latest is missing
    mask = df['days_since_contact'].isna() & df['first_conv'].notna()
    df.loc[mask, 'days_since_contact'] = (today - df.loc[mask, 'first_conv']).dt.days
else:
    df['days_since_contact'] = None

# Parse lead status for ordering
status_order = {'1-Pilot': 1, '2-POC': 2, '3-Proposal sent': 3, '4-TOF': 4}
if 'status' in df.columns:
    df['status_rank'] = df['status'].map(status_order).fillna(5)
else:
    df['status_rank'] = 5

# ══════════════════════════════════════════════════════════════════════════════

tab_gtm, tab_notes, tab_pipeline, tab_deals = st.tabs([
    "🎯 GTM Tracker",
    "📝 Meeting Notes",
    "🔄 Pipeline",
    "📋 Active Deals",
])


# ══════════════════════════════════════════════════════════════════════════════
# GTM DATA — 2026 Targets & Actuals
# ══════════════════════════════════════════════════════════════════════════════

gtm_target = pd.DataFrame({
    "Month": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "T_New_Mtgs": [5, 10, 15, 18, 20, 20, 22, 22, 20, 18, 15, 10],
    "T_Cumul_Mtgs": [5, 15, 30, 48, 68, 88, 110, 132, 152, 170, 185, 195],
    "T_Free_POCs": [1, 3, 6, 10, 14, 18, 22, 26, 30, 34, 37, 39],
    "T_Pilots_Started": [0, 1, 2, 3, 5, 6, 7, 9, 10, 11, 12, 13],
    "T_Pilots_Finished": [0, 0, 0, 0, 1, 2, 4, 5, 7, 8, 10, 11],
    "T_Live_Customers": [0, 0, 0, 0, 0, 1, 2, 3, 5, 7, 9, 10],
    "T_Pilot_Revenue": [0, 15000, 30000, 45000, 75000, 90000, 105000, 135000, 150000, 165000, 180000, 195000],
    "T_Monthly_MRR": [0, 0, 0, 0, 0, 4000, 8000, 12000, 20000, 28000, 36000, 40000],
})

# Actuals — derived 100% from df_all (Overall Pipeline tab) below. Previously
# Jan/Feb/Mar had hardcoded meeting names; those duplicated/diverged from the
# sheet and broke parity with the Pipeline page Companies Met section.
gtm_actual_mtgs = {}

# Auto-detect meetings from Overall Pipeline by first_conv date
# Uses df_all (Active + Dropped) so dropped leads' historical meetings still count.
# Proposals derived from Proposal Sent Date column directly (more accurate than status).
MONTH_ABBR = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
              7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}

_pre2026_meetings = []
if 'first_conv' in df_all.columns:
    for _, row in df_all.iterrows():
        if pd.notna(row.get('first_conv')):
            conv_date = row['first_conv']
            lead = str(row.get('lead_name', '')).strip()
            if not lead:
                continue
            if conv_date.year < 2026:
                if lead not in _pre2026_meetings:
                    _pre2026_meetings.append(lead)
                continue
            m_abbr = MONTH_ABBR.get(conv_date.month)
            if m_abbr and m_abbr not in gtm_actual_mtgs:
                gtm_actual_mtgs[m_abbr] = {"meetings": [], "proposals": []}
            if m_abbr:
                if lead not in gtm_actual_mtgs[m_abbr]["meetings"]:
                    gtm_actual_mtgs[m_abbr]["meetings"].append(lead)

# Proposals derived from Proposal Sent Date column (all leads, by month)
if 'proposal_sent_date' in df_all.columns:
    for _, row in df_all.iterrows():
        psd = row.get('proposal_sent_date')
        if pd.notna(psd) and psd.year == 2026:
            lead = str(row.get('lead_name', '')).strip()
            if not lead:
                continue
            m_abbr = MONTH_ABBR.get(psd.month)
            if m_abbr and m_abbr not in gtm_actual_mtgs:
                gtm_actual_mtgs[m_abbr] = {"meetings": [], "proposals": []}
            if m_abbr and lead not in gtm_actual_mtgs[m_abbr]["proposals"]:
                gtm_actual_mtgs[m_abbr]["proposals"].append(lead)

# Build actuals dataframe
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Partner-sourced meetings (Greentern + Cartlyst website) — shades the chart
_PARTNER_SOURCES = {"greentern", "cartlyst website"}
partner_new_mtgs = [0] * 12
if "source" in df_all.columns and "first_conv" in df_all.columns:
    _partner_df = df_all[
        df_all["source"].fillna("").astype(str).str.strip().str.lower().isin(_PARTNER_SOURCES)
        & df_all["first_conv"].notna()
        & (df_all["first_conv"].dt.year == 2026)
    ]
    for m_num, grp in _partner_df.groupby(_partner_df["first_conv"].dt.month):
        if 1 <= int(m_num) <= 12:
            partner_new_mtgs[int(m_num) - 1] = len(grp)

# All-e proposals sent by month — sourced from the revenue sheet's 'Proposals'
# tab (the source of truth), filtered to All-e products only. The presales
# tracker's 'Proposal Sent Date' column is sparsely filled, so it undercounts.
# Cross-product proposals live in the cross-product section, not here.
@st.cache_data(ttl=1800)
def _load_alle_props_by_month():
    import re as _re
    counts = [0] * 12
    clients = [[] for _ in range(12)]
    rev_id = os.getenv("REVENUE_SHEET_ID", "")
    if not rev_id:
        return counts, clients
    try:
        from services.sheets_client import fetch_sheet_tab
        pdf = fetch_sheet_tab(rev_id, "Proposals")
        if pdf.empty:
            return counts, clients
        _MON = {"jan": 0, "feb": 1, "mar": 2, "apr": 3, "may": 4, "jun": 5,
                "jul": 6, "aug": 7, "sep": 8, "oct": 9, "nov": 10, "dec": 11}
        for _, _row in pdf.iterrows():
            _client = str(_row.get("Client Name", "")).strip()
            _product = str(_row.get("Product", "")).lower()
            if not _client or "all-e" not in _product:
                continue
            _mm = _re.match(r"\s*([A-Za-z]{3})", str(_row.get("Date sent", "")))
            if _mm:
                _mi = _MON.get(_mm.group(1).lower())
                if _mi is not None:
                    counts[_mi] += 1
                    clients[_mi].append(_client)
        return counts, clients
    except Exception:
        return counts, clients

alle_props_by_month, alle_prop_clients = _load_alle_props_by_month()

actual_new_mtgs = []
actual_cumul_mtgs = []
actual_proposals = []
actual_proposal_clients = []
cumul = 0
_current_month_idx_for_cumul = datetime.now().month - 1  # 0-based
for i, m in enumerate(months):
    if m in gtm_actual_mtgs:
        n = len(gtm_actual_mtgs[m]["meetings"])
        cumul += n
    else:
        n = 0
    p = alle_props_by_month[i]  # All-e proposals from the revenue 'Proposals' tab
    pc = ", ".join(alle_prop_clients[i])  # names of clients proposed to this month
    # Past + current month: carry the running cumul forward (even if 0 new mtgs).
    # Future months: None so the chart doesn't draw them.
    if i <= _current_month_idx_for_cumul:
        actual_new_mtgs.append(n)
        actual_cumul_mtgs.append(cumul)
        actual_proposals.append(p)
        actual_proposal_clients.append(pc)
    else:
        actual_new_mtgs.append(None)
        actual_cumul_mtgs.append(None)
        actual_proposals.append(None)
        actual_proposal_clients.append("")

gtm_target["A_New_Mtgs"] = actual_new_mtgs
gtm_target["A_Cumul_Mtgs"] = actual_cumul_mtgs
gtm_target["A_Proposals"] = actual_proposals
gtm_target["A_Proposal_Clients"] = actual_proposal_clients


# ══════════════════════════════════════════════════════════════════════════════
# TAB 0: GTM TRACKER
# ══════════════════════════════════════════════════════════════════════════════

with tab_gtm:
    # ── Leads Table (operational view) ────────────────────────────────────────
    st.markdown("""
    <style>
    /* Compact multiselect chips for the GTM filter row */
    div[data-testid="stMultiSelect"] [data-baseweb="tag"] {
        background-color: #374151 !important;
        color: #E5E7EB !important;
        font-size: 0.7rem !important;
        padding: 1px 6px !important;
        height: auto !important;
        line-height: 1.4 !important;
        border-radius: 4px !important;
    }
    div[data-testid="stMultiSelect"] [data-baseweb="tag"] svg {
        fill: #9CA3AF !important;
        width: 12px !important;
        height: 12px !important;
    }
    div[data-testid="stMultiSelect"] label,
    div[data-testid="stTextInput"] label {
        font-size: 0.78rem !important;
        font-weight: 500 !important;
        color: #9CA3AF !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("### All Active Leads")

    col_status, col_vertical, col_source, col_search = st.columns(4)
    with col_status:
        _statuses = sorted(df['status'].dropna().unique().tolist()) if 'status' in df.columns else []
        _sel_status = st.multiselect("Status", _statuses, default=_statuses, key="gtm_alle_status")
    with col_vertical:
        _verticals = sorted(df['vertical'].dropna().unique().tolist()) if 'vertical' in df.columns else []
        _sel_verticals = st.multiselect("Vertical", _verticals, default=_verticals, key="gtm_alle_vert")
    with col_source:
        _src_vals = sorted(df['source'].dropna().unique().tolist()) if 'source' in df.columns else []
        _sel_sources = st.multiselect("Source", _src_vals, default=_src_vals, key="gtm_alle_src")
    with col_search:
        _search = st.text_input("Search lead", "", key="gtm_alle_search")

    _gtm_filtered = df.copy()
    if 'status' in _gtm_filtered.columns:
        _gtm_filtered = _gtm_filtered[_gtm_filtered['status'].isin(_sel_status)]
    if 'vertical' in _gtm_filtered.columns:
        _gtm_filtered = _gtm_filtered[_gtm_filtered['vertical'].isin(_sel_verticals)]
    if 'source' in _gtm_filtered.columns:
        _gtm_filtered = _gtm_filtered[_gtm_filtered['source'].isin(_sel_sources)]
    if _search:
        _gtm_filtered = _gtm_filtered[_gtm_filtered['lead_name'].str.contains(_search, case=False, na=False)]
    _gtm_filtered = _gtm_filtered.sort_values('status_rank')

    _display_cols = ['lead_name', 'vertical', 'source', 'agents', 'status', 'first_conv', 'latest_conv']
    _available_cols = [c for c in _display_cols if c in _gtm_filtered.columns]
    _gtm_display = _gtm_filtered[_available_cols].copy().reset_index(drop=True)
    _gtm_display.insert(0, '#', range(1, len(_gtm_display) + 1))
    for dc in ['first_conv', 'latest_conv']:
        if dc in _gtm_display.columns:
            _gtm_display[dc] = _gtm_display[dc].dt.strftime('%d %b %Y').fillna('—')
    _gtm_display = _gtm_display.rename(columns={
        'lead_name': 'Lead', 'vertical': 'Vertical', 'source': 'Source',
        'agents': 'Product Interest', 'status': 'Status',
        'first_conv': 'First Contact', 'latest_conv': 'Last Contact',
    })

    def _gtm_status_color(val):
        return {
            '1-Pilot': 'background-color: #065F46; color: white',
            '2-POC': 'background-color: #1E40AF; color: white',
            '3-Proposal sent': 'background-color: #92400E; color: white',
            '4-TOF': 'background-color: #374151; color: white',
        }.get(val, '')

    _gtm_style = _gtm_display.style
    if 'Status' in _gtm_display.columns:
        _gtm_style = _gtm_style.map(_gtm_status_color, subset=['Status'])
    st.dataframe(_gtm_style, use_container_width=True, height=600, hide_index=True)

    st.markdown("---")

    # ── 2026 Execution & Revenue Roadmap ──────────────────────────────────────
    st.markdown("### 2026 Execution & Revenue Roadmap")
    st.caption("Tracking against AOP targets — cumulative figures, pilot revenue recognized at month of start")

    # Current month detection — auto from today
    current_month_idx = datetime.now().month - 1  # 0-based (Apr = 3)

    # ── KPI Cards — YTD ───────────────────────────────────────────────────────
    ytd_target_mtgs = gtm_target.loc[current_month_idx, "T_Cumul_Mtgs"]
    _raw_actual = gtm_target.loc[current_month_idx, "A_Cumul_Mtgs"]
    ytd_actual_mtgs = int(_raw_actual) if pd.notna(_raw_actual) else 0
    ytd_ach_mtgs = (
        f"{ytd_actual_mtgs/ytd_target_mtgs*100:.0f}%"
        if ytd_target_mtgs and pd.notna(ytd_target_mtgs)
        else "—"
    )

    ytd_target_pocs = gtm_target.loc[current_month_idx, "T_Free_POCs"]
    # Count proposals as proxy for POC pipeline
    ytd_actual_proposals = sum(p for p in actual_proposals[:current_month_idx+1] if p is not None)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(f"Cumul. Meetings ({months[current_month_idx]})", f"{ytd_actual_mtgs}", f"{ytd_ach_mtgs} of {ytd_target_mtgs} target")
    with c2:
        st.metric("Proposals Sent (YTD)", ytd_actual_proposals, f"Target POCs: {ytd_target_pocs}")
    with c3:
        st.metric("Pilots Started (Target)", gtm_target.loc[current_month_idx, "T_Pilots_Started"])
    with c4:
        st.metric("Pilot Revenue (Target)", f"${gtm_target.loc[current_month_idx, 'T_Pilot_Revenue']:,}")

    # ── Meetings: Target vs Actual Chart (Jan–current month only) ──────────────
    st.markdown("### New Meetings — Target vs Actual")

    _chart_months = months[:current_month_idx + 1]  # Jan through current month
    _chart_targets = gtm_target["T_New_Mtgs"].iloc[:current_month_idx + 1]
    _chart_actuals = actual_new_mtgs[:current_month_idx + 1]

    # Optional: show pre-2026 meetings count
    if _pre2026_meetings:
        st.caption(f"ℹ️ {len(_pre2026_meetings)} leads from pre-2026 not shown: {', '.join(_pre2026_meetings[:8])}{'…' if len(_pre2026_meetings) > 8 else ''}")

    _chart_partner = partner_new_mtgs[:current_month_idx + 1]
    actual_bars  = [v if v is not None else 0 for v in _chart_actuals]
    partner_bars = list(_chart_partner)
    graas_bars   = [max(a - p, 0) for a, p in zip(actual_bars, partner_bars)]
    _PARTNER_COLOR = "#A78BFA"  # lavender
    _GRAAS_COLOR   = "#10B981"  # green
    _TARGET_COLOR  = "#374151"  # dark gray

    fig_mtgs = go.Figure()
    fig_mtgs.add_trace(go.Bar(
        x=_chart_months, y=_chart_targets,
        name="Target", marker_color=_TARGET_COLOR,
        offsetgroup="target",
    ))
    fig_mtgs.add_trace(go.Bar(
        x=_chart_months, y=partner_bars,
        name="Partner Meetings", marker_color=_PARTNER_COLOR,
        offsetgroup="actual",
    ))
    fig_mtgs.add_trace(go.Bar(
        x=_chart_months, y=graas_bars,
        name="Graas Network Meetings", marker_color=_GRAAS_COLOR,
        offsetgroup="actual",
    ))
    fig_mtgs.update_layout(
        barmode="stack", height=350, template="plotly_dark",
        margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig_mtgs, use_container_width=True)

    # ── Cumulative Meetings Chart (Jan–current month only) ─────────────────────
    st.markdown("### Cumulative Meetings — Target vs Actual")
    fig_cumul = go.Figure()
    fig_cumul.add_trace(go.Scatter(
        x=_chart_months, y=gtm_target["T_Cumul_Mtgs"].iloc[:current_month_idx+1],
        mode="lines+markers", name="Target",
        line=dict(color="#6B7280", dash="dash", width=2),
    ))
    actual_cumul_plot = [v for v in actual_cumul_mtgs[:current_month_idx+1] if v is not None]
    fig_cumul.add_trace(go.Scatter(
        x=_chart_months[:len(actual_cumul_plot)],
        y=actual_cumul_plot,
        mode="lines+markers", name="Actual",
        line=dict(color="#4F46E5", width=3),
        marker=dict(size=10),
    ))
    fig_cumul.update_layout(
        height=350, template="plotly_dark",
        margin=dict(l=20, r=20, t=20, b=20),
    )
    st.plotly_chart(fig_cumul, use_container_width=True)

    # ── Full Roadmap Table ────────────────────────────────────────────────────
    st.markdown("### Full Roadmap — Targets")

    # Show only up to current month + 1.
    # Order: Month → Actuals first (Mtgs / Cumul / Proposals) → Targets.
    # Pilot Rev + MRR columns removed (low signal at this stage).
    roadmap_display = gtm_target.iloc[:current_month_idx + 2][[
        "Month",
        "A_New_Mtgs", "A_Cumul_Mtgs", "A_Proposals", "A_Proposal_Clients",
        "T_New_Mtgs", "T_Cumul_Mtgs", "T_Free_POCs",
        "T_Pilots_Started", "T_Pilots_Finished", "T_Live_Customers",
    ]].copy()

    roadmap_display = roadmap_display.rename(columns={
        "A_New_Mtgs": "Actual Mtgs", "A_Cumul_Mtgs": "Actual Cumul",
        "A_Proposals": "Actual Proposals", "A_Proposal_Clients": "Proposal Clients",
        "T_New_Mtgs": "Target Mtgs", "T_Cumul_Mtgs": "Target Cumul",
        "T_Free_POCs": "Target POCs", "T_Pilots_Started": "Target Pilots",
        "T_Pilots_Finished": "Pilots Done", "T_Live_Customers": "Live Cust",
    })

    # Color-code Actuals (green tint) vs Targets (muted gray) so the eye
    # can immediately tell "what we did" from "what we aimed at".
    _actual_cols = ["Actual Mtgs", "Actual Cumul", "Actual Proposals"]
    _target_cols = ["Target Mtgs", "Target Cumul", "Target POCs",
                    "Target Pilots", "Pilots Done", "Live Cust"]
    _num_cols = _actual_cols + _target_cols

    # Styler defaults to 6-decimal float for numeric columns once we apply
    # .set_properties — explicit int formatter required to keep things clean.
    def _int_fmt(v):
        if v is None:
            return "—"
        try:
            import math
            if isinstance(v, float) and math.isnan(v):
                return "—"
            return f"{int(v)}"
        except (TypeError, ValueError):
            return "—"

    _styled = (
        roadmap_display.style
            .format({c: _int_fmt for c in _num_cols})
            .set_properties(subset=_actual_cols, **{
                "background-color": "rgba(16, 185, 129, 0.12)",  # emerald-500 @ 12%
                "color": "#10B981",
                "font-weight": "600",
            })
            .set_properties(subset=_target_cols, **{
                "color": "#9CA3AF",  # gray-400 — visible but recessed
            })
    )
    st.dataframe(_styled, use_container_width=True, hide_index=True)

    st.caption("Assumption: 13 Paid Pilots → 10 Customers in Production = $195K + $148K = **$343K invoiced revenue in 2026**")

    # ── Pipeline Heatmap — Milestones × Vertical (2026 YTD) ───────────────────
    st.markdown("---")
    st.markdown("### 🌐 2026 Vertical Overview")
    st.caption("All counts are 2026 milestones, deduped by lead name. Meetings = first conv this year (= Dropped + still-active). Dropped = leads now marked Dropped. TOF = active, no milestone yet. POC / Proposal Sent / Pilot = leads that hit that milestone date in 2026.")
    if 'vertical' in df_all.columns and 'first_conv' in df_all.columns:

        def _vert(s):
            v = str(s or '').strip()
            return v if v and v.lower() != 'nan' else 'Other'

        def _in_year(col):
            if col not in df_all.columns:
                return pd.Series(False, index=df_all.index)
            return df_all[col].notna() & (df_all[col].dt.year == 2026)

        first_2026     = _in_year('first_conv')
        poc_2026       = _in_year('poc_delivery_date')
        proposal_2026  = _in_year('proposal_sent_date')
        pilot_2026     = _in_year('pilot_start_date')
        tof_2026 = first_2026 & ~poc_2026 & ~proposal_2026 & ~pilot_2026

        # Dropped leads — for triangulation
        if 'active_status' in df_all.columns:
            _dropped_flag = df_all['active_status'].fillna('').astype(str).str.strip().str.lower() == 'dropped'
        else:
            _dropped_flag = pd.Series(False, index=df_all.index)
        dropped_2026 = first_2026 & _dropped_flag

        _vert_series = df_all['vertical'].apply(_vert)
        _lead_series = df_all.get('lead_name', pd.Series('', index=df_all.index)).fillna('').astype(str).str.strip()

        def _counts(mask):
            sub = pd.DataFrame({'_vert': _vert_series[mask], '_lead': _lead_series[mask]})
            sub = sub[sub['_lead'] != ''].drop_duplicates(subset=['_vert', '_lead'])
            return sub['_vert'].value_counts()

        meetings_by_vert  = _counts(first_2026)
        dropped_by_vert   = _counts(dropped_2026)
        tof_by_vert       = _counts(tof_2026 & ~_dropped_flag)
        poc_by_vert       = _counts(poc_2026)
        proposal_by_vert  = _counts(proposal_2026)
        pilot_by_vert     = _counts(pilot_2026)

        all_verts = sorted(set(meetings_by_vert.index) | set(dropped_by_vert.index)
                           | set(tof_by_vert.index) | set(poc_by_vert.index)
                           | set(proposal_by_vert.index) | set(pilot_by_vert.index))
        cross = pd.DataFrame({
            'Meetings':      [int(meetings_by_vert.get(v, 0))  for v in all_verts],
            'Dropped':       [int(dropped_by_vert.get(v, 0))   for v in all_verts],
            'TOF':           [int(tof_by_vert.get(v, 0))       for v in all_verts],
            'POC':           [int(poc_by_vert.get(v, 0))       for v in all_verts],
            'Proposal Sent': [int(proposal_by_vert.get(v, 0))  for v in all_verts],
            'Pilot':         [int(pilot_by_vert.get(v, 0))     for v in all_verts],
        }, index=all_verts)

        sort_idx = cross.drop(index=['Other'], errors='ignore').sort_values('Meetings', ascending=False).index.tolist()
        if 'Other' in cross.index:
            sort_idx.append('Other')
        cross = cross.loc[sort_idx]

        # Append a Total row summing every column
        cross.loc['Total'] = cross.sum(axis=0).astype(int)

        _zmax = max(int(cross.iloc[:, 1:].max().max()) if cross.shape[1] > 1 else 1, 1) + 1

        fig_heat = px.imshow(
            cross, text_auto=True, aspect='auto',
            color_continuous_scale=[
                [0.0,  '#F1F5F9'],
                [0.15, '#BFDBFE'],
                [0.5,  '#3B82F6'],
                [1.0,  '#1E3A8A'],
            ],
            zmin=0, zmax=_zmax,
            labels=dict(x="Stage", y="Vertical", color="Count"),
        )
        fig_heat.update_traces(
            texttemplate="%{z}",
            textfont=dict(size=14),
        )
        fig_heat.update_layout(
            height=max(340, 38 * len(cross.index) + 90),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#374151'),
            margin=dict(l=20, r=20, t=40, b=20),
            xaxis=dict(side='top', tickfont=dict(size=13, color='#374151'), title=None, showgrid=False),
            yaxis=dict(tickfont=dict(size=13, color='#374151'), title=None, showgrid=False),
            coloraxis_showscale=False,
        )
        col_heat, col_audit = st.columns([2, 1])
        with col_heat:
            st.plotly_chart(fig_heat, use_container_width=True)

        with col_audit:
            st.markdown(
                f'<div style="font-size:0.7rem;font-weight:700;color:#6B7280;'
                f'text-transform:uppercase;letter-spacing:0.05em;margin:6px 0 4px 0;">'
                f'Lead audit · {int(cross.loc["Total", "Meetings"])} total</div>',
                unsafe_allow_html=True,
            )

            _audit = df_all[first_2026].copy()
            _audit['_vert'] = _audit['vertical'].apply(_vert)
            _audit['_lead'] = _lead_series[first_2026]
            _audit = _audit[_audit['_lead'] != ''].drop_duplicates(subset=['_vert', '_lead'])

            def _state(row):
                if _dropped_flag.loc[row.name]:
                    return ('Dropped', '#9CA3AF')
                if pilot_2026.loc[row.name]:
                    return ('Pilot', '#10B981')
                if proposal_2026.loc[row.name]:
                    return ('Proposal', '#3B82F6')
                if poc_2026.loc[row.name]:
                    return ('POC', '#A78BFA')
                return ('TOF', '#F59E0B')

            audit_blocks = []
            for vert in cross.index.drop(['Total'], errors='ignore'):
                rows = _audit[_audit['_vert'] == vert].sort_values('_lead')
                if rows.empty:
                    continue

                active_rows  = rows[~_dropped_flag.reindex(rows.index, fill_value=False)]
                dropped_rows = rows[ _dropped_flag.reindex(rows.index, fill_value=False)]

                lead_lines = []
                for _, r in active_rows.iterrows():
                    label, color = _state(r)
                    lead_lines.append(
                        f'<div style="font-size:0.62rem;color:#374151;line-height:1.35;'
                        f'border-left:2px solid {color};padding-left:5px;margin:1px 0;">'
                        f'{r["_lead"]} '
                        f'<span style="color:{color};font-weight:600;">· {label}</span></div>'
                    )
                if not dropped_rows.empty:
                    names = " · ".join(dropped_rows['_lead'].tolist())
                    lead_lines.append(
                        f'<div style="font-size:0.62rem;color:#9CA3AF;line-height:1.35;'
                        f'border-left:2px solid #9CA3AF;padding-left:5px;margin:1px 0;">'
                        f'<span style="font-weight:600;">Dropped ({len(dropped_rows)}):</span> {names}</div>'
                    )

                audit_blocks.append(
                    f'<div style="margin:0 0 6px 0;">'
                    f'<div style="font-size:0.68rem;font-weight:700;color:#1F2937;margin-bottom:2px;">'
                    f'{vert} <span style="color:#9CA3AF;font-weight:500;">({len(rows)})</span></div>'
                    f'{"".join(lead_lines)}</div>'
                )
            st.markdown("".join(audit_blocks), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB: MEETING NOTES  (pulled from Slack channels via Granola shares)
# ══════════════════════════════════════════════════════════════════════════════


with tab_notes:
    st.markdown("### 📝 Latest Meeting Notes")
    st.caption("Auto-pulled from Slack — `#ebu-offerings-gtm` (India) and `#my-gtm-alle` (MY/SEA)")

    # ── Build notes from sheet's notes_link column ────────────────────────────
    st.markdown("#### 🔗 Notes by Lead (from Presales Tracker)")

    if 'notes_link' in df.columns:
        leads_with_notes = df[df['notes_link'].notna() & (df['notes_link'].str.strip() != '')].copy()
        if not leads_with_notes.empty:
            leads_with_notes = leads_with_notes.sort_values('latest_conv', ascending=False, na_position='last')
            for _, row in leads_with_notes.iterrows():
                lead = row['lead_name']
                raw_links = str(row['notes_link']).strip()
                status = row.get('status', '')
                last_contact = row['latest_conv'].strftime('%d %b') if pd.notna(row.get('latest_conv')) else '—'
                vertical = row.get('vertical', '')

                # Parse links
                link_parts = re.findall(r'https?://[^\s]+', raw_links)
                granola_count = sum(1 for l in link_parts if 'granola.ai' in l)
                gdoc_count = sum(1 for l in link_parts if 'docs.google.com' in l)

                # Icon based on status
                status_icon = {"1-Pilot": "🟢", "2-POC": "🔵", "3-Proposal sent": "🟡", "4-TOF": "⚪"}.get(status, "⚫")

                with st.expander(f"{status_icon} **{lead}** — {vertical} — last contact {last_contact} — {len(link_parts)} note(s)"):
                    # Show all links
                    for i, link in enumerate(link_parts, 1):
                        if 'granola.ai' in link:
                            st.markdown(f"📋 [Granola Note {i}]({link})")
                        elif 'docs.google.com' in link:
                            st.markdown(f"📄 [Google Doc {i}]({link})")
                        else:
                            st.markdown(f"🔗 [Link {i}]({link})")

                    # Show conversation details if available
                    if pd.notna(row.get('conv_details')) and str(row['conv_details']).strip():
                        st.markdown("**Latest conversation:**")
                        st.markdown(str(row['conv_details'])[:500])
        else:
            st.info("No leads with notes links found.")
    else:
        st.info("Notes link column not found in sheet.")

    st.markdown("---")

    # ── Recent Slack recaps ───────────────────────────────────────────────────
    st.markdown("#### 💬 Recent Meeting Recaps (from Slack)")
    st.caption("Key takeaways shared in `#ebu-offerings-gtm` and `#my-gtm-alle`")

    # Try live Slack pull; fall back to cached snapshot
    @st.cache_data(ttl=1800)
    def _fetch_slack_notes():
        try:
            from services.slack_notes import fetch_meeting_notes
            notes = fetch_meeting_notes(lookback_days=30)
            if notes:
                return notes, True
        except Exception:
            pass
        return None, False

    slack_recaps, is_live = _fetch_slack_notes()

    if st.button("🔄 Refresh Slack Notes", key="refresh_slack_notes"):
        _fetch_slack_notes.clear()
        st.rerun()

    # Fallback: hardcoded snapshot (last pulled 13 Apr 2026)
    if not slack_recaps:
        is_live = False
        slack_recaps = [
            {
                "client": "Orient Bell",
                "date": "10 Apr",
                "channel": "#ebu-offerings-gtm",
                "author": "Gaurav Girotra",
                "granola": "https://notes.granola.ai/t/374658c2-7836-4553-b1d0-89337a86612f-008umkv4",
                "takeaways": [
                    "POC kicked off for floor tiles as a category",
                    "To be delivered by end of next week (assuming catalogue & details received)",
                    "GG to set up f2f meeting for POC walkthrough and Pilot next steps",
                ],
            },
            {
                "client": "Unicharm",
                "date": "10 Apr",
                "channel": "#ebu-offerings-gtm",
                "author": "Ashwin Puri",
                "granola": "https://notes.granola.ai/t/b8d38fbc-26bb-4f6d-9f97-510409956be5-00best9l",
                "takeaways": [
                    "Existing MP customer expanding markets — SGD $45M MYR/month MY business",
                    "Enablement: extend SG DKSH model to MY for Lazada/Shopee",
                    "Hoppr: provide Deanna access for SG regional data team",
                    "All-e: discovery call to be set up in KL with IT team (Ashwin to arrange)",
                    "Offline AI agent for 126 merchandising + 170 sales team — $10M USD/month MY business",
                ],
            },
            {
                "client": "RSPL Group",
                "date": "9 Apr",
                "channel": "#ebu-offerings-gtm",
                "author": "Gaurav Girotra",
                "granola": "https://notes.granola.ai/t/5b967b55-5142-452f-a0bc-0a5381f85906-008umkv4",
                "takeaways": [
                    "Sales use case not a need — dealer ordering is not an issue for them",
                    "Possible use case: factory OCR (30 factories) for handwritten/typed info routing",
                    "They will come back after discussing internally",
                ],
            },
            {
                "client": "Tata 1mg",
                "date": "9 Apr",
                "channel": "#ebu-offerings-gtm",
                "author": "Gaurav Girotra",
                "granola": "https://notes.granola.ai/t/1fe5a8ad-e368-4995-b0d7-d56c93d82130-008umkv4",
                "takeaways": [
                    "Prem to work with Nikhil on closing out commercials",
                    "Amruta to test accuracy improvements with new cleanly labelled prescriptions",
                ],
            },
            {
                "client": "Dalmia Cement",
                "date": "8 Apr",
                "channel": "#ebu-offerings-gtm",
                "author": "Gaurav Girotra",
                "granola": "https://notes.granola.ai/t/2beb83b8-b2eb-49f5-9702-f8712d8ef5e0-008umkv4",
                "takeaways": [
                    "Very low SKUs (5 active), weekly ordering, 50K dealers — no opportunity",
                    "They already have an AI agent deployed for dealer ordering",
                    "Cement may not be a good fit — low SKU density, infrequent orders",
                ],
            },
            {
                "client": "Sunway",
                "date": "6 Apr",
                "channel": "#my-gtm-alle",
                "author": "Sahil Tyagi",
                "granola": "https://notes.granola.ai/t/d82cf004-9cd3-4fc1-b707-86a56c96e897-009c2hma",
                "takeaways": [],
            },
            {
                "client": "Decathlon",
                "date": "2 Apr",
                "channel": "#my-gtm-alle",
                "author": "Prem Bhatia",
                "granola": "https://notes.granola.ai/t/e88082b9-a0b4-44f9-9646-d56f7c353a5c-008umkv4",
                "takeaways": [],
            },
            {
                "client": "Beacon Mart",
                "date": "1 Apr",
                "channel": "#my-gtm-alle",
                "author": "Sahil Tyagi",
                "granola": "https://notes.granola.ai/t/813537a7-c353-4cf1-bca5-cf165966e9a4-008umkv4",
                "takeaways": [
                    "Cindy to send Thomas Hoppr login for e-commerce team (5 users)",
                    "Send Thomas videos on offline agent (Ollie) for IT team",
                    "Follow up with proposal for f2f meeting in KL once IT is looped in",
                    "Thomas to share Graas videos with Beacon Mart IT team",
                ],
            },
        ]

    if is_live:
        st.success(f"🔴 Live — {len(slack_recaps)} meeting note(s) from Slack (last 30 days)")
    else:
        st.info("📸 Showing cached snapshot — add `SLACK_BOT_TOKEN` to `.env` to enable live refresh")

    for recap in slack_recaps:
        takeaway_count = len(recap["takeaways"])
        label = f"📋 **{recap['client']}** — {recap['date']} — {recap['author']} — {recap['channel']}"
        if takeaway_count:
            label += f" — {takeaway_count} action(s)"

        with st.expander(label):
            if recap["takeaways"]:
                for t in recap["takeaways"]:
                    st.markdown(f"- {t}")
            else:
                st.caption("Granola notes shared — open link for details")
            st.markdown(f"[Open full Granola notes]({recap['granola']})")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

with tab_pipeline:

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    total = len(df)
    pilots = len(df[df['status'] == '1-Pilot']) if 'status' in df.columns else 0
    pocs = len(df[df['status'] == '2-POC']) if 'status' in df.columns else 0
    proposals = len(df[df['status'] == '3-Proposal sent']) if 'status' in df.columns else 0
    tof = len(df[df['status'] == '4-TOF']) if 'status' in df.columns else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Total Leads", total)
    with c2:
        st.metric("Pilots", pilots)
    with c3:
        st.metric("POC", pocs)
    with c4:
        st.metric("Proposals Sent", proposals)
    with c5:
        st.metric("Top of Funnel", tof)

    # ── Month View — Actual vs Target (only through current month) ────────────
    st.markdown("### Monthly Progress vs Target")

    _current_month_idx = datetime.now().month - 1  # 0-based (Jan=0, Apr=3)
    _show_months = months[:_current_month_idx + 1]  # Jan through current month

    month_rows = []
    for m in _show_months:
        idx = months.index(m)
        t_mtgs = gtm_target.loc[idx, "T_New_Mtgs"]
        t_cumul = gtm_target.loc[idx, "T_Cumul_Mtgs"]
        t_pocs = gtm_target.loc[idx, "T_Free_POCs"]
        t_pilots = gtm_target.loc[idx, "T_Pilots_Started"]

        a_mtgs = actual_new_mtgs[idx]
        a_cumul = actual_cumul_mtgs[idx]
        a_props = actual_proposals[idx]

        if a_mtgs is not None:
            mtg_status = "✅" if a_mtgs >= t_mtgs else "⚠️"
            month_rows.append({
                "Month": m,
                "Mtgs (A/T)": f"{mtg_status} {a_mtgs} / {t_mtgs}",
                "Cumul (A/T)": f"{a_cumul} / {t_cumul}",
                "Proposals": a_props,
                "Target POCs": t_pocs,
                "Target Pilots": t_pilots,
            })
        else:
            month_rows.append({
                "Month": m,
                "Mtgs (A/T)": f"— / {t_mtgs}",
                "Cumul (A/T)": f"— / {t_cumul}",
                "Proposals": "—",
                "Target POCs": t_pocs,
                "Target Pilots": t_pilots,
            })

    st.dataframe(pd.DataFrame(month_rows), use_container_width=True, hide_index=True)

    # ── Deals by stage ────────────────────────────────────────────────────────
    st.markdown("### Deals by Stage")
    if 'status' in df.columns:
        for status_label, color, icon in [
            ("1-Pilot", "#10B981", "🟢"),
            ("2-POC", "#06B6D4", "🔵"),
            ("3-Proposal sent", "#F59E0B", "🟡"),
        ]:
            stage_deals = df[df['status'] == status_label].sort_values('days_since_contact', na_position='last')
            if not stage_deals.empty:
                st.markdown(f"#### {icon} {status_label} ({len(stage_deals)} deals)")
                for _, deal in stage_deals.iterrows():
                    days = f"{int(deal['days_since_contact'])}d ago" if pd.notna(deal['days_since_contact']) else "—"
                    vertical = deal.get('vertical', '')
                    source = deal.get('source', '')
                    st.markdown(f"- **{deal['lead_name']}** ({vertical}) — {source} — last contact {days}")

    # ── Funnel Chart (below) ──────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Sales Funnel")

    funnel_stages = ["4 - Top of Funnel", "3 - Proposal Sent", "2 - POC", "1 - Pilot"]
    funnel_values = [tof, proposals, pocs, pilots]

    fig_funnel = go.Figure(go.Funnel(
        y=funnel_stages,
        x=funnel_values,
        textinfo="value+text",
        marker=dict(color=["#6B7280", "#F59E0B", "#06B6D4", "#10B981"]),
        connector=dict(line=dict(color="#374151", width=2)),
    ))
    fig_funnel.update_layout(height=350, template="plotly_dark", margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig_funnel, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: ACTIVE DEALS
# ══════════════════════════════════════════════════════════════════════════════

with tab_deals:
    st.markdown("### Deal Detail")
    st.caption("Pick a lead to see its full meeting + status history. The full leads table moved to the GTM Tracker tab.")

    deal_names = sorted(df['lead_name'].dropna().tolist()) if 'lead_name' in df.columns else []
    selected_deal = st.selectbox("Select lead", deal_names, key="alle_detail")

    if selected_deal:
        deal = df[df['lead_name'] == selected_deal].iloc[0]

        col_info, col_meta = st.columns([3, 2])
        with col_info:
            st.markdown(f"**{deal['lead_name']}** — {deal.get('vertical', '')} ({deal.get('entity_type', '')})")
            st.markdown(f"Status: **{deal.get('status', '')}** | Source: **{deal.get('source', '')}**")
            st.markdown(f"Product Interest: **{deal.get('agents', '')}**")
            if pd.notna(deal.get('contacts')):
                st.markdown(f"Contacts: {deal['contacts']}")
        with col_meta:
            if pd.notna(deal.get('first_conv')):
                st.markdown(f"First Contact: **{deal['first_conv'].strftime('%d %b %Y') if pd.notna(deal.get('first_conv')) else '—'}**")
            if pd.notna(deal.get('latest_conv')):
                st.markdown(f"Last Contact: **{deal['latest_conv'].strftime('%d %b %Y') if pd.notna(deal.get('latest_conv')) else '—'}**")
            if pd.notna(deal.get('days_since_contact')):
                st.markdown(f"Days Since Contact: **{int(deal['days_since_contact'])}**")

        if pd.notna(deal.get('conv_details')) and str(deal['conv_details']).strip():
            with st.expander("📝 Latest Conversation Details"):
                st.markdown(str(deal['conv_details'])[:2000])

        if pd.notna(deal.get('comments')) and str(deal['comments']).strip():
            with st.expander("💬 Comments"):
                st.markdown(str(deal['comments'])[:2000])


