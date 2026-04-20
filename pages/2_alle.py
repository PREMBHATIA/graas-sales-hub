"""All-e — Foundry Presales Pipeline & CRM."""

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
    """Load All-e data — try Sheets API first, then CSV fallback."""
    try:
        from services.sheets_client import fetch_alle_active_presales
        df = fetch_alle_active_presales()
        if not df.empty:
            return df
        else:
            st.info("All-e API returned empty DataFrame")
    except Exception as e:
        st.warning(f"All-e load error: {e}")
    # CSV fallback
    candidates = [
        "All-e - Foundry Presales Tracker - Active presales (1).csv",
        "All-e - Foundry Presales Tracker - Active presales.csv",
    ]
    for name in candidates:
        path = Path.home() / "Downloads" / name
        if path.exists():
            return pd.read_csv(path)
    return pd.DataFrame()

raw = load_alle_data()

if raw.empty:
    st.warning("No All-e data found. Download the 'Active presales' tab from the All-e Foundry Presales Tracker sheet.")
    st.stop()

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

# Parse dates
for date_col in ['first_conv', 'latest_conv']:
    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')

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

tab_gtm, tab_notes, tab_pipeline, tab_deals, tab_stale, tab_analytics = st.tabs([
    "🎯 GTM Tracker",
    "📝 Meeting Notes",
    "🔄 Pipeline",
    "📋 Active Deals",
    "⏰ Needs Follow-up",
    "📊 Analytics",
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

# Actuals — update these as new months complete
gtm_actual_mtgs = {
    "Jan": {
        "meetings": ["Syngenta", "TTK", "Cello", "Rich", "Samsung", "Orient Bell", "MHR Dubai"],
        "proposals": ["Canon"],
    },
    "Feb": {
        "meetings": ["Nippon", "Prince", "Anmol", "Siyaram", "RR Cable", "Wipro", "Kajaria",
                      "Dell", "Reebok", "Wakefit", "Versuni", "BBW", "Mondelez", "Frisian Flag", "Wipro"],
        "proposals": ["Agricon", "Nippon", "Schneider"],
    },
    "Mar": {
        "meetings": ["Crompton", "Eureka", "SRMB Steel", "Tata Consumer Prod", "Liberty Steel", "Makson", "Sunway"],
        "proposals": ["Orient Bell"],
    },
}

# Auto-detect meetings from Active presales sheet by first_conv date
MONTH_ABBR = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
              7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}

if 'first_conv' in df.columns:
    for _, row in df.iterrows():
        if pd.notna(row.get('first_conv')):
            m_abbr = MONTH_ABBR.get(row['first_conv'].month)
            if m_abbr and m_abbr not in gtm_actual_mtgs:
                gtm_actual_mtgs[m_abbr] = {"meetings": [], "proposals": []}
            if m_abbr:
                lead = str(row.get('lead_name', '')).strip()
                if lead and lead not in gtm_actual_mtgs[m_abbr]["meetings"]:
                    gtm_actual_mtgs[m_abbr]["meetings"].append(lead)
                status = str(row.get('status', '')).lower()
                if 'proposal' in status and lead not in gtm_actual_mtgs[m_abbr]["proposals"]:
                    gtm_actual_mtgs[m_abbr]["proposals"].append(lead)

# Build actuals dataframe
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
actual_new_mtgs = []
actual_cumul_mtgs = []
actual_proposals = []
cumul = 0
for m in months:
    if m in gtm_actual_mtgs:
        n = len(gtm_actual_mtgs[m]["meetings"])
        p = len(gtm_actual_mtgs[m]["proposals"])
        cumul += n
    else:
        n = None
        p = None
    actual_new_mtgs.append(n)
    actual_cumul_mtgs.append(cumul if n is not None else None)
    actual_proposals.append(p)

gtm_target["A_New_Mtgs"] = actual_new_mtgs
gtm_target["A_Cumul_Mtgs"] = actual_cumul_mtgs
gtm_target["A_Proposals"] = actual_proposals


# ══════════════════════════════════════════════════════════════════════════════
# TAB 0: GTM TRACKER
# ══════════════════════════════════════════════════════════════════════════════

with tab_gtm:
    st.markdown("### 2026 Execution & Revenue Roadmap")
    st.caption("Tracking against AOP targets — cumulative figures, pilot revenue recognized at month of start")

    # Current month detection — auto from today
    current_month_idx = datetime.now().month - 1  # 0-based (Apr = 3)

    # ── KPI Cards — YTD ───────────────────────────────────────────────────────
    ytd_target_mtgs = gtm_target.loc[current_month_idx, "T_Cumul_Mtgs"]
    ytd_actual_mtgs = gtm_target.loc[current_month_idx, "A_Cumul_Mtgs"] or 0
    ytd_ach_mtgs = f"{ytd_actual_mtgs/ytd_target_mtgs*100:.0f}%" if ytd_target_mtgs else "—"

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

    # ── Meetings: Target vs Actual Chart ──────────────────────────────────────
    st.markdown("### New Meetings — Target vs Actual")

    fig_mtgs = go.Figure()
    fig_mtgs.add_trace(go.Bar(
        x=months, y=gtm_target["T_New_Mtgs"],
        name="Target", marker_color="#374151",
    ))
    actual_bars = [v if v is not None else 0 for v in actual_new_mtgs]
    colors = []
    for i, (a, t) in enumerate(zip(actual_bars, gtm_target["T_New_Mtgs"])):
        if actual_new_mtgs[i] is None:
            colors.append("#1a1a2e")  # future months — dim
        elif a >= t:
            colors.append("#10B981")  # met target
        else:
            colors.append("#EF4444")  # missed
    fig_mtgs.add_trace(go.Bar(
        x=months, y=actual_bars,
        name="Actual", marker_color=colors,
    ))
    fig_mtgs.update_layout(
        barmode="group", height=350, template="plotly_dark",
        margin=dict(l=20, r=20, t=20, b=20),
    )
    st.plotly_chart(fig_mtgs, use_container_width=True)

    # ── Cumulative Meetings Chart ─────────────────────────────────────────────
    st.markdown("### Cumulative Meetings — Target vs Actual")
    fig_cumul = go.Figure()
    fig_cumul.add_trace(go.Scatter(
        x=months, y=gtm_target["T_Cumul_Mtgs"],
        mode="lines+markers", name="Target",
        line=dict(color="#6B7280", dash="dash", width=2),
    ))
    actual_cumul_plot = [v if v is not None else None for v in actual_cumul_mtgs]
    fig_cumul.add_trace(go.Scatter(
        x=months[:current_month_idx+1],
        y=[v for v in actual_cumul_plot[:current_month_idx+1] if v is not None],
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

    # Show only up to current month + 1
    roadmap_display = gtm_target.iloc[:current_month_idx + 2][["Month", "T_New_Mtgs", "T_Cumul_Mtgs", "T_Free_POCs",
                                   "T_Pilots_Started", "T_Pilots_Finished", "T_Live_Customers",
                                   "T_Pilot_Revenue", "T_Monthly_MRR",
                                   "A_New_Mtgs", "A_Cumul_Mtgs", "A_Proposals"]].copy()

    roadmap_display["T_Pilot_Revenue"] = roadmap_display["T_Pilot_Revenue"].apply(lambda x: f"${x:,}")
    roadmap_display["T_Monthly_MRR"] = roadmap_display["T_Monthly_MRR"].apply(lambda x: f"${x:,}")

    roadmap_display = roadmap_display.rename(columns={
        "T_New_Mtgs": "Target Mtgs", "T_Cumul_Mtgs": "Target Cumul",
        "T_Free_POCs": "Target POCs", "T_Pilots_Started": "Target Pilots",
        "T_Pilots_Finished": "Pilots Done", "T_Live_Customers": "Live Cust",
        "T_Pilot_Revenue": "Pilot Rev", "T_Monthly_MRR": "MRR",
        "A_New_Mtgs": "Actual Mtgs", "A_Cumul_Mtgs": "Actual Cumul",
        "A_Proposals": "Proposals",
    })

    st.dataframe(roadmap_display, use_container_width=True, hide_index=True)

    st.caption("Assumption: 13 Paid Pilots → 10 Customers in Production = $195K + $148K = **$343K invoiced revenue in 2026**")

    # ── Monthly Detail ────────────────────────────────────────────────────────
    st.markdown("### Monthly Detail — Meetings & Proposals")

    for month_name, data in gtm_actual_mtgs.items():
        target_idx = months.index(month_name)
        target_val = gtm_target.loc[target_idx, "T_New_Mtgs"]
        actual_val = len(data["meetings"])
        hit = "✅" if actual_val >= target_val else "⚠️"

        with st.expander(f"{hit} **{month_name}** — {actual_val} meetings (target: {target_val}) | {len(data['proposals'])} proposals"):
            mcol1, mcol2 = st.columns(2)
            with mcol1:
                st.markdown("**Meetings:**")
                for i, name in enumerate(data["meetings"], 1):
                    st.markdown(f"{i}. {name}")
            with mcol2:
                st.markdown("**Proposals Sent:**")
                for i, name in enumerate(data["proposals"], 1):
                    st.markdown(f"{i}. {name}")


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

    # ── Month View — Actual vs Target ─────────────────────────────────────────
    st.markdown("### Monthly Progress vs Target")

    month_rows = []
    for m in months:
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
    st.markdown("### All Active Deals")

    # Filters
    col_status, col_vertical, col_source, col_search = st.columns(4)

    with col_status:
        statuses = sorted(df['status'].dropna().unique().tolist()) if 'status' in df.columns else []
        sel_status = st.multiselect("Status", statuses, default=statuses, key="alle_status")
    with col_vertical:
        verticals = sorted(df['vertical'].dropna().unique().tolist()) if 'vertical' in df.columns else []
        sel_verticals = st.multiselect("Vertical", verticals, default=verticals, key="alle_vert")
    with col_source:
        sources = sorted(df['source'].dropna().unique().tolist()) if 'source' in df.columns else []
        sel_sources = st.multiselect("Source", sources, default=sources, key="alle_src")
    with col_search:
        search = st.text_input("Search lead", "", key="alle_search")

    filtered = df.copy()
    if 'status' in filtered.columns:
        filtered = filtered[filtered['status'].isin(sel_status)]
    if 'vertical' in filtered.columns:
        filtered = filtered[filtered['vertical'].isin(sel_verticals)]
    if 'source' in filtered.columns:
        filtered = filtered[filtered['source'].isin(sel_sources)]
    if search:
        filtered = filtered[filtered['lead_name'].str.contains(search, case=False, na=False)]

    filtered = filtered.sort_values('status_rank')

    # Build display table
    display_cols = ['lead_name', 'vertical', 'source', 'agents', 'status', 'first_conv', 'latest_conv']
    available_cols = [c for c in display_cols if c in filtered.columns]

    display = filtered[available_cols].copy()

    # Add row numbers
    display = display.reset_index(drop=True)
    display.insert(0, '#', range(1, len(display) + 1))

    # Format dates
    for dc in ['first_conv', 'latest_conv']:
        if dc in display.columns:
            display[dc] = display[dc].dt.strftime('%d %b %Y').fillna('—')

    rename_map = {
        'lead_name': 'Lead', 'vertical': 'Vertical', 'source': 'Source',
        'agents': 'Product Interest', 'status': 'Status',
        'first_conv': 'First Contact', 'latest_conv': 'Last Contact',
    }
    display = display.rename(columns={k: v for k, v in rename_map.items() if k in display.columns})

    def status_color(val):
        colors = {
            '1-Pilot': 'background-color: #065F46; color: white',
            '2-POC': 'background-color: #1E40AF; color: white',
            '3-Proposal sent': 'background-color: #92400E; color: white',
            '4-TOF': 'background-color: #374151; color: white',
        }
        return colors.get(val, '')

    def days_color(val):
        try:
            v = float(val)
            if v > 21:
                return 'background-color: #7F1D1D; color: white'
            elif v > 14:
                return 'background-color: #92400E; color: white'
            return ''
        except:
            return ''

    style = display.style
    if 'Status' in display.columns:
        style = style.map(status_color, subset=['Status'])
    if 'Days Silent' in display.columns:
        style = style.map(days_color, subset=['Days Silent'])

    st.dataframe(style, use_container_width=True, height=600, hide_index=True)

    # ── Deal Detail ───────────────────────────────────────────────────────────
    st.markdown("### Deal Detail")
    deal_names = filtered['lead_name'].tolist()
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


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: NEEDS FOLLOW-UP
# ══════════════════════════════════════════════════════════════════════════════

with tab_stale:

    # ── Proposals Needing Chasers ─────────────────────────────────────────────
    st.markdown("### 📨 Proposals Needing a Chaser")
    st.caption("Proposals sent 14+ days ago that may need a follow-up")

    if 'days_since_contact' in df.columns and 'status' in df.columns:
        proposals_sent = df[df['status'] == '3-Proposal sent'].copy()

        overdue = proposals_sent[proposals_sent['days_since_contact'] > 30].sort_values('days_since_contact', ascending=False)
        upcoming = proposals_sent[(proposals_sent['days_since_contact'] > 14) & (proposals_sent['days_since_contact'] <= 30)].sort_values('days_since_contact', ascending=False)

        if not overdue.empty:
            st.markdown(f"#### 🔴 Overdue — Proposal sent 30+ days ago ({len(overdue)})")
            for _, deal in overdue.iterrows():
                days = int(deal['days_since_contact'])
                source = deal.get('source', '')
                st.markdown(f"- **{deal['lead_name']}** — {days} days since last update — Owner: {source}")

        if not upcoming.empty:
            st.markdown(f"#### 🟡 Coming Due — Proposal sent 14-30 days ago ({len(upcoming)})")
            for _, deal in upcoming.iterrows():
                days = int(deal['days_since_contact'])
                source = deal.get('source', '')
                st.markdown(f"- **{deal['lead_name']}** — {days} days since last update — Owner: {source}")

        if overdue.empty and upcoming.empty:
            st.success("All proposals are fresh — no chasers needed right now.")

    # ── POC / Pilot Check-ins ─────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🔄 POC & Pilot Check-ins")
    st.caption("Active POCs and Pilots — are they progressing?")

    if 'days_since_contact' in df.columns and 'status' in df.columns:
        active = df[df['status'].isin(['1-Pilot', '2-POC'])].sort_values('days_since_contact', ascending=False).copy()

        if not active.empty:
            for _, deal in active.iterrows():
                days = int(deal['days_since_contact']) if pd.notna(deal['days_since_contact']) else 0
                source = deal.get('source', '')
                icon = "🟢" if days < 14 else "🟡" if days < 30 else "🔴"
                st.markdown(f"- {icon} **{deal['lead_name']}** ({deal['status']}) — last update {days}d ago — Owner: {source}")
        else:
            st.info("No active POCs or Pilots.")

    else:
        st.info("No date data available.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

with tab_analytics:
    st.markdown("### Pipeline Analytics")

    col_left, col_right = st.columns(2)

    # By Vertical
    with col_left:
        st.markdown("#### By Vertical")
        if 'vertical' in df.columns:
            vert_counts = df['vertical'].value_counts().reset_index()
            vert_counts.columns = ['Vertical', 'Count']
            fig_vert = px.bar(vert_counts.sort_values('Count', ascending=True),
                              x='Count', y='Vertical', orientation='h',
                              color_discrete_sequence=['#4F46E5'])
            fig_vert.update_layout(height=350, template="plotly_dark", margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig_vert, use_container_width=True)

    # By Source
    with col_right:
        st.markdown("#### By Lead Source")
        if 'source' in df.columns:
            source_counts = df['source'].value_counts().reset_index()
            source_counts.columns = ['Source', 'Count']
            fig_src = px.pie(source_counts, names='Source', values='Count',
                             color_discrete_sequence=px.colors.qualitative.Set2)
            fig_src.update_layout(height=350, template="plotly_dark")
            st.plotly_chart(fig_src, use_container_width=True)

    # By Status × Vertical heatmap
    st.markdown("#### Pipeline Heatmap — Status x Vertical")
    if 'status' in df.columns and 'vertical' in df.columns:
        cross = pd.crosstab(df['vertical'], df['status'])
        fig_heat = px.imshow(
            cross, text_auto=True,
            color_continuous_scale=['#1a1a2e', '#4F46E5', '#10B981'],
            labels=dict(x="Stage", y="Vertical", color="Count"),
        )
        fig_heat.update_layout(height=400, template="plotly_dark")
        st.plotly_chart(fig_heat, use_container_width=True)

    # Timeline — deals by first contact month
    st.markdown("#### Pipeline Growth — Deals by First Contact Month")
    if 'first_conv' in df.columns:
        timeline = df[df['first_conv'].notna()].copy()
        timeline['month'] = timeline['first_conv'].dt.to_period('M').astype(str)
        monthly = timeline.groupby('month').size().reset_index(name='New Leads')
        fig_time = px.bar(monthly, x='month', y='New Leads', color_discrete_sequence=['#7C3AED'])
        fig_time.update_layout(height=300, template="plotly_dark", xaxis_title="Month", margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig_time, use_container_width=True)
