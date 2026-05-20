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

st.info(
    "📖 **Email playbook** — Amruta & team's reference for segments + content. "
    "[Open Google Doc ↗](https://docs.google.com/document/d/1kbDEjVTpVpFdrdtxhhEomdtss1f05O2Fm8ph4Y1TY1Y/edit?tab=t.0)",
    icon="📖",
)

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


# ══════════════════════════════════════════════════════════════════════════════
# PLAYBOOK BUCKETS — sourced from "All-e email re-engagement" Google Doc
# Last sync: 7 May 2026 (V1). Doc:
# https://docs.google.com/document/d/1kbDEjVTpVpFdrdtxhhEomdtss1f05O2Fm8ph4Y1TY1Y
# ══════════════════════════════════════════════════════════════════════════════

PLAYBOOK_BUCKETS = {
    "Timing-Paused": {
        "icon": "⏸️",
        "color": "#3B82F6",
        "desc": "Intent was real. Window closed (reorgs, budgets, planning). Not a fit issue. Highest recovery potential.",
        "framework": "A — Market Signal",
        "cadence": "1 insight email → 3-week wait → 1 follow-on different angle → pause",
        "rules": [
            "Use a vertical insight as the re-entry — peer-level, brief, zero urgency",
            "Don't reference the prior stall",
            "Reinforce the problem hasn't been solved by waiting",
        ],
        "accounts": [
            "Polycab", "Haier", "Prince Pipes", "Voltas",
            "Forest Essentials", "Versuni", "Shalimar Paints",
            "910 Indonesia", "Chickin",
        ],
    },
    "Evaluation Stalled": {
        "icon": "🔄",
        "color": "#F59E0B",
        "desc": "Multi-stakeholder engagement happened. Proposal/POC done. Stall is at internal approval — not fit rejection.",
        "framework": "B — Outcome Reference",
        "cadence": "1 outcome-reference email → 4-week wait → 1 short follow-on → pause",
        "rules": [
            "Lead with one specific deployment outcome in their vertical",
            "Frame around integration complexity (ERP sync, credit, scheme logic)",
            "Reads like a practitioner's note, not a sales email",
            "Kajaria & Kent RO: do NOT reference voice — use WA/FA digitization angle",
        ],
        "accounts": [
            "Wakefit", "SRMB", "RR Kabel", "TTK Prestige",
            "Aditya Birla Fashion", "Reebok",
            "Power Buy", "Wipro Enterprises", "Rich Products",
            "Eureka Forbes", "KRBL", "Kajaria", "Kent RO",
        ],
    },
    "Competitor-Adjacent": {
        "icon": "🛡️",
        "color": "#A855F7",
        "desc": "Has adjacent solution (Bizom, yellow.ai, Salesforce, Haptik). Re-entry is the gap their tool can't close — not replacement.",
        "framework": "C — Adoption Gap",
        "cadence": "1 analytical insight email → 4-6 week pause → re-evaluate",
        "rules": [
            "Position All-e as additive — never competitive",
            "Never name-drop their vendor's limitations",
            "Use the adoption-gap data (DMS/SFA at <15%) as re-entry",
            "Borosil: do NOT reference voice — find a non-voice angle",
        ],
        "accounts": [
            "Sheela Foam", "Group Meeran", "Usha Electricals",
            "Bajaj Consumer Care", "Borosil",
        ],
    },
    "Ghost Accounts": {
        "icon": "👻",
        "color": "#6B7280",
        "desc": "Met once or twice, genuine initial interest, then silence. One precisely-targeted email — never a sequence.",
        "framework": "E — Specific Trigger",
        "cadence": "1 targeted email only. No follow-on unless they reply. If no reply in 3 weeks, archive 90 days.",
        "rules": [
            "Reference the SPECIFIC use case from meeting notes — never generic",
            "Reads like a peer note, not a vendor follow-up",
        ],
        "accounts": [
            "Finolex", "Topcem", "Hindustan Pencils", "KLF Nirmal",
            "KRBL", "TIPL", "Talbros", "Dalmia Bharat", "Fairprice",
            "Duroflex",
        ],
    },
    "Strategic Slow Movers": {
        "icon": "🎯",
        "color": "#10B981",
        "desc": "Large enterprises, well-qualified use case, multi-stakeholder. Internal velocity is structurally low. Long-horizon maintenance.",
        "framework": "D — Founder-Tone Strategic Note",
        "cadence": "1 insight per 4-6 weeks, indefinitely — until they signal readiness or explicitly close",
        "rules": [
            "Strategic, founder-to-senior-leader. Reads like a quarterly letter.",
            "No product references",
            "Send as Prem or Amruta directly — not generic insights@",
        ],
        "accounts": [
            "Wipro Enterprises", "RR Kabel", "TTK Prestige",
            "Polycab", "Haier", "Tata Consumer",
            "Aditya Birla Fashion", "Reebok",
        ],
    },
}

# Per-account special instructions from playbook footnotes
PLAYBOOK_NOTES = {
    "Sheela Foam": "⚠️ HOLD OFF for now (playbook footnote — pls hold off)",
    "Polycab": "ℹ️ Narrative angle: retailer-to-distributor ordering specifically",
    "Versuni": "ℹ️ OneChef proposal already sent (INR 5L+1L monthly), dropped Apr 20",
    "Sheela Foam ": "⚠️ HOLD OFF for now",  # trailing-space variant
    "Haier": "ℹ️ Acquisition pause should now have passed",
    "Forest Essentials": "ℹ️ Internal systems change should now be complete",
    "Borosil": "⚠️ Evaluating voice players — DO NOT reference voice in outreach",
    "Kajaria": "⚠️ Voice startup pilot first; do NOT reference voice. Use WA/FA digitization.",
    "Kent RO": "⚠️ Working with Haptik for outbound voice. Do NOT reference voice.",
    "Bajaj Electricals": "🚫 Already using conversational AI (voice) — explicit low interest",
    "Anmol Industries": "🚫 Has Bizom DMS with direct overlap — not before 9 months",
    "Hindware": "🚫 Rejected formal proposal Feb 2026 — re-engage Aug 2026 only on trigger",
    "Growsari": "🚫 Pilot discontinued Mar 2026 — revisit Jan 2027 only",
    "Godrej Consumer Products": "↪️ Hand off to hoppr GTM (marketplace use case, not All-e)",
    "Cello World": "↪️ Hand off to hoppr GTM (D2C too small, wants hoppr for marketplace)",
}

NO_TOUCH = {
    "Structural ICP Mismatch (permanent)": {
        "icon": "🚫",
        "desc": "No B2B trade/distribution channel that All-e addresses.",
        "accounts": {
            "Liberty Steel": "Contract manufacturing, no distributor network",
            "Makson Group": "Contract manufacturing, 10-15 customers, no retail",
            "Genus Power": "Government tenders, no distributor channel",
            "Merino Group": "Custom projects, project teams upfront",
            "Tata Electronics": "4 warehouses, customer pickup, no channel",
            "Amber Group": "AC components to OEMs, no retail",
            "Lubi Electronics": "Auto electronic parts to OEMs",
            "Stelmec": "B2B industrial, no trade distribution",
            "AB InBev": "State excise controls, sector explicitly unsuitable",
            "Bajaj Electricals": "Already using conversational AI for retailer ordering",
        },
    },
    "Hard Rejection / Pilot Ended (6-12mo cooldown)": {
        "icon": "⛔",
        "desc": "Off list for 6-12 months. Re-engage only on specific trigger.",
        "accounts": {
            "Hindware": "Rejected proposal Feb 2026, chose competitor. Re-engage Aug 2026 only on trigger (e.g. competitor failure)",
            "Growsari": "Pilot discontinued Mar 2026 (H1 profitability + ROI). Revisit Jan 2027",
            "Anmol Industries": "Has Bizom DMS with direct overlap. Not before 9 months",
        },
    },
    "Product Misdirection → hoppr": {
        "icon": "↪️",
        "desc": "Live prospects but for hoppr — not All-e. Hand off to hoppr GTM.",
        "accounts": {
            "Godrej Consumer Products": "hoppr for Shopee/TikTok marketplace. Hand off, remove from All-e pipeline.",
            "Cello World": "D2C only 50 orders/day, too small for All-e. Wants hoppr for marketplace.",
        },
    },
}


def _normalize_company(name: str) -> str:
    """Lowercase, strip, collapse spaces — for fuzzy matching."""
    return " ".join((name or "").lower().split())


def playbook_lookup(company: str):
    """Returns dict with bucket(s), no_touch info, and special notes for a company."""
    cl = _normalize_company(company)
    if not cl:
        return {"buckets": [], "no_touch": None, "note": None}

    # No-touch check first (highest priority)
    no_touch = None
    for category, info in NO_TOUCH.items():
        for acc, reason in info["accounts"].items():
            an = _normalize_company(acc)
            if an in cl or cl in an:
                no_touch = {"category": category, "icon": info["icon"], "reason": reason}
                break
        if no_touch:
            break

    # All matching buckets (some accounts appear in multiple)
    matched_buckets = []
    for bucket, info in PLAYBOOK_BUCKETS.items():
        for acc in info["accounts"]:
            an = _normalize_company(acc)
            if an in cl or cl in an:
                matched_buckets.append(bucket)
                break

    # Special note (look up by playbook key, fuzzy)
    note = None
    for k, v in PLAYBOOK_NOTES.items():
        kn = _normalize_company(k)
        if kn in cl or cl in kn:
            note = v
            break

    return {"buckets": matched_buckets, "no_touch": no_touch, "note": note}


# Apply to contacts dataframe — accounts can belong to multiple buckets
# (playbook footnote: "Many accounts in this bucket are also present in
# other buckets — E.g. Polycab.")
def _bucket_label_primary(company):
    """Primary bucket = first match. Used for KPI counts to avoid double-counting."""
    res = playbook_lookup(company)
    if res["no_touch"]:
        return f"🚫 No Touch — {res['no_touch']['category'].split(' (')[0]}"
    if res["buckets"]:
        return res["buckets"][0]
    return None

contacts["playbook_bucket"] = contacts["company"].apply(_bucket_label_primary)
contacts["playbook_buckets_all"] = contacts["company"].apply(
    lambda c: playbook_lookup(c)["buckets"]
)
contacts["playbook_no_touch"] = contacts["company"].apply(
    lambda c: playbook_lookup(c)["no_touch"]
)
contacts["playbook_note"] = contacts["company"].apply(
    lambda c: playbook_lookup(c)["note"]
)

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

tab_contacts, tab_segments, tab_compose, tab_analytics = st.tabs([
    "👥 Contacts",
    "🎯 Segments",
    "✉️ Email Composer",
    "📊 Analytics",
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
    st.markdown("### Re-engagement Buckets")
    st.caption(
        "Sourced from Amruta's *All-e email re-engagement* playbook (V1, 7 May 2026). "
        "Each bucket has a defined framework, cadence, and rules. "
        "Accounts with explicit warnings (voice references, vendor lock-in nuances) are flagged inline."
    )

    emailable = contacts[contacts['has_email']].copy()

    # ── Top-line counts by bucket ─────────────────────────────────────────────
    bucketed = emailable[emailable['playbook_bucket'].notna()]
    no_touch_df = emailable[emailable['playbook_no_touch'].notna()]
    in_buckets_df = emailable[
        emailable['playbook_bucket'].notna()
        & emailable['playbook_no_touch'].isna()
    ]
    unbucketed = emailable[
        emailable['playbook_bucket'].isna()
        & emailable['playbook_no_touch'].isna()
    ]

    kc1, kc2, kc3, kc4 = st.columns(4)
    with kc1:
        st.metric("In playbook buckets", in_buckets_df['company'].nunique(),
                  help="Unique companies with at least one playbook bucket. "
                       "Many appear in multiple buckets (e.g. Polycab is both "
                       "Timing-Paused AND Strategic).")
    with kc2: st.metric("🚫 No Touch", no_touch_df['company'].nunique())
    with kc3: st.metric("Unbucketed", unbucketed['company'].nunique())
    with kc4: st.metric("Total emailable", emailable['company'].nunique())

    st.markdown("---")

    # ── No Touch list (warning, top of page) ──────────────────────────────────
    if not no_touch_df.empty:
        with st.expander(
            f"🚫 **No Touch list** — {no_touch_df['company'].nunique()} accounts that must NOT receive outreach",
            expanded=False,
        ):
            for category, info in NO_TOUCH.items():
                cat_companies = []
                for acc_name in info["accounts"]:
                    matches = no_touch_df[
                        no_touch_df['company'].str.lower().str.contains(
                            acc_name.lower(), na=False, regex=False
                        )
                    ]
                    if not matches.empty:
                        cat_companies.append((acc_name, info["accounts"][acc_name], matches))
                if not cat_companies:
                    continue
                st.markdown(f"**{info['icon']} {category}** — _{info['desc']}_")
                for acc_name, reason, matches in cat_companies:
                    n = matches['company'].nunique()
                    st.markdown(f"- **{acc_name}** ({n} contact{'s' if n != 1 else ''}) — {reason}")
                st.markdown("")

    # ── Playbook buckets (the main event) ─────────────────────────────────────
    st.markdown("#### 📬 Playbook Buckets")
    st.caption("Each bucket has a designated email framework. Click to expand contacts + see rules.")

    for bucket_name, info in PLAYBOOK_BUCKETS.items():
        # Multi-bucket: account appears in every bucket it matches
        bucket_grp = emailable[
            emailable['playbook_buckets_all'].apply(
                lambda bs: bucket_name in (bs or [])
            )
            & emailable['playbook_no_touch'].isna()
        ]
        n_companies = bucket_grp['company'].nunique()
        n_contacts = len(bucket_grp)

        # Companies from playbook list that we did NOT find in the data
        found_companies = {_normalize_company(c) for c in bucket_grp['company'].unique()}
        missing = []
        for acc in info["accounts"]:
            an = _normalize_company(acc)
            if not any(an in fc or fc in an for fc in found_companies):
                missing.append(acc)

        header = f"{info['icon']} **{bucket_name}** — {n_companies} companies, {n_contacts} contacts  ·  Framework: {info['framework']}"
        with st.expander(header, expanded=False):
            st.markdown(f"_{info['desc']}_")
            st.markdown(f"**📨 Cadence:** {info['cadence']}")
            st.markdown("**📋 Rules:**")
            for rule in info["rules"]:
                st.markdown(f"- {rule}")

            if not bucket_grp.empty:
                st.markdown("**Contacts:**")
                # Show "Also in" column when account is in multiple buckets
                preview = bucket_grp[['company', 'person_name', 'email', 'designation',
                                      'lead_status', 'last_contact',
                                      'playbook_buckets_all', 'playbook_note']].copy()
                preview['last_contact'] = preview['last_contact'].apply(
                    lambda x: x.strftime('%d %b %Y') if pd.notna(x) else '—')
                preview['Also in'] = preview['playbook_buckets_all'].apply(
                    lambda bs: ', '.join(b for b in (bs or []) if b != bucket_name) or '—'
                )
                preview = preview.drop(columns=['playbook_buckets_all'])
                preview = preview.sort_values(['company', 'last_contact'], ascending=[True, False])
                preview['playbook_note'] = preview['playbook_note'].fillna('')
                st.dataframe(preview.rename(columns={
                    'company': 'Company', 'person_name': 'Name', 'email': 'Email',
                    'designation': 'Title', 'lead_status': 'Status',
                    'last_contact': 'Last Contact', 'playbook_note': '⚠️ Note',
                }), use_container_width=True, hide_index=True, height=min(320, 40 + 35 * len(preview)))

            if missing:
                st.warning(
                    f"📋 Listed in playbook but NOT found in CRM data ({len(missing)}): "
                    f"{', '.join(missing)}. "
                    f"Either add them to the All-e Active/Dropped sheet, or update the spelling in the playbook."
                )

    st.markdown("---")

    # ── Unbucketed accounts (recency view as fallback) ────────────────────────
    with st.expander(
        f"📂 **Unbucketed accounts** — {unbucketed['company'].nunique()} companies not in playbook (recency view)",
        expanded=False,
    ):
        st.caption("These accounts are not classified in the playbook yet. Showing recency for context.")
        recency_order = ['🔥 Hot (<30d)', '☀️ Warm (30-90d)', '❄️ Cool (90-180d)', '🧊 Cold (180+d)', '⚫ No date']
        matrix = unbucketed.groupby(['recency', 'segment'])['company'].nunique().unstack(fill_value=0)
        matrix = matrix.reindex(recency_order, fill_value=0)
        if 'Active' not in matrix.columns: matrix['Active'] = 0
        if 'Dropped' not in matrix.columns: matrix['Dropped'] = 0
        matrix['Total'] = matrix['Active'] + matrix['Dropped']
        matrix = matrix.reset_index().rename(columns={'recency': 'Recency'})
        st.dataframe(matrix, use_container_width=True, hide_index=True)

        un_preview = unbucketed[['company', 'person_name', 'email', 'segment', 'lead_status',
                                 'recency', 'last_contact']].copy()
        un_preview['last_contact'] = un_preview['last_contact'].apply(
            lambda x: x.strftime('%d %b %Y') if pd.notna(x) else '—')
        un_preview = un_preview.sort_values(['recency', 'company'])
        st.dataframe(un_preview.rename(columns={
            'company': 'Company', 'person_name': 'Name', 'email': 'Email',
            'segment': 'Segment', 'lead_status': 'Status',
            'recency': 'Recency', 'last_contact': 'Last Contact',
        }), use_container_width=True, hide_index=True, height=400)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: EMAIL COMPOSER
# ══════════════════════════════════════════════════════════════════════════════

# 5 frameworks from Amruta's playbook (Building Agentic Frameworks).
# Each maps 1:1 to a playbook bucket; the composer auto-suggests the right
# framework based on which bucket the selected contact's company is in.
EMAIL_TEMPLATES = {
    "A — Market Signal (Timing-Paused)": {
        "subject": "Why ordering adoption stays stuck at 12% — and what changes it",
        "body": """Hi {name},

One pattern worth sharing as {company} heads into FY26 planning.

Brands with large retailer networks are finding a consistent gap: retailer apps and DMS tools sit at ~12% adoption even after years of investment. The ordering behavior doesn't change because the submission path is harder than a WhatsApp message to the FA.

The brands that moved retailer ordering to WhatsApp — without replacing their existing stack — are seeing two things happen:
1. Adoption crosses 25–30% within two quarters because retailers are already on WhatsApp all day.
2. Scheme communication, which was always supposed to drive volume, finally reaches the retailer in time to act on it.

The second outcome is the one most brands didn't plan for. The scheme and trade promotion layer becomes useful only when the ordering layer is actually being used.

Given the scale of {company}'s retailer network, this seemed worth flagging as FY26 priorities are being set.

Happy to share a brief note on how a peer in {vertical} structured this.

Best,
{sender}

P.S. — Schneider Electric, B2B retailer ordering (FMEG): https://www.youtube.com/watch?v=jDJfMnR3OYE""",
    },
    "B — Outcome Reference (Evaluation Stalled)": {
        "subject": "Outcome from a {vertical} brand's distributor ordering deployment",
        "body": """Hi {name},

One brief reference that might be relevant to your internal discussion.

A {vertical} brand we work with — distributor network of comparable scale — deployed WhatsApp-based ordering last quarter. The primary metric they tracked was not adoption rate (though that hit 28%+ within 8 weeks). It was ERP data completeness — the share of orders flowing directly into their system without manual re-entry.

That went from around 18% to over 45% within three months. The secondary benefit was reliable secondary sales data finally flowing in, which unlocked scheme tracking they'd been trying to operationalise for two years.

Given the size of {company}'s distribution network, the same dynamics likely apply.

Happy to walk through how the deployment was structured if the internal conversation is moving forward.

Best,
{sender}

P.S. — References:
• Schneider Electric — B2B retailer ordering (FMEG): https://www.youtube.com/watch?v=jDJfMnR3OYE
• Distributor Agent — B2B distributor ordering: https://youtu.be/c0mnXe-MZeY""",
    },
    "C — Adoption Gap (Competitor-Adjacent)": {
        "subject": "Why the DMS you have and the data you get are two different things",
        "body": """Hi {name},

One observation from brands in {vertical} that have been through the same evaluation.

Most brands with SAP, DMS, and SFA in place find that distributor and retailer adoption of those systems sits at 5–12% in traditional trade. The tools are there. The data isn't. The reason is consistent: any solution that requires a separate login or a new app competes with WhatsApp for the distributor's attention — and loses.

The brands that closed this gap didn't replace their DMS. They added a WhatsApp ordering layer on top of it.

The agent handles the conversation — order placement, scheme queries, stock checks — and the DMS gets the structured data it was always supposed to have. Adoption follows because distributors and retailers are already on WhatsApp all day.

The investment question then shifts: not whether to digitize, but whether the WA layer pays for itself in data quality and order volume. For a network the size of {company}'s, the math tends to work differently than for a smaller deployment.

Happy to share how one {vertical} brand with a similar stack structured this.

Best,
{sender}""",
    },
    "D — Founder-Tone Strategic Note (Strategic Slow Movers)": {
        "subject": "One observation on AI in {vertical} distribution",
        "body": """Hi {name},

One observation worth sharing as you plan FY26 priorities.

The brands generating the most durable traction with AI in distribution are not the ones that started with the most ambitious deployments. They started with the narrowest, highest-friction workflow — typically order placement or invoice capture — and built outward.

The reason it works: a narrow deployment generates the behavioral data that makes the broader system intelligent. The brands that skipped this step found themselves with a capable system and no signal to act on.

At the scale of {company}'s network, the sequencing question matters significantly.

Happy to share how a couple of brands in {vertical} have approached this if the conversation is useful.

Best,
{sender}""",
    },
    "E1 — Specific Trigger / Distributor Ordering (Ghost)": {
        "subject": "Why DMS sits at 15% in traditional trade and what the WhatsApp layer does differently",
        "body": """Hi {name},

One observation that may be worth {company}'s attention as you plan for FY26.

In the last two quarters, a set of {vertical} brands have moved primary distributor ordering to WhatsApp as the main channel. The reason is straightforward: distributors already operate on WhatsApp, and any solution that requires a separate login sees single-digit adoption regardless of how well it is designed.

The brands that made this work connected the agent directly to their ERP / DMS systems so it knows real-time pricing, credit limits, and stock levels at the moment an order is placed. That is where a WhatsApp ordering interface becomes the data layer.

Beyond ordering, the same agent handles delivery status updates, financial document retrieval, scheme nudges for utilisation and target achievement, restocking reminders, and ready-to-use personalised order lists based on past purchase history. And it is not just for distributors — the same setup extends to retailers as well.

We have live deployments across agrochem (Agricon & PI Industries for distributor ordering) and electricals (Schneider Electric for contractor ordering). The setup and go-live runs 6–8 weeks.

We had spoken some months ago about this for {company}. If the timing is better now, I am happy to walk through how a comparable brand in {vertical} set this up.

Best,
{sender}

P.S. — Here is a short video of PI Industries using this for distributor ordering: https://drive.google.com/file/d/14eyziI1N1Yt0AFKfVho4WM5WmbzwumMW/view""",
    },
    "E2 — Specific Trigger / D2C Discovery (Ghost)": {
        "subject": "Why product discovery fails on D2C sites and what the knowledge layer fixes",
        "body": """Hi {name},

A brief observation that may be relevant to where {company}'s D2C roadmap sits right now.

In the last quarter, a few {vertical} brands have moved away from rule-based chat widgets toward agents that genuinely understand the product catalog — the kind that answers not just "which model should I buy" but "how does this compare to what I already own and what I specifically need." The gap between those two is the gap between a chatbot and an agent.

What makes the difference is not the model. It is the knowledge layer underneath — a Brand Knowledge Graph built on your enriched catalog and customer purchase history. When a shopper asks a complex query, the agent maps intent to the right product, accounts for brand affinity, past purchases, and price preference, and surfaces a matched recommendation with explained trade-offs. No disambiguation loop, no wrong SKU, no generic answer.

The same layer also handles basket growth — cross-sell suggestions driven by purchase signals from your own transaction history, not generic recommendations — and lifecycle nudges for restocking and repurchase.

Two ways to deploy this: use our chat SDK and go live end-to-end, or plug our API and knowledge graph into your own agent interface. Available on cloud or on-premise.

We are doing this for Puma and Canon. If this is back on the table at {company}, happy to show you exactly how the knowledge graph is built for your catalog.

Best,
{sender}

P.S. — Here is Puma's agent in action: https://drive.google.com/file/d/119yh5D5m-0Z3opQEQtK_j-JiaVGcKcgH/view""",
    },
    "F — Voice Warm-Up (Voice-Waiting)": {
        "subject": "One thing we observed from WA ordering deployments in {vertical} — relevant to what you mentioned",
        "body": """Hi {name},

Sharing one observation while we work on something we think will be directly relevant to the direction you mentioned.

Across {vertical} brands, the ordering problem consistently splits into two parts: the conversation layer (getting the dealer to place an order at all) and the intelligence layer (knowing which SKU, which scheme, which depot, what credit limit applies).

Voice handles the first part reasonably well. Where it consistently falls short is the second — when a dealer asks a specific product or scheme question, the agent either escalates or gives a generic answer, because it doesn't have the product and channel context to respond accurately.

The brands that have gotten real traction built the intelligence layer first — so whatever interaction surface they use, the answers are right.

We're working on something we hope to share a first look at in June that we think will be relevant to what you mentioned. Will be in touch then.

Best,
{sender}""",
    },
    "Custom": {
        "subject": "",
        "body": "",
    },
}

# Bucket → framework auto-mapping (from Amruta's playbook).
# Ghost Accounts split: E1 (distributor ordering) is the default since most
# ghost accounts in the tracker are B2B distribution; pick E2 manually for
# D2C/discovery-driven accounts (Wakefit, Samsung, KLF Nirmal, etc.).
BUCKET_TO_FRAMEWORK = {
    "Timing-Paused":            "A — Market Signal (Timing-Paused)",
    "Evaluation Stalled":       "B — Outcome Reference (Evaluation Stalled)",
    "Competitor-Adjacent":      "C — Adoption Gap (Competitor-Adjacent)",
    "Strategic Slow Movers":    "D — Founder-Tone Strategic Note (Strategic Slow Movers)",
    "Ghost Accounts":           "E1 — Specific Trigger / Distributor Ordering (Ghost)",
    "Voice-Waiting":            "F — Voice Warm-Up (Voice-Waiting)",
}

with tab_compose:
    # ── Auto-reset body/subject when template OR recipient changes ────────────
    # Without this, a personal line like "Hope the golf is going well" stays in
    # the body when you switch to a different recipient — and gets sent to the
    # wrong person. We detect changes by comparing the previous-render values
    # cached in session state to the current ones.
    _prev_template = st.session_state.get("_last_template_name")
    _prev_recipient = st.session_state.get("_last_recipient_label")
    _curr_template = st.session_state.get("template_sel")
    _curr_recipient = st.session_state.get("send_recipient")

    if _curr_template and _curr_template in EMAIL_TEMPLATES:
        _tmpl = EMAIL_TEMPLATES[_curr_template]
        # Reset only if something *changed* — first render leaves both alone
        if (_prev_template is not None and _prev_template != _curr_template) or \
           (_prev_recipient is not None and _prev_recipient != _curr_recipient):
            st.session_state["email_body"] = _tmpl["body"]
            st.session_state["email_subject"] = _tmpl["subject"]

    st.session_state["_last_template_name"] = _curr_template
    st.session_state["_last_recipient_label"] = _curr_recipient

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

    # Suggest a framework based on the dominant playbook bucket in the filtered set
    # (real per-recipient suggestion happens in step 4 next to the recipient dropdown)
    suggested_template = None
    if not recipients.empty and "playbook_bucket" in recipients.columns:
        bucket_counts = recipients["playbook_bucket"].value_counts()
        bucket_counts = bucket_counts[bucket_counts.index.isin(BUCKET_TO_FRAMEWORK.keys())]
        if not bucket_counts.empty:
            top_bucket = bucket_counts.index[0]
            suggested_template = BUCKET_TO_FRAMEWORK.get(top_bucket)
            if suggested_template:
                st.info(f"💡 Most contacts here are in **{top_bucket}** → suggested framework: **{suggested_template}**")

    # Names are guessed from the email prefix (e.g. dsp@voltas.com -> "Dsp"),
    # so let the user correct them. Overrides are keyed by email and persist
    # across filter/template changes, and feed both the preview and sends.
    if "crm_name_overrides" not in st.session_state:
        st.session_state["crm_name_overrides"] = {}
    overrides = st.session_state["crm_name_overrides"]
    if not recipients.empty:
        recipients['person_name'] = recipients.apply(
            lambda r: overrides.get(r['email'], r['person_name']), axis=1)

    with st.expander(f"View / edit {len(recipients)} recipients", expanded=False):
        if not recipients.empty:
            st.caption(
                "✏️ Edit the **Name** column to fix how each contact is greeted in `{name}`. "
                "Names are guessed from the email address and usually need correcting — "
                "edits stick as you change filters or templates and apply to sends."
            )
            editor_df = recipients[['company', 'person_name', 'email', 'designation', 'last_contact']].copy()
            editor_df = editor_df.reset_index(drop=True)
            editor_df['last_contact'] = editor_df['last_contact'].apply(
                lambda x: x.strftime('%d %b %Y') if pd.notna(x) else '—')
            editor_df = editor_df.rename(columns={
                'company': 'Company', 'person_name': 'Name', 'email': 'Email',
                'designation': 'Title', 'last_contact': 'Last Contact',
            })
            ed_key = f"recipient_editor_{hash(tuple(sorted(recipients['email'])))}"
            edited = st.data_editor(
                editor_df, use_container_width=True, hide_index=True, height=300, key=ed_key,
                column_config={
                    'Name': st.column_config.TextColumn(
                        'Name ✏️', help="How this contact is greeted in the email — editable"),
                },
                disabled=['Company', 'Email', 'Title', 'Last Contact'],
            )
            for _, erow in edited.iterrows():
                nm = str(erow['Name'] or '').strip()
                if nm:
                    overrides[erow['Email']] = nm
            recipients['person_name'] = recipients.apply(
                lambda r: overrides.get(r['email'], r['person_name']), axis=1)

    st.markdown("---")

    # ── Step 2: Choose template ───────────────────────────────────────────────
    st.markdown("#### 2. Choose Template & Compose")

    tc1, tc2 = st.columns([1, 2])
    with tc1:
        template_name = st.radio("Template", list(EMAIL_TEMPLATES.keys()), key="template_sel")

    template = EMAIL_TEMPLATES[template_name]

    with tc2:
        from services.email_sender import SENDERS as _SENDERS
        sender_label = st.selectbox(
            "Send as",
            list(_SENDERS.keys()),
            help="Visible 'From' is always Graas Insights <insights@graas.ai>. "
                 "Replies route to the selected person's inbox via Reply-To.",
            key="sender_label",
        )
        sender_display_name, sender_reply_to = _SENDERS[sender_label]
        sender_name = sender_display_name.split()[0]  # for {sender} substitution
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
            # Render template — {name} = first name, {full_name} = full name
            _pv_full = str(pc.get('person_name', '')).strip()
            _pv_first = _pv_full.split()[0] if _pv_full else _pv_full

            rendered_subject = subject.format(
                company=pc['company'], name=_pv_first, full_name=_pv_full,
                vertical=pc['vertical'], sender=sender_name,
            ) if '{' in subject else subject

            rendered_body = body
            for key, val in {
                '{company}':    pc['company'],
                '{name}':       _pv_first,
                '{full_name}':  _pv_full,
                '{vertical}':   pc['vertical'],
                '{sender}':     sender_name,
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

    # ── Step 4: Send ──────────────────────────────────────────────────────────
    st.markdown("#### 4. Send")

    from services.email_sender import (
        send_email,
        preflight_check,
        remaining_cap,
        get_weekly_cap,
        get_sends_this_week,
        recent_sends,
        last_sent_to,
        get_dedup_days,
        recent_sent_emails,
        suppressed_emails,
    )

    pre_err = preflight_check()
    if pre_err:
        st.error(
            f"⚠️ Email sending is not configured: **{pre_err}**\n\n"
            "Add the missing keys to `.env`:\n"
            "- `SMTP_USER=insights@graas.ai`\n"
            "- `SMTP_PASS=<16-char Gmail App Password>`\n"
            "- `EMAIL_LOG_SHEET_ID=<sheet id of 'Graas Outreach Log'>`\n"
            "- `WEEKLY_SEND_CAP=50` (optional)\n\n"
            "Sheet must be shared with the service account (Editor permission)."
        )
    else:
        # Show the result of the previous send attempt (if any)
        last_result = st.session_state.get("last_send_result")
        if last_result:
            result_kind, result_to, result_msg = last_result
            if result_kind == "ok":
                st.success(f"✅ Sent to **{result_to}** — see Analytics tab for the log row.")
            else:
                st.error(f"❌ Send failed for **{result_to}**: {result_msg}")
            if st.button("Dismiss", key="dismiss_send_result"):
                del st.session_state["last_send_result"]
                st.rerun()

        # Cap status
        used = get_sends_this_week()
        cap = get_weekly_cap()
        left = max(0, cap - used)
        bar_color = "🟢" if left > 10 else ("🟡" if left > 0 else "🔴")
        cap_cols = st.columns([2, 1])
        with cap_cols[0]:
            st.markdown(f"{bar_color} **Weekly send cap:** {used}/{cap} used · **{left} remaining**")
            st.progress(min(used / cap, 1.0) if cap > 0 else 0)
        with cap_cols[1]:
            st.caption("Cap counts all successful sends in the trailing 7 days, across all senders.")

        # Single-recipient send (preview row drives this)
        st.markdown("##### Send the previewed email")

        if not recipients.empty:
            # Build recipient list for the dropdown — one row per (company, contact)
            contact_options = []
            for _, row in recipients.iterrows():
                if row.get("email") and "@" in str(row["email"]):
                    label = f"{row['person_name']} <{row['email']}> · {row['company']}"
                    contact_options.append((label, row.to_dict()))

            if not contact_options:
                st.warning("No valid recipient emails in the current segment.")
            else:
                # Default to first contact of preview_co if available
                default_idx = 0
                default_label_for_preview = None
                for i, (lbl, r) in enumerate(contact_options):
                    if r["company"] == preview_co:
                        default_idx = i
                        default_label_for_preview = lbl
                        break

                # Force the recipient dropdown to follow the previewed company.
                # Streamlit's selectbox ignores `index=` once it has a session-state
                # value for `key`, so without this the dropdown gets stuck on whatever
                # company was last selected — even if "Preview for" was changed.
                # That divergence caused a previewed-for-Samsung email to be sent
                # with HUL substituted, because send_target came from the stale row.
                _last_pc_key = "_send_recipient_last_preview_co"
                if (default_label_for_preview is not None
                        and st.session_state.get(_last_pc_key) != preview_co):
                    st.session_state["send_recipient"] = default_label_for_preview
                    st.session_state[_last_pc_key] = preview_co

                # Test-mode toggle goes FIRST so we can disable the recipient
                # dropdown when test mode is on (cleaner UX: you're picking
                # ONE thing — real send target OR test address, not both).
                test_mode = st.checkbox(
                    "🧪 Send to test address instead (override recipient email)",
                    key="send_test_mode",
                    help="When on: the real-recipient dropdown is locked, and the "
                         "email is sent to the chosen test address. Personalization "
                         "(Hi {name}, ... at {company}) still uses the recipient "
                         "previewed above, so the test email matches what the real "
                         "recipient would have received."
                )

                send_label = st.selectbox(
                    "Recipient",
                    [c[0] for c in contact_options],
                    index=default_idx,
                    key="send_recipient",
                    disabled=test_mode,
                    help="Locked in test mode — uncheck the test box above to send to a real recipient."
                         if test_mode else None,
                )
                send_target = dict(contact_options[[c[0] for c in contact_options].index(send_label)][1])

                # Defensive guard: if the chosen recipient's company doesn't match
                # the previewed company, refuse to send. Prevents the preview/send
                # divergence from ever shipping a wrong-company email.
                preview_send_mismatch = (send_target["company"] != preview_co)
                if preview_send_mismatch:
                    st.error(
                        f"⚠️ **Recipient mismatch:** preview shows **{preview_co}** "
                        f"but the selected recipient is at **{send_target['company']}**. "
                        f"Pick a {preview_co} contact, or change 'Preview for' to "
                        f"{send_target['company']} so the substituted body matches who you're sending to."
                    )

                # Show the playbook bucket(s) for this contact + suggest the right framework
                target_buckets = send_target.get("playbook_buckets_all") or []
                if not isinstance(target_buckets, list):
                    target_buckets = []
                target_no_touch = send_target.get("playbook_no_touch")
                target_note = send_target.get("playbook_note", "")

                if target_buckets:
                    suggested_for_recipient = BUCKET_TO_FRAMEWORK.get(target_buckets[0])
                    bucket_str = " · ".join(target_buckets)
                    if suggested_for_recipient and suggested_for_recipient != template_name:
                        st.info(
                            f"📋 **{send_target['company']}** is in playbook bucket(s): **{bucket_str}** → "
                            f"suggested framework: **{suggested_for_recipient}** "
                            f"(currently using {template_name})"
                        )
                    else:
                        st.caption(f"📋 Playbook bucket(s): **{bucket_str}**")

                # NaN is truthy in Python, so a plain `if target_note:` would
                # render the string "nan" for accounts without a playbook note.
                if isinstance(target_note, str) and target_note.strip() and target_note.strip().lower() != "nan":
                    st.warning(target_note)

                test_email = ""
                if test_mode:
                    # Known internal testers — extend this list as needed.
                    TEST_RECIPIENTS = {
                        "Prem (prem@graas.ai)":                     "prem@graas.ai",
                        "Dhanashree (dhanashree.mohite@graas.ai)":  "dhanashree.mohite@graas.ai",
                        "Amruta (amruta@graas.ai)":                 "amruta@graas.ai",
                        "Gaurav (gaurav@graas.ai)":                 "gaurav@graas.ai",
                        "Insights (insights@graas.ai)":             "insights@graas.ai",
                        "Custom…":                                  "",
                    }
                    tcol1, tcol2 = st.columns([1, 1])
                    with tcol1:
                        test_choice = st.selectbox(
                            "Test recipient",
                            list(TEST_RECIPIENTS.keys()),
                            key="send_test_choice",
                        )
                    if test_choice == "Custom…":
                        with tcol2:
                            test_email = st.text_input(
                                "Custom email",
                                value="",
                                placeholder="someone@example.com",
                                key="send_test_email_custom",
                            ).strip()
                    else:
                        test_email = TEST_RECIPIENTS[test_choice]
                        with tcol2:
                            st.markdown(f"**→** `{test_email}`")

                # Render personalized subject + body for the chosen contact
                # (personalization always uses the dropdown contact, even in test mode)
                # {name} → first name only (matches how cold outreach is actually written)
                # {full_name} → full name, kept as a backup for templates that need it
                _full_name = str(send_target.get("person_name", "")).strip()
                _first_name = _full_name.split()[0] if _full_name else _full_name

                rendered_subject_send = subject.format(
                    company=send_target["company"], name=_first_name, full_name=_full_name,
                    vertical=send_target["vertical"], sender=sender_name,
                ) if "{" in subject else subject

                rendered_body_send = body
                for k, v in {
                    "{company}":    send_target["company"],
                    "{name}":       _first_name,
                    "{full_name}":  _full_name,
                    "{vertical}":   send_target["vertical"],
                    "{sender}":     sender_name,
                    "{designation}": send_target.get("designation", ""),
                }.items():
                    rendered_body_send = rendered_body_send.replace(k, str(v))

                # Resolve the actual To: address (test override or real recipient)
                effective_to_email = test_email if (test_mode and test_email) else send_target["email"]
                effective_to_name = "Test (Prem)" if (test_mode and test_email) else send_target["person_name"]

                # Two-step confirm to avoid misclicks
                confirm_key = "send_confirm_armed"
                if confirm_key not in st.session_state:
                    st.session_state[confirm_key] = False

                # No-Touch enforcement — block real sends to companies on Amruta's
                # No-Touch list. Test mode is allowed because it goes to internal
                # addresses, never to the real (no-touch) recipient.
                no_touch_block = False
                if target_no_touch and not test_mode:
                    no_touch_block = True
                    st.error(
                        f"🚫 **Cannot send to {send_target['company']}** — listed in playbook **No-Touch** "
                        f"({target_no_touch.get('category', '')}).\n\n"
                        f"**Reason:** _{target_no_touch.get('reason', '')}_\n\n"
                        f"Override only by switching to test mode (which sends to an internal address, "
                        f"never to {send_target['email']})."
                    )

                # Dedup check — warn if this recipient was emailed within DEDUP_DAYS.
                # Test mode bypasses (test addresses are hit repeatedly during testing).
                dedup_override = False
                dedup_days = get_dedup_days()
                if not test_mode:
                    _last_sent, _days_ago = last_sent_to(effective_to_email)
                    if _last_sent and _days_ago is not None and _days_ago < dedup_days:
                        st.warning(
                            f"⚠️ **{effective_to_email}** was last emailed **{_days_ago} day(s) ago** "
                            f"(dedup window = {dedup_days} days). Sending again is blocked unless you override."
                        )
                        dedup_override = st.checkbox(
                            f"Send anyway (override {dedup_days}-day dedup)",
                            key="dedup_override_box",
                            help="Use sparingly — repeat sends inside the dedup window often feel spammy."
                        )

                cols = st.columns([2, 1, 1])
                with cols[0]:
                    test_badge = " 🧪 **TEST MODE**" if (test_mode and test_email) else ""
                    st.markdown(
                        f"**Will send to:** `{effective_to_email}`{test_badge}  \n"
                        f"**From:** Graas Insights `<insights@graas.ai>`  \n"
                        f"**Reply-To:** {sender_display_name} `<{sender_reply_to}>`"
                    )
                with cols[1]:
                    # Disable Send if cap reached, or test-mode-without-email, or
                    # No-Touch-blocked, or recipient is in dedup window without override.
                    _last_sent_check, _days_check = last_sent_to(effective_to_email)
                    in_dedup_window = (not test_mode and _last_sent_check is not None
                                       and _days_check is not None and _days_check < dedup_days)
                    send_disabled = (
                        (left <= 0)
                        or (test_mode and not test_email)
                        or no_touch_block
                        or (in_dedup_window and not dedup_override)
                        or preview_send_mismatch
                    )
                    if not st.session_state[confirm_key]:
                        if st.button("📧 Send email", type="primary", disabled=send_disabled,
                                     use_container_width=True, key="send_arm"):
                            st.session_state[confirm_key] = True
                            st.rerun()
                    else:
                        if st.button("✅ Confirm send", type="primary",
                                     use_container_width=True, key="send_confirm"):
                            with st.spinner(f"📨 Sending to {effective_to_email}…"):
                                ok, msg = send_email(
                                    sender_label=sender_label,
                                    to_email=effective_to_email,
                                    to_name=effective_to_name,
                                    company=send_target["company"] + (" [TEST]" if test_mode else ""),
                                    subject=rendered_subject_send,
                                    body=rendered_body_send,
                                    bucket=str(send_target.get("playbook_bucket", "")) or str(send_target.get("recency", "")),
                                    template=template_name + (" (test)" if test_mode else ""),
                                    bypass_dedup=test_mode or dedup_override,
                                )
                            st.session_state[confirm_key] = False
                            # Stash result so we can show it after the rerun
                            st.session_state["last_send_result"] = ("ok" if ok else "err", effective_to_email, msg)
                            st.rerun()
                with cols[2]:
                    if st.session_state[confirm_key]:
                        if st.button("Cancel", use_container_width=True, key="send_cancel"):
                            st.session_state[confirm_key] = False
                            st.rerun()

                if left <= 0:
                    st.warning(f"Weekly cap of {cap} reached. New sends blocked until older sends roll out of the 7-day window.")

        # Bulk-copy fallback (kept for manual / Gmail-direct workflows)
        with st.expander("📋 Copy emails for manual sending (Gmail BCC, etc.)"):
            ac1, ac2 = st.columns(2)
            with ac1:
                st.markdown("**All recipient emails**")
                all_emails = ', '.join(recipients['email'].unique().tolist())
                st.code(all_emails, language=None)
            with ac2:
                st.markdown("**Emails by company**")
                for co in recipients['company'].unique()[:20]:
                    co_emails = recipients[recipients['company'] == co]['email'].tolist()
                    co_names = recipients[recipients['company'] == co]['person_name'].tolist()
                    st.markdown(f"**{co}** ({', '.join(co_names)})")
                    st.code(', '.join(co_emails), language=None)
                if len(recipients['company'].unique()) > 20:
                    st.caption(f"... and {len(recipients['company'].unique()) - 20} more companies")

        # ── Bulk send to filtered set ─────────────────────────────────────────
        st.markdown("---")
        st.markdown("##### 📨 Bulk send to all in current filter")
        st.caption(
            "Sends the **same template + body** to every recipient in the current Step 1 filter, "
            "with `{name}`, `{company}`, `{vertical}` substituted per-person. "
            "If you've added personal lines to the body (e.g. \"Hope golf is going well\"), reset to "
            "the framework template first — they'll go to everyone otherwise."
        )

        if recipients.empty or not contact_options:
            st.caption("No recipients in current filter. Adjust filters in Step 1 above.")
        else:
            # ── Pre-flight: build filter pipeline ─────────────────────────
            bulk_pool = recipients[recipients["email"].apply(lambda e: bool(e) and "@" in str(e))].copy()
            bulk_pool["_email_norm"] = bulk_pool["email"].str.lower().str.strip()

            # Stage 1: total
            stage_total = len(bulk_pool)

            # Stage 2: remove No-Touch companies
            def _is_no_touch(v):
                return isinstance(v, dict) and v.get("category")
            no_touch_mask = bulk_pool.get("playbook_no_touch", pd.Series([None]*len(bulk_pool))).apply(_is_no_touch)
            bulk_no_touch = bulk_pool[no_touch_mask]
            after_no_touch = bulk_pool[~no_touch_mask]
            stage_after_nt = len(after_no_touch)

            # Stage 3: remove suppressed
            with st.spinner("Loading suppression + recent-send data…"):
                supp_set = suppressed_emails()
                recent_set = recent_sent_emails(get_dedup_days())
            sup_mask = after_no_touch["_email_norm"].isin(supp_set)
            bulk_supp = after_no_touch[sup_mask]
            after_supp = after_no_touch[~sup_mask]
            stage_after_supp = len(after_supp)

            # Stage 4: remove recently-sent (dedup window)
            dedup_mask = after_supp["_email_norm"].isin(recent_set)
            bulk_dedup = after_supp[dedup_mask]
            after_dedup = after_supp[~dedup_mask]
            stage_final = len(after_dedup)

            # Show filter pipeline
            st.markdown(
                f"**Filter pipeline:**  \n"
                f"• {stage_total} contacts in current filter  \n"
                f"• −{stage_total - stage_after_nt} No-Touch companies → **{stage_after_nt}**  \n"
                f"• −{stage_after_nt - stage_after_supp} on suppression list → **{stage_after_supp}**  \n"
                f"• −{stage_after_supp - stage_final} sent within last {get_dedup_days()}d (dedup) → **{stage_final}**  \n"
                f"### → Will send to **{stage_final}** recipient(s)"
            )

            # Cap check
            bulk_blocked_reason = None
            if stage_final == 0:
                bulk_blocked_reason = "No recipients left after filters."
            elif stage_final > left:
                bulk_blocked_reason = (
                    f"{stage_final} sends would exceed the weekly cap "
                    f"({used} used, {left} remaining of {cap}). "
                    f"Reduce the filter or wait for cap to roll over."
                )

            # Drilldown of who's being filtered out (for transparency)
            if stage_total > stage_final:
                with st.expander(f"🔍 See who's being filtered out ({stage_total - stage_final} contacts)"):
                    if not bulk_no_touch.empty:
                        st.markdown(f"**🚫 No-Touch ({len(bulk_no_touch)}):**")
                        st.dataframe(
                            bulk_no_touch[["company", "person_name", "email"]].rename(
                                columns={"company": "Company", "person_name": "Name", "email": "Email"}),
                            use_container_width=True, hide_index=True, height=140)
                    if not bulk_supp.empty:
                        st.markdown(f"**🚷 Suppressed ({len(bulk_supp)}):**")
                        st.dataframe(
                            bulk_supp[["company", "person_name", "email"]].rename(
                                columns={"company": "Company", "person_name": "Name", "email": "Email"}),
                            use_container_width=True, hide_index=True, height=140)
                    if not bulk_dedup.empty:
                        st.markdown(f"**⏱️ Recently emailed ({len(bulk_dedup)}, within {get_dedup_days()}d):**")
                        st.dataframe(
                            bulk_dedup[["company", "person_name", "email"]].rename(
                                columns={"company": "Company", "person_name": "Name", "email": "Email"}),
                            use_container_width=True, hide_index=True, height=140)

            # Preview of who WILL be sent to
            if stage_final > 0:
                with st.expander(f"📋 Preview the {stage_final} recipient(s) who WILL be sent to"):
                    st.dataframe(
                        after_dedup[["company", "person_name", "email", "playbook_bucket"]].rename(
                            columns={"company": "Company", "person_name": "Name",
                                     "email": "Email", "playbook_bucket": "Bucket"}),
                        use_container_width=True, hide_index=True, height=300)

            # Bulk send button — two-step confirm
            bulk_confirm_key = "bulk_confirm_armed"
            if bulk_confirm_key not in st.session_state:
                st.session_state[bulk_confirm_key] = False

            if bulk_blocked_reason:
                st.error(f"⚠️ {bulk_blocked_reason}")

            bcols = st.columns([2, 1, 1])
            with bcols[0]:
                if not bulk_blocked_reason:
                    st.markdown(
                        f"**Will send {stage_final} email(s) via:** {sender_display_name} `<{sender_reply_to}>`  \n"
                        f"**Framework:** {template_name}  \n"
                        f"**Cap impact:** {used}/{cap} → **{used + stage_final}/{cap}**"
                    )
            with bcols[1]:
                if not st.session_state[bulk_confirm_key]:
                    if st.button(f"📨 Send to all {stage_final}",
                                 type="primary",
                                 disabled=bool(bulk_blocked_reason),
                                 use_container_width=True,
                                 key="bulk_arm"):
                        st.session_state[bulk_confirm_key] = True
                        st.rerun()
                else:
                    if st.button(f"✅ Confirm send to {stage_final}",
                                 type="primary",
                                 use_container_width=True,
                                 key="bulk_confirm"):
                        # Run the send loop
                        progress_bar = st.progress(0.0, text=f"Sending 0 of {stage_final}…")
                        sent_n, failed_n = 0, 0
                        failures = []
                        for i, (_, row) in enumerate(after_dedup.iterrows(), start=1):
                            r_full = str(row.get("person_name", "")).strip()
                            r_first = r_full.split()[0] if r_full else r_full
                            try:
                                r_subj = subject.format(
                                    company=row["company"], name=r_first, full_name=r_full,
                                    vertical=row["vertical"], sender=sender_name,
                                ) if "{" in subject else subject
                            except Exception as e:
                                failures.append((row["email"], f"Subject format error: {e}"))
                                failed_n += 1
                                progress_bar.progress(i / stage_final, text=f"Sending {i} of {stage_final}…")
                                continue

                            r_body = body
                            for k, v in {
                                "{company}":    row["company"],
                                "{name}":       r_first,
                                "{full_name}":  r_full,
                                "{vertical}":   row["vertical"],
                                "{sender}":     sender_name,
                                "{designation}": row.get("designation", ""),
                            }.items():
                                r_body = r_body.replace(k, str(v))

                            ok_b, msg_b = send_email(
                                sender_label=sender_label,
                                to_email=row["email"],
                                to_name=r_full,
                                company=row["company"],
                                subject=r_subj,
                                body=r_body,
                                bucket=str(row.get("playbook_bucket", "")) or str(row.get("recency", "")),
                                template=template_name,
                                bypass_dedup=False,  # already pre-filtered, but keep guard active
                            )
                            if ok_b:
                                sent_n += 1
                            else:
                                failed_n += 1
                                failures.append((row["email"], msg_b))
                            progress_bar.progress(i / stage_final, text=f"Sending {i} of {stage_final}…")

                        progress_bar.empty()
                        st.session_state[bulk_confirm_key] = False
                        # Stash result for persistent banner
                        st.session_state["last_bulk_result"] = (sent_n, failed_n, failures)
                        st.rerun()

            with bcols[2]:
                if st.session_state[bulk_confirm_key]:
                    if st.button("Cancel", use_container_width=True, key="bulk_cancel"):
                        st.session_state[bulk_confirm_key] = False
                        st.rerun()

            # Show last bulk result if any
            last_bulk = st.session_state.get("last_bulk_result")
            if last_bulk:
                bsent, bfail, bfailures = last_bulk
                if bfail == 0:
                    st.success(f"✅ Bulk send complete — **{bsent} sent**, 0 failed.")
                else:
                    st.warning(f"⚠️ Bulk send done — **{bsent} sent**, **{bfail} failed**.")
                    with st.expander(f"View {bfail} failure(s)"):
                        for em, why in bfailures:
                            st.markdown(f"- `{em}` — {why}")
                if st.button("Dismiss bulk result", key="dismiss_bulk_result"):
                    del st.session_state["last_bulk_result"]
                    st.rerun()

        st.caption("📊 Open the **Analytics** tab to see send history, volume by sender, and outreach metrics.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

with tab_analytics:
    st.markdown("### 📊 Outreach Analytics")
    st.caption("Email outreach metrics from the Graas Outreach Log. "
               "Sent is tracked today; opens / replies / unsubscribes need Phase 2 (hosted pixel + reply polling).")

    from services.email_sender import (
        recent_sends as _recent_sends,
        get_weekly_cap as _get_weekly_cap,
        get_sends_this_week as _get_sends_this_week,
        preflight_check as _preflight_check,
        fetch_suppressions as _fetch_suppressions,
        add_to_suppression as _add_to_suppression,
    )

    a_pre_err = _preflight_check()
    if a_pre_err:
        st.warning(f"⚠️ {a_pre_err} — analytics will be empty until email sending is configured (see **Email Composer** tab).")

    # Pull the full log once
    log_df = _recent_sends(limit=10000)

    if log_df.empty:
        st.info("No sends logged yet. Once you send your first email from the composer, metrics will populate here.")
    else:
        # Parse timestamp once
        log_df = log_df.copy()
        log_df["_ts"] = pd.to_datetime(log_df["timestamp_utc"], errors="coerce", utc=True)
        log_df = log_df[log_df["_ts"].notna()]

        now_utc = pd.Timestamp.now(tz="UTC")
        sent_df = log_df[log_df["status"] == "sent"]
        sent_7d = sent_df[sent_df["_ts"] >= now_utc - pd.Timedelta(days=7)]
        sent_30d = sent_df[sent_df["_ts"] >= now_utc - pd.Timedelta(days=30)]
        failed_7d = log_df[(log_df["status"] != "sent") & (log_df["_ts"] >= now_utc - pd.Timedelta(days=7))]

        # ── KPI tiles ─────────────────────────────────────────────────────────
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("📤 Sent (7d)", len(sent_7d), help=f"{len(sent_30d)} in last 30 days · {len(sent_df)} all-time")
        k2.metric("👀 Opened", "—", help="Phase 2: requires hosted tracking pixel")
        k3.metric("↩️ Replied", "—", help="Phase 2: requires Gmail API reply polling")
        k4.metric("🚫 Unsubscribed", "—", help="Phase 2: requires hosted unsubscribe endpoint")

        # Weekly cap row
        cap = _get_weekly_cap()
        used = _get_sends_this_week()
        st.markdown(f"**Weekly send cap:** {used} / {cap} used · {max(0, cap - used)} remaining")
        st.progress(min(used / cap, 1.0) if cap > 0 else 0)

        # Failure callout
        if not failed_7d.empty:
            st.error(f"⚠️ {len(failed_7d)} send failure(s) in the last 7 days — see Recent sends below for details.")

        st.markdown("---")

        # ── Volume over time + by sender ──────────────────────────────────────
        col_a, col_b = st.columns([3, 2])

        with col_a:
            st.markdown("#### Sends per day (last 30 days)")
            daily = (sent_30d.assign(_day=sent_30d["_ts"].dt.tz_convert(None).dt.date)
                            .groupby("_day").size().reset_index(name="Sends"))
            if daily.empty:
                st.caption("No sends in the last 30 days.")
            else:
                fig_daily = px.bar(daily, x="_day", y="Sends",
                                   color_discrete_sequence=["#4F46E5"])
                fig_daily.update_layout(template="plotly_dark", height=280,
                                        margin=dict(l=10, r=10, t=10, b=10),
                                        xaxis_title=None, yaxis_title="Sends")
                st.plotly_chart(fig_daily, use_container_width=True)

        with col_b:
            st.markdown("#### By sender (last 30d)")
            if "sender_label" in sent_30d.columns and not sent_30d.empty:
                by_sender = (sent_30d.groupby("sender_label").size()
                             .reset_index(name="Sends").sort_values("Sends", ascending=True))
                fig_s = px.bar(by_sender, x="Sends", y="sender_label", orientation="h",
                               color_discrete_sequence=["#7C3AED"])
                fig_s.update_layout(template="plotly_dark", height=280,
                                    margin=dict(l=10, r=10, t=10, b=10),
                                    xaxis_title=None, yaxis_title=None)
                st.plotly_chart(fig_s, use_container_width=True)
            else:
                st.caption("No sender data yet.")

        # ── By template + by bucket ───────────────────────────────────────────
        col_c, col_d = st.columns(2)
        with col_c:
            st.markdown("#### By template (last 30d)")
            if "template" in sent_30d.columns and not sent_30d.empty:
                by_t = (sent_30d.groupby("template").size().reset_index(name="Sends")
                        .sort_values("Sends", ascending=True))
                by_t = by_t[by_t["template"] != ""]
                if by_t.empty:
                    st.caption("No template data.")
                else:
                    fig_t = px.bar(by_t, x="Sends", y="template", orientation="h",
                                   color_discrete_sequence=["#10B981"])
                    fig_t.update_layout(template="plotly_dark", height=280,
                                        margin=dict(l=10, r=10, t=10, b=10),
                                        xaxis_title=None, yaxis_title=None)
                    st.plotly_chart(fig_t, use_container_width=True)
            else:
                st.caption("No template data yet.")

        with col_d:
            st.markdown("#### By bucket (last 30d)")
            if "bucket" in sent_30d.columns and not sent_30d.empty:
                by_b = (sent_30d.groupby("bucket").size().reset_index(name="Sends")
                        .sort_values("Sends", ascending=True))
                by_b = by_b[by_b["bucket"] != ""]
                if by_b.empty:
                    st.caption("No bucket data.")
                else:
                    fig_b = px.bar(by_b, x="Sends", y="bucket", orientation="h",
                                   color_discrete_sequence=["#F59E0B"])
                    fig_b.update_layout(template="plotly_dark", height=280,
                                        margin=dict(l=10, r=10, t=10, b=10),
                                        xaxis_title=None, yaxis_title=None)
                    st.plotly_chart(fig_b, use_container_width=True)
            else:
                st.caption("No bucket data yet.")

        st.markdown("---")

        # ── Recent sends table ────────────────────────────────────────────────
        st.markdown("#### 📬 Recent sends")
        recent_view = log_df.sort_values("_ts", ascending=False).head(50).copy()
        recent_view["timestamp_utc"] = recent_view["_ts"].dt.strftime("%d %b %H:%M UTC")
        cols_to_show = [c for c in
            ["timestamp_utc", "sender_label", "to_email", "company", "template", "subject", "status", "error_msg"]
            if c in recent_view.columns]
        st.dataframe(recent_view[cols_to_show], use_container_width=True, hide_index=True, height=420)

    # ── Suppression list (always visible, even when no sends yet) ─────────────
    st.markdown("---")
    st.markdown("#### 🚫 Suppression list")
    st.caption(
        "Emails on this list are blocked from sending — used for people who've "
        "asked to be removed, bounced repeatedly, or shouldn't be contacted for "
        "any other reason. Stored in the **Suppressions** tab of the Outreach Log."
    )

    supp_df = _fetch_suppressions()

    add_cols = st.columns([3, 4, 2, 1])
    with add_cols[0]:
        new_supp_email = st.text_input("Email to suppress", placeholder="someone@example.com",
                                       key="supp_new_email").strip()
    with add_cols[1]:
        new_supp_reason = st.text_input("Reason", placeholder="e.g. asked to unsubscribe, bounced 3×",
                                        key="supp_new_reason").strip()
    with add_cols[2]:
        new_supp_by = st.text_input("Added by", value="Prem", key="supp_new_by").strip()
    with add_cols[3]:
        st.markdown("&nbsp;")  # vertical alignment
        if st.button("Add", type="primary", use_container_width=True, key="supp_add_btn"):
            if not new_supp_email or "@" not in new_supp_email:
                st.error("Enter a valid email.")
            else:
                with st.spinner("Adding to suppression list…"):
                    ok = _add_to_suppression(new_supp_email, new_supp_reason, new_supp_by)
                if ok:
                    st.success(f"✅ {new_supp_email} added to suppression list.")
                    st.rerun()
                else:
                    st.error("Failed to add — check sheet permissions.")

    if supp_df.empty:
        st.caption("No suppressed emails yet.")
    else:
        st.markdown(f"**{len(supp_df)} suppressed:**")
        st.dataframe(supp_df, use_container_width=True, hide_index=True, height=240)
        st.caption("To remove an email from suppression, edit the **Suppressions** tab "
                   "in the [Outreach Log sheet](https://docs.google.com/spreadsheets/d/"
                   "1Vcu7ZkAjGbzpKH2CUGoSuLUGIfwYBT-GlpNN0zMKJMY/edit) directly.")
