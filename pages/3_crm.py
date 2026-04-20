"""CRM & Email Outreach — Unified contacts from All-e Active & Dropped leads."""

import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path
from datetime import datetime
import re
import sys
import json

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

_env_path = str(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(_env_path, override=True)

st.set_page_config(page_title="CRM & Outreach | Graas", page_icon="📧", layout="wide")
st.markdown("## 📧 CRM & Email Outreach")
st.caption("All-e Active + Dropped leads (team sheet, read-only) + local overlay (Prem's personal adds) — merged view")

# ── Styling ──────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.crm-card {
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    border-radius: 12px; padding: 18px; margin: 6px 0;
    border-left: 4px solid #4F46E5;
}
.crm-card h4 { margin: 0 0 4px 0; color: #e2e8f0; font-size: 1rem; }
.crm-card .meta { color: #94a3b8; font-size: 0.85rem; }
.crm-card .email-tag {
    display: inline-block; background: #1e3a5f; border-radius: 6px;
    padding: 2px 8px; margin: 2px; font-size: 0.82rem; color: #93c5fd;
}
.segment-btn { padding: 12px; border-radius: 8px; margin: 4px 0;
    background: #1e293b; border: 1px solid #334155; }
.email-preview {
    background: #0f172a; border: 1px solid #334155; border-radius: 10px;
    padding: 20px; margin: 10px 0; font-family: system-ui;
}
.email-preview .subject { font-size: 1.1rem; font-weight: 600; color: #e2e8f0; }
.email-preview .to { font-size: 0.9rem; color: #94a3b8; margin-bottom: 12px; }
.email-preview .body { color: #cbd5e1; white-space: pre-wrap; line-height: 1.6; }
</style>
""", unsafe_allow_html=True)


# ── Data Loading ─────────────────────────────────────────────────────────────

def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize column names (mirrors 8_alle.py logic)."""
    col_map = {}
    for col in df.columns:
        cl = col.strip().lower()
        if 'lead name' in cl:
            col_map[col] = 'lead_name'
        elif 'vertical' in cl:
            col_map[col] = 'vertical'
        elif 'source' in cl and 'lead' in cl:
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
        elif 'comment' in cl:
            col_map[col] = 'comments'
        elif 'entity' in cl:
            col_map[col] = 'entity_type'
        elif 'email' in cl and 'personnel' in cl:
            col_map[col] = 'contacts'
        elif 'who will own' in cl or ('email' in cl and 'outreach' in cl):
            col_map[col] = 'outreach_owner'
    df = df.rename(columns=col_map)
    # Filter empty rows
    if 'lead_name' in df.columns:
        df = df[df['lead_name'].notna() & (df['lead_name'].str.strip() != '')].copy()
    # Parse dates
    for dc in ['first_conv', 'latest_conv']:
        if dc in df.columns:
            df[dc] = pd.to_datetime(df[dc], format='mixed', errors='coerce')
    return df


def _safe(row, col):
    """Safely get a scalar value from a row, handling missing columns."""
    if col not in row.index:
        return ''
    val = row[col]
    return str(val).strip() if pd.notna(val) else ''


def _parse_contacts(df: pd.DataFrame, segment: str) -> pd.DataFrame:
    """Parse 'contacts' (Email of Key Personnel) into individual contact rows."""
    rows = []
    for _, row in df.iterrows():
        email_raw = _safe(row, 'contacts')
        company = _safe(row, 'lead_name')
        if not company or company == 'nan':
            continue

        common = {
            'company': company,
            'lead_status': _safe(row, 'status'),
            'segment': segment,
            'vertical': _safe(row, 'vertical'),
            'entity_type': _safe(row, 'entity_type'),
            'agents': _safe(row, 'agents'),
            'comments': _safe(row, 'comments'),
            'conv_details': _safe(row, 'conv_details'),
            'outreach_owner': _safe(row, 'outreach_owner'),
            'source': _safe(row, 'source'),
        }
        # Parse last contact — fall back to first_conv if latest_conv is missing
        lc = row['latest_conv'] if 'latest_conv' in row.index and pd.notna(row['latest_conv']) else None
        fc = row['first_conv'] if 'first_conv' in row.index and pd.notna(row['first_conv']) else None
        common['last_contact'] = lc if lc is not None else fc
        common['last_contact_is_fallback'] = (lc is None and fc is not None)
        common['first_contact'] = fc

        # Split email field on newlines first, then commas (but not inside parens)
        entries = re.split(r'[\n]+', email_raw)
        flat = []
        for e in entries:
            flat.extend(re.split(r',(?![^(]*\))', e))

        parsed_any = False
        for entry in flat:
            entry = entry.strip()
            if '@' not in entry:
                continue
            # Extract email + optional (Designation)
            m = re.match(r'([^\s(]+@[^\s(,]+)\s*(?:\(([^)]*)\))?', entry)
            if not m:
                continue
            email = m.group(1).strip().rstrip(',')
            designation = (m.group(2) or '').strip()
            # Derive person name from email prefix
            prefix = email.split('@')[0]
            name_parts = re.split(r'[._]', prefix)
            person_name = ' '.join(p.capitalize() for p in name_parts if p)

            rows.append({
                **common,
                'person_name': person_name,
                'email': email,
                'designation': designation,
            })
            parsed_any = True

        if not parsed_any:
            rows.append({**common, 'person_name': '', 'email': '', 'designation': ''})

    return pd.DataFrame(rows)


def _load_overlay():
    """Load local CRM overlay — contacts added outside the team All-e sheet."""
    import json
    from pathlib import Path
    overlay_path = Path(__file__).parent.parent / "content" / "crm_overlay.json"
    if not overlay_path.exists():
        return pd.DataFrame()
    try:
        with open(overlay_path) as f:
            data = json.load(f)
    except Exception:
        return pd.DataFrame()

    rows = []
    for entry in data.get("contacts", []):
        common = {
            "company": entry.get("company", ""),
            "vertical": entry.get("vertical", ""),
            "entity_type": entry.get("entity_type", ""),
            "lead_status": entry.get("lead_status", ""),
            "segment": entry.get("segment", "Active"),
            "agents": entry.get("agents", ""),
            "source": entry.get("source", ""),
            "outreach_owner": entry.get("outreach_owner", ""),
            "conv_details": entry.get("conv_details", ""),
            "comments": entry.get("comments", ""),
            "first_contact": pd.to_datetime(entry.get("first_contact"), errors="coerce"),
            "last_contact": pd.to_datetime(entry.get("last_contact"), errors="coerce"),
            "last_contact_is_fallback": False,
            "_overlay": True,
        }
        people = entry.get("people", [])
        if not people:
            rows.append({**common, "person_name": "", "email": "", "designation": ""})
            continue
        for p in people:
            rows.append({
                **common,
                "person_name": p.get("name", ""),
                "email": p.get("email", ""),
                "designation": p.get("designation", ""),
            })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600)
def load_crm_data():
    """Load and parse all contacts from Active + Dropped sheets + local overlay."""
    try:
        from services.sheets_client import fetch_alle_active_presales, fetch_alle_dropped_leads
        active_raw = fetch_alle_active_presales()
        dropped_raw = fetch_alle_dropped_leads()
    except Exception:
        return pd.DataFrame()

    active_df = _standardize_columns(active_raw)
    dropped_df = _standardize_columns(dropped_raw)

    active_contacts = _parse_contacts(active_df, 'Active')
    dropped_contacts = _parse_contacts(dropped_df, 'Dropped')
    active_contacts['_overlay'] = False
    dropped_contacts['_overlay'] = False

    overlay_contacts = _load_overlay()

    # Dedupe: if overlay company exists in All-e, overlay wins (more up-to-date)
    if not overlay_contacts.empty:
        overlay_companies = set(overlay_contacts['company'].str.lower().unique())
        active_contacts = active_contacts[
            ~active_contacts['company'].str.lower().isin(overlay_companies)
        ]
        dropped_contacts = dropped_contacts[
            ~dropped_contacts['company'].str.lower().isin(overlay_companies)
        ]

    return pd.concat([active_contacts, dropped_contacts, overlay_contacts], ignore_index=True)


contacts = load_crm_data()

if contacts.empty:
    st.warning("No CRM data found. Check All-e sheet connection.")
    st.stop()

if st.button("🔄 Refresh CRM Data"):
    st.cache_data.clear()
    st.rerun()

# Clean up nan strings
for col in contacts.columns:
    if contacts[col].dtype == 'object':
        contacts[col] = contacts[col].replace({'nan': '', 'None': ''})

# ── Derived fields ───────────────────────────────────────────────────────────

contacts['has_email'] = contacts['email'].str.contains('@', na=False)
if 'last_contact' in contacts.columns:
    contacts['days_silent'] = (pd.Timestamp.now() - contacts['last_contact']).dt.days

# ── Recency bucket ───────────────────────────────────────────────────────────
def _recency_bucket(d):
    """Bucket by days since last contact."""
    if pd.isna(d):
        return '⚫ No date'
    if d <= 30:
        return '🔥 Hot (<30d)'
    elif d <= 90:
        return '☀️ Warm (30-90d)'
    elif d <= 180:
        return '❄️ Cool (90-180d)'
    else:
        return '🧊 Cold (180+d)'

contacts['recency'] = contacts['days_silent'].apply(_recency_bucket)

# Short key for filtering (without emoji)
def _recency_key(d):
    if pd.isna(d):
        return 'no_date'
    if d <= 30:
        return 'hot'
    elif d <= 90:
        return 'warm'
    elif d <= 180:
        return 'cool'
    else:
        return 'cold'

contacts['recency_key'] = contacts['days_silent'].apply(_recency_key)


# ══════════════════════════════════════════════════════════════════════════════

tab_contacts, tab_segments, tab_compose = st.tabs([
    "👥 Contacts",
    "🎯 Segments",
    "✉️ Email Composer",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: CONTACTS
# ══════════════════════════════════════════════════════════════════════════════

with tab_contacts:

    # ── Add-to-overlay form ──────────────────────────────────────────────────
    with st.expander("➕ Add contact (overlay)", expanded=False):
        st.caption("Adds to `content/crm_overlay.json` — the team All-e sheet is **not** modified. If the company already exists in All-e, the overlay entry will take precedence.")

        with st.form("add_overlay_form", clear_on_submit=True):
            oc1, oc2, oc3 = st.columns(3)
            with oc1:
                ov_company = st.text_input("Company *", key="ov_company")
                ov_vertical = st.text_input("Vertical", key="ov_vertical", placeholder="FMEG, Auto, Pharma…")
                ov_entity = st.selectbox("Entity Type", ["", "OEM", "Distributor", "Retailer", "Agency", "Other"], key="ov_entity")
            with oc2:
                ov_status = st.selectbox("Lead Status",
                    ["1-Exploring", "2-POC", "3-Negotiation", "4-Won", "5-Lost", "0-Cold"],
                    index=0, key="ov_status")
                ov_segment = st.selectbox("Segment", ["Active", "Dropped"], key="ov_segment")
                ov_owner = st.text_input("Outreach Owner", key="ov_owner")
            with oc3:
                ov_first = st.date_input("First Contact", value=pd.Timestamp.now().date(), key="ov_first")
                ov_last = st.date_input("Last Contact", value=pd.Timestamp.now().date(), key="ov_last")
                ov_source = st.text_input("Source", key="ov_source", placeholder="Outbound, Inbound, Referral…")

            ov_agents = st.text_input("Agents / Workstreams", key="ov_agents",
                placeholder="e.g. All-e — 4 workstreams (Search, Catalog, KG API, eCom)")
            ov_conv = st.text_area("Conversation details", key="ov_conv", height=100)
            ov_comments = st.text_area("Comments / Follow-ups", key="ov_comments", height=70)

            st.markdown("**People** (at least one required)")
            people_inputs = []
            for i in range(5):
                pc1, pc2, pc3 = st.columns([2, 3, 2])
                with pc1:
                    pname = st.text_input(f"Name {i+1}", key=f"ov_pname_{i}", label_visibility="collapsed", placeholder=f"Name {i+1}")
                with pc2:
                    pemail = st.text_input(f"Email {i+1}", key=f"ov_pemail_{i}", label_visibility="collapsed", placeholder=f"Email {i+1}")
                with pc3:
                    pdesig = st.text_input(f"Title {i+1}", key=f"ov_pdesig_{i}", label_visibility="collapsed", placeholder=f"Title {i+1}")
                people_inputs.append((pname, pemail, pdesig))

            submitted = st.form_submit_button("💾 Save to overlay", type="primary")

            if submitted:
                if not ov_company.strip():
                    st.error("Company name is required.")
                else:
                    people = [
                        {"name": n.strip(), "email": e.strip(), "designation": d.strip()}
                        for (n, e, d) in people_inputs
                        if n.strip() or e.strip()
                    ]
                    if not people:
                        st.error("Add at least one person (name or email).")
                    else:
                        import json
                        from pathlib import Path
                        overlay_path = Path(__file__).parent.parent / "content" / "crm_overlay.json"
                        try:
                            with open(overlay_path) as f:
                                overlay_data = json.load(f)
                        except FileNotFoundError:
                            overlay_data = {"_comment": "Local CRM overlay", "contacts": []}

                        new_entry = {
                            "company": ov_company.strip(),
                            "vertical": ov_vertical.strip(),
                            "entity_type": ov_entity,
                            "lead_status": ov_status,
                            "segment": ov_segment,
                            "agents": ov_agents.strip(),
                            "source": ov_source.strip(),
                            "outreach_owner": ov_owner.strip(),
                            "first_contact": ov_first.strftime("%Y-%m-%d"),
                            "last_contact": ov_last.strftime("%Y-%m-%d"),
                            "conv_details": ov_conv.strip(),
                            "comments": ov_comments.strip(),
                            "people": people,
                        }

                        # Replace existing entry for same company (case-insensitive), else append
                        existing_contacts = overlay_data.get("contacts", [])
                        filtered_contacts = [
                            c for c in existing_contacts
                            if c.get("company", "").strip().lower() != ov_company.strip().lower()
                        ]
                        filtered_contacts.append(new_entry)
                        overlay_data["contacts"] = filtered_contacts

                        with open(overlay_path, "w") as f:
                            json.dump(overlay_data, f, indent=2, ensure_ascii=False)

                        st.success(f"✅ Saved **{ov_company.strip()}** to overlay ({len(people)} contact{'s' if len(people) != 1 else ''}). Refreshing…")
                        st.cache_data.clear()
                        st.rerun()

    with_email = contacts[contacts['has_email']]
    active_w = with_email[with_email['segment'] == 'Active']
    dropped_w = with_email[with_email['segment'] == 'Dropped']

    # Unique companies
    total_companies = contacts['company'].nunique()

    # Recency KPIs (cross-segment)
    hot_n = with_email[with_email['recency_key'] == 'hot']['company'].nunique()
    warm_n = with_email[with_email['recency_key'] == 'warm']['company'].nunique()
    cool_n = with_email[with_email['recency_key'] == 'cool']['company'].nunique()
    cold_n = with_email[with_email['recency_key'] == 'cold']['company'].nunique()

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric("Total Contacts", len(with_email))
    with c2:
        st.metric("Companies", total_companies)
    with c3:
        st.metric("🔥 Hot", hot_n, help="Met within last 30 days")
    with c4:
        st.metric("☀️ Warm", warm_n, help="Last contact 30-90 days ago")
    with c5:
        st.metric("❄️ Cool", cool_n, help="Last contact 90-180 days ago")
    with c6:
        st.metric("🧊 Cold", cold_n, help="Last contact 180+ days ago")

    # Filters
    st.markdown("---")
    fc1, fc2, fc3, fc4, fc5 = st.columns(5)
    with fc1:
        seg_filter = st.selectbox("Segment", ["All", "Active", "Dropped"], key="crm_seg")
    with fc2:
        recency_options = ["All", "🔥 Hot (<30d)", "☀️ Warm (30-90d)", "❄️ Cool (90-180d)", "🧊 Cold (180+d)", "⚫ No date"]
        rec_filter = st.selectbox("Recency", recency_options, key="crm_recency")
    with fc3:
        verticals = sorted(contacts['vertical'].unique().tolist())
        vert_filter = st.selectbox("Vertical", ["All"] + [v for v in verticals if v], key="crm_vert")
    with fc4:
        statuses = sorted([s for s in contacts['lead_status'].unique() if s])
        status_filter = st.selectbox("Status", ["All"] + statuses, key="crm_status")
    with fc5:
        search = st.text_input("Search", placeholder="Company, name, email", key="crm_search")

    # Apply filters
    filtered = contacts[contacts['has_email']].copy()
    if seg_filter != "All":
        filtered = filtered[filtered['segment'] == seg_filter]
    if rec_filter != "All":
        filtered = filtered[filtered['recency'] == rec_filter]
    if vert_filter != "All":
        filtered = filtered[filtered['vertical'] == vert_filter]
    if status_filter != "All":
        filtered = filtered[filtered['lead_status'] == status_filter]
    if search:
        mask = (
            filtered['company'].str.contains(search, case=False, na=False) |
            filtered['person_name'].str.contains(search, case=False, na=False) |
            filtered['email'].str.contains(search, case=False, na=False)
        )
        filtered = filtered[mask]

    # Sort by last contact
    filtered = filtered.sort_values('last_contact', ascending=False, na_position='last')

    st.caption(f"Showing {len(filtered)} contacts")

    # Display table — add source indicator (📋 All-e sheet, 📌 Local overlay)
    display = filtered[['company', 'person_name', 'email', 'designation',
                         'lead_status', 'segment', 'recency', 'vertical', 'last_contact', '_overlay']].copy()
    display = display.reset_index(drop=True)
    display.insert(0, '#', range(1, len(display) + 1))

    if 'last_contact' in display.columns:
        display['last_contact'] = display['last_contact'].apply(
            lambda x: x.strftime('%d %b %Y') if pd.notna(x) else '—')

    display['Source'] = display['_overlay'].apply(lambda x: '📌 Overlay' if x else '📋 All-e')
    display = display.drop(columns=['_overlay'])

    display = display.rename(columns={
        'company': 'Company', 'person_name': 'Name', 'email': 'Email',
        'designation': 'Title', 'lead_status': 'Status', 'segment': 'Segment',
        'recency': 'Recency', 'vertical': 'Vertical', 'last_contact': 'Last Contact',
    })

    st.dataframe(display, use_container_width=True, height=500, hide_index=True)

    # Contact detail
    st.markdown("---")
    companies = filtered['company'].unique().tolist()
    if companies:
        selected_co = st.selectbox("View company detail", companies, key="crm_detail")
        co_contacts = filtered[filtered['company'] == selected_co]
        if not co_contacts.empty:
            first = co_contacts.iloc[0]
            st.markdown(f"### {first['company']}")
            col_a, col_b = st.columns([3, 2])
            with col_a:
                st.markdown(f"**Vertical:** {first['vertical']}")
                st.markdown(f"**Status:** {first['lead_status']} | **Segment:** {first['segment']}")
                st.markdown(f"**Product Interest:** {first['agents']}")
                if first.get('source'):
                    st.markdown(f"**Source:** {first['source']}")
            with col_b:
                if pd.notna(first.get('first_contact')):
                    st.markdown(f"**First Contact:** {first['first_contact'].strftime('%d %b %Y')}")
                if pd.notna(first.get('last_contact')):
                    st.markdown(f"**Last Contact:** {first['last_contact'].strftime('%d %b %Y')}")
                if first.get('outreach_owner'):
                    st.markdown(f"**Outreach Owner:** {first['outreach_owner']}")

            st.markdown("**Contacts:**")
            for _, c in co_contacts.iterrows():
                title = f" — {c['designation']}" if c['designation'] else ""
                st.markdown(f"- **{c['person_name']}** ({c['email']}){title}")

            if first.get('conv_details') and first['conv_details'] not in ('', 'nan'):
                with st.expander("📝 Latest Conversation"):
                    st.markdown(first['conv_details'][:1000])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: SEGMENTS
# ══════════════════════════════════════════════════════════════════════════════

with tab_segments:
    st.markdown("### Audience Segments")
    st.caption("Different segments need different outreach. Hot leads get a direct follow-up; cold leads need a re-introduction.")

    emailable = contacts[contacts['has_email']]

    # ── Recency × Segment matrix ──────────────────────────────────────────────
    st.markdown("#### 🎯 Recency × Status Matrix")
    st.caption("The cross-tab that matters most — recently met leads (Hot/Warm) are your priority")

    recency_order = ['🔥 Hot (<30d)', '☀️ Warm (30-90d)', '❄️ Cool (90-180d)', '🧊 Cold (180+d)', '⚫ No date']
    matrix = emailable.groupby(['recency', 'segment'])['company'].nunique().unstack(fill_value=0)
    matrix = matrix.reindex(recency_order, fill_value=0)
    if 'Active' not in matrix.columns:
        matrix['Active'] = 0
    if 'Dropped' not in matrix.columns:
        matrix['Dropped'] = 0
    matrix['Total'] = matrix['Active'] + matrix['Dropped']
    matrix = matrix.reset_index().rename(columns={'recency': 'Recency'})
    st.dataframe(matrix, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Outreach Priority Groups ──────────────────────────────────────────────
    st.markdown("#### 📬 Outreach Priority Groups")
    st.caption("These are the segments that should receive different emails")

    priority_groups = [
        {
            'key': 'hot_active',
            'label': '🔥 Hot + Active',
            'desc': 'Met recently, still in pipeline — direct follow-up',
            'filter': (emailable['recency_key'] == 'hot') & (emailable['segment'] == 'Active'),
            'template': 'Follow-up (Active Leads)',
        },
        {
            'key': 'hot_dropped',
            'label': '🔥 Hot + Dropped',
            'desc': 'Met recently but marked dropped — re-engage immediately',
            'filter': (emailable['recency_key'] == 'hot') & (emailable['segment'] == 'Dropped'),
            'template': 'Hot Re-engagement (Recent)',
        },
        {
            'key': 'warm',
            'label': '☀️ Warm (30-90d)',
            'desc': 'Conversation fading — nudge with a relevant update',
            'filter': (emailable['recency_key'] == 'warm'),
            'template': 'Warm Nudge',
        },
        {
            'key': 'cool',
            'label': '❄️ Cool (90-180d)',
            'desc': 'Gone quiet — reintroduce with what\'s new',
            'filter': (emailable['recency_key'] == 'cool'),
            'template': 'Cool Re-introduction',
        },
        {
            'key': 'cold',
            'label': '🧊 Cold (180+d)',
            'desc': 'Essentially fresh — treat like a new intro with "we met before" context',
            'filter': (emailable['recency_key'] == 'cold'),
            'template': 'Cold Re-introduction',
        },
        {
            'key': 'no_date',
            'label': '⚫ No Contact Date',
            'desc': 'No recorded interaction — treat as cold intro',
            'filter': (emailable['recency_key'] == 'no_date'),
            'template': 'Meeting Request (Cold)',
        },
    ]

    for pg in priority_groups:
        grp = emailable[pg['filter']]
        n_companies = grp['company'].nunique()
        n_contacts = len(grp)
        if n_contacts == 0:
            continue
        with st.expander(f"**{pg['label']}** — {n_companies} companies, {n_contacts} contacts  ·  _{pg['desc']}_"):
            st.caption(f"Suggested template: **{pg['template']}**")
            preview = grp[['company', 'person_name', 'email', 'designation', 'lead_status', 'last_contact']].copy()
            preview['last_contact'] = preview['last_contact'].apply(
                lambda x: x.strftime('%d %b %Y') if pd.notna(x) else '—')
            preview = preview.sort_values('last_contact', ascending=False)
            st.dataframe(preview.rename(columns={
                'company': 'Company', 'person_name': 'Name', 'email': 'Email',
                'designation': 'Title', 'lead_status': 'Status', 'last_contact': 'Last Contact',
            }), use_container_width=True, hide_index=True, height=250)

    st.markdown("---")

    # ── Active / Dropped status breakdown (kept for reference) ────────────────
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("#### Active Leads by Status")
        active_all = emailable[emailable['segment'] == 'Active']
        status_counts = active_all.groupby('lead_status')['company'].nunique()

        status_labels = {
            '1-Pilot': ('🟢', 'Pilot'),
            '2-POC': ('🔵', 'POC'),
            '3-Proposal sent': ('🟡', 'Proposal Sent'),
            '4-TOF': ('⚪', 'Top of Funnel'),
        }
        for status_key, (icon, label) in status_labels.items():
            count = status_counts.get(status_key, 0)
            contacts_in = len(active_all[active_all['lead_status'] == status_key])
            st.markdown(f"{icon} **{label}** — {count} companies, {contacts_in} contacts")

        st.markdown(f"**Total active:** {active_all['company'].nunique()} companies, {len(active_all)} contacts")

    with col_r:
        st.markdown("#### Dropped Leads by Owner")
        dropped_all = emailable[emailable['segment'] == 'Dropped']

        owner_counts = dropped_all.groupby('outreach_owner')['company'].nunique()
        for owner, count in owner_counts.items():
            if owner and owner not in ('', 'nan', 'Not needed'):
                contacts_in = len(dropped_all[dropped_all['outreach_owner'] == owner])
                st.markdown(f"👤 **Owner: {owner}** — {count} companies, {contacts_in} contacts")

        not_needed = len(dropped_all[dropped_all['outreach_owner'].isin(['Not needed', ''])])
        st.markdown(f"⏸️ **Not needed / Unassigned** — {not_needed} contacts")
        st.markdown(f"**Total dropped (with email):** {dropped_all['company'].nunique()} companies, {len(dropped_all)} contacts")

    st.markdown("---")

    # ── By Vertical ───────────────────────────────────────────────────────────
    col_v, col_g = st.columns(2)

    with col_v:
        st.markdown("#### By Vertical")
        vert_df = emailable.groupby(['vertical', 'segment'])['company'].nunique().reset_index()
        vert_df.columns = ['Vertical', 'Segment', 'Companies']
        vert_df = vert_df[vert_df['Vertical'] != '']
        if not vert_df.empty:
            fig_v = px.bar(vert_df.sort_values('Companies', ascending=True),
                           x='Companies', y='Vertical', color='Segment',
                           orientation='h', color_discrete_map={'Active': '#4F46E5', 'Dropped': '#6B7280'})
            fig_v.update_layout(height=400, template="plotly_dark",
                                margin=dict(l=20, r=20, t=20, b=20), legend=dict(orientation='h', y=-0.15))
            st.plotly_chart(fig_v, use_container_width=True)

    with col_g:
        st.markdown("#### By Entity Type")
        geo_df = emailable.groupby(['entity_type', 'segment'])['company'].nunique().reset_index()
        geo_df.columns = ['Entity', 'Segment', 'Companies']
        geo_df = geo_df[geo_df['Entity'] != '']
        if not geo_df.empty:
            fig_g = px.bar(geo_df.sort_values('Companies', ascending=True),
                           x='Companies', y='Entity', color='Segment',
                           orientation='h', color_discrete_map={'Active': '#4F46E5', 'Dropped': '#6B7280'})
            fig_g.update_layout(height=400, template="plotly_dark",
                                margin=dict(l=20, r=20, t=20, b=20), legend=dict(orientation='h', y=-0.15))
            st.plotly_chart(fig_g, use_container_width=True)

    # ── Staleness view ────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Engagement Staleness (Active Leads)")
    if 'days_silent' in emailable.columns:
        active_stale = emailable[emailable['segment'] == 'Active'].copy()
        active_stale = active_stale[active_stale['days_silent'].notna()]

        def stale_bucket(d):
            if d <= 7:
                return '🟢 <7 days'
            elif d <= 14:
                return '🟡 7-14 days'
            elif d <= 30:
                return '🟠 14-30 days'
            else:
                return '🔴 30+ days'

        active_stale['staleness'] = active_stale['days_silent'].apply(stale_bucket)
        stale_summary = active_stale.groupby('staleness')['company'].nunique().reset_index()
        stale_summary.columns = ['Staleness', 'Companies']
        stale_summary = stale_summary.sort_values('Staleness')
        st.dataframe(stale_summary, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: EMAIL COMPOSER
# ══════════════════════════════════════════════════════════════════════════════

EMAIL_TEMPLATES = {
    "Follow-up (Active Leads)": {
        "subject": "Following up — {company} x All-e",
        "body": """Hi {name},

Following up on our recent conversation about All-e for {company}. Wanted to check if you had any questions or needed anything specific from our side to move forward.

Happy to jump on a quick call whenever works for you.

Best,
{sender}""",
    },
    "Hot Re-engagement (Recent)": {
        "subject": "Quick follow-up — {company}",
        "body": """Hi {name},

Good speaking recently about {company}. I wanted to circle back with something specific rather than a generic nudge.

Since we last spoke, we've rolled out a few things that map to what you were evaluating — happy to share a short walkthrough focused on your use case.

Does a 20-min call this week work?

Best,
{sender}""",
    },
    "Warm Nudge": {
        "subject": "Quick check-in — {company}",
        "body": """Hi {name},

It's been a few weeks since we last spoke about All-e for {company}. I didn't want the conversation to go stale without giving you something concrete.

A few things have shipped since — agentic ordering via WhatsApp, SKU-level performance root cause analysis, and affiliate analytics. If any of these are closer to what you need, happy to share a short demo.

Is this week good for a quick call?

Best,
{sender}""",
    },
    "Cool Re-introduction": {
        "subject": "An update from Graas — thought of {company}",
        "body": """Hi {name},

It's been a few months since we last connected about All-e. Wanted to share a quick update on where we've taken things — especially because a few of the capabilities are directly relevant to {company} in {vertical}.

What's new:
- Agentic ordering via WhatsApp for distributors and retailers (ERP-integrated, ~90 sec from invoice photo to order)
- Root cause analytics — understand why sales declined by SKU × platform × market
- Affiliate and creator analytics across Shopee, Lazada, TikTok

Would you be open to a fresh 20-min conversation to see if timing is better now?

Best,
{sender}""",
    },
    "Cold Re-introduction": {
        "subject": "Reconnecting — Graas All-e for {company}",
        "body": """Hi {name},

We connected some time back about All-e for {company}. A lot has changed on our side since then, so I wanted to reach out fresh rather than continue where we left off.

Short version: we've moved from building agents to running them in production for brands in {vertical}. Order processing is down from days to minutes, and we're seeing real conversion lift on the consumer side.

If it's worth a fresh look, I'd be happy to do a 20-min walkthrough focused on where you are today — no assumptions from last time.

Best,
{sender}""",
    },
    "Re-engagement (Dropped Leads)": {
        "subject": "Catching up — {company} x Graas All-e",
        "body": """Hi {name},

Hope you're doing well. We last connected regarding All-e for {company}, and I wanted to share some updates on what we've been building since then.

We've recently launched agentic AI workflows for offline sales teams — AI agents that handle distributor ordering via WhatsApp, product discovery, and field force automation. A leading electronics major and a large agri major are already piloting these with strong early results.

Would love to reconnect and explore if there's a fit now. Are you open to a quick 20-min call this week?

Best,
{sender}""",
    },
    "Product Update": {
        "subject": "New capabilities in All-e — thought of {company}",
        "body": """Hi {name},

Quick update from our side — we've shipped some significant improvements to All-e that I thought would be relevant for {company}:

- Agentic ordering via WhatsApp — distributors/retailers can place orders through a conversational AI agent
- Product discovery agent — helps sales reps and end-customers find the right product from large catalogues (60K+ SKUs)
- Field force automation — AI-powered visit planning, stock-taking, and order capture

Would be great to walk you through a quick demo. Would any day this week work?

Best,
{sender}""",
    },
    "Meeting Request (Cold)": {
        "subject": "Quick intro — Graas All-e for {company}",
        "body": """Hi {name},

I'm reaching out from Graas. We've built All-e — an AI agent platform purpose-built for e-commerce and offline sales teams.

Given {company}'s focus on {vertical}, I think there could be a strong fit, particularly around:
- AI-powered ordering for distributors/retailers
- Product discovery and recommendation agents
- Sales force automation

Would you be open to a 20-minute call to explore?

Best,
{sender}""",
    },
    "Custom": {
        "subject": "",
        "body": "",
    },
}

with tab_compose:
    st.markdown("### ✉️ Compose Outreach Email")

    # ── Step 1: Select recipients ─────────────────────────────────────────────
    st.markdown("#### 1. Select Recipients")

    rc1, rc2, rc3, rc4 = st.columns(4)
    with rc1:
        comp_seg = st.selectbox("Segment", ["Active", "Dropped", "All"], key="comp_seg")
    with rc2:
        recency_opts = ["All", "🔥 Hot (<30d)", "☀️ Warm (30-90d)", "❄️ Cool (90-180d)", "🧊 Cold (180+d)", "⚫ No date"]
        comp_recency = st.selectbox("Recency", recency_opts, key="comp_recency")
    with rc3:
        comp_statuses = sorted([s for s in contacts['lead_status'].unique() if s])
        comp_status = st.selectbox("Status", ["All"] + comp_statuses, key="comp_status")
    with rc4:
        comp_owners = sorted([o for o in contacts['outreach_owner'].unique() if o and o not in ('nan', 'Not needed', '')])
        comp_owner = st.selectbox("Owner", ["All"] + comp_owners, key="comp_owner")

    # Filter recipients
    recipients = contacts[contacts['has_email']].copy()
    if comp_seg != "All":
        recipients = recipients[recipients['segment'] == comp_seg]
    if comp_recency != "All":
        recipients = recipients[recipients['recency'] == comp_recency]
    if comp_status != "All":
        recipients = recipients[recipients['lead_status'] == comp_status]
    if comp_owner != "All":
        recipients = recipients[recipients['outreach_owner'] == comp_owner]

    st.caption(f"📬 {len(recipients)} contacts across {recipients['company'].nunique()} companies")

    # Smart template suggestion based on recency filter
    suggested_template = None
    if comp_recency == "🔥 Hot (<30d)" and comp_seg == "Active":
        suggested_template = "Follow-up (Active Leads)"
    elif comp_recency == "🔥 Hot (<30d)" and comp_seg == "Dropped":
        suggested_template = "Hot Re-engagement (Recent)"
    elif comp_recency == "☀️ Warm (30-90d)":
        suggested_template = "Warm Nudge"
    elif comp_recency == "❄️ Cool (90-180d)":
        suggested_template = "Cool Re-introduction"
    elif comp_recency == "🧊 Cold (180+d)":
        suggested_template = "Cold Re-introduction"
    elif comp_recency == "⚫ No date":
        suggested_template = "Meeting Request (Cold)"

    if suggested_template:
        st.info(f"💡 Suggested template for this segment: **{suggested_template}**")

    with st.expander(f"View {len(recipients)} recipients"):
        if not recipients.empty:
            r_display = recipients[['company', 'person_name', 'email', 'designation', 'segment', 'recency', 'last_contact']].copy()
            r_display = r_display.reset_index(drop=True)
            r_display['last_contact'] = r_display['last_contact'].apply(
                lambda x: x.strftime('%d %b %Y') if pd.notna(x) else '—')
            r_display.insert(0, '#', range(1, len(r_display) + 1))
            st.dataframe(r_display.rename(columns={
                'company': 'Company', 'person_name': 'Name', 'email': 'Email',
                'designation': 'Title', 'segment': 'Segment',
                'recency': 'Recency', 'last_contact': 'Last Contact',
            }), use_container_width=True, hide_index=True, height=300)

    st.markdown("---")

    # ── Step 2: Choose template ───────────────────────────────────────────────
    st.markdown("#### 2. Choose Template & Compose")

    tc1, tc2 = st.columns([1, 2])
    with tc1:
        template_name = st.radio("Template", list(EMAIL_TEMPLATES.keys()), key="template_sel")

    template = EMAIL_TEMPLATES[template_name]

    with tc2:
        sender_name = st.text_input("Sender name", value="Prem", key="sender_name")
        subject = st.text_input("Subject", value=template["subject"], key="email_subject")
        body = st.text_area("Body", value=template["body"], height=300, key="email_body")

    st.markdown("---")

    # ── Step 3: Preview ───────────────────────────────────────────────────────
    st.markdown("#### 3. Preview")

    if not recipients.empty:
        preview_companies = recipients['company'].unique().tolist()
        preview_co = st.selectbox("Preview for", preview_companies, key="preview_co")

        preview_contacts = recipients[recipients['company'] == preview_co]
        if not preview_contacts.empty:
            pc = preview_contacts.iloc[0]
            # Render template
            rendered_subject = subject.format(
                company=pc['company'], name=pc['person_name'],
                vertical=pc['vertical'], sender=sender_name,
            ) if '{' in subject else subject

            rendered_body = body
            for key, val in {
                '{company}': pc['company'],
                '{name}': pc['person_name'],
                '{vertical}': pc['vertical'],
                '{sender}': sender_name,
                '{designation}': pc['designation'],
            }.items():
                rendered_body = rendered_body.replace(key, str(val))

            to_list = ', '.join(preview_contacts['email'].tolist())

            st.markdown(f"""
<div class="email-preview">
    <div class="to">To: {to_list}</div>
    <div class="subject">Subject: {rendered_subject}</div>
    <hr style="border-color: #334155; margin: 10px 0;">
    <div class="body">{rendered_body}</div>
</div>
""", unsafe_allow_html=True)

    st.markdown("---")

    # ── Step 4: Actions ───────────────────────────────────────────────────────
    st.markdown("#### 4. Copy & Send")

    ac1, ac2 = st.columns(2)

    with ac1:
        st.markdown("**All recipient emails** (copy into Gmail BCC)")
        all_emails = ', '.join(recipients['email'].unique().tolist())
        st.code(all_emails, language=None)

    with ac2:
        st.markdown("**Emails by company** (for personalized sends)")
        for co in recipients['company'].unique()[:20]:
            co_emails = recipients[recipients['company'] == co]['email'].tolist()
            co_names = recipients[recipients['company'] == co]['person_name'].tolist()
            names_str = ', '.join(co_names)
            emails_str = ', '.join(co_emails)
            st.markdown(f"**{co}** ({names_str})")
            st.code(emails_str, language=None)

        if len(recipients['company'].unique()) > 20:
            st.caption(f"... and {len(recipients['company'].unique()) - 20} more companies")
