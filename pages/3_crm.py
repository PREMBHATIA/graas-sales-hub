"""CRM & Email Outreach — Unified contacts from All-e Active & Dropped leads."""

import os
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


# ── Per-segment email suggestions (item 5) ───────────────────────────────────
# Replaces the static "playbook Google Doc" link. Suggestions are LIVE-READ from
# Dhanashree's re-engagement audience sheet: each account carries an AI Maturity
# and an "Email Theme" (the recommended angle, by maturity × reason stalled). We
# reduce that to segment (AI Maturity) · account (Company) · suggestion (Email
# Theme). Single source of truth — she edits the sheet, the composer follows.
#
# The sheet MUST be shared with the app's service account
# (command-center@prefab-bruin-491807-n0.iam.gserviceaccount.com, Viewer is
# enough). Until it is, the read returns empty and the header falls back to the
# playbook Doc link — nothing breaks.
#
# Override sheet/tab via env if she moves it:
#   SEGMENT_SUGGESTIONS_SHEET_ID  (default = her audience sheet)
#   SEGMENT_SUGGESTIONS_GID       (the linked tab's gid; we header-validate and
#                                  fall back to scanning tabs if it doesn't fit)
SEGMENT_SUGGESTIONS_SHEET_ID = os.getenv(
    "SEGMENT_SUGGESTIONS_SHEET_ID", "11uhucHZ6099LysoifJRmeGCx5DQ57ZxEa94Q0HjpaPo")
SEGMENT_SUGGESTIONS_GID = os.getenv("SEGMENT_SUGGESTIONS_GID", "2125984853")
# The "Theme - 3 Months" content-plan tab (gid-first hint; header-validated,
# falls back to scanning tabs — survives renames/moves).
SEGMENT_THEME_PLAN_GID = os.getenv("SEGMENT_THEME_PLAN_GID", "1357660099")
# An Email Theme containing any of these = "don't send yet" (voice demo pending).
_VOICE_HOLD_MARKERS = ("voice", "hold until demo")

# AI-maturity segmentation (the 1-to-many campaign axis). Labels match the
# pipeline sheet's "AI Maturity" column + Dhanashree's audience sheet exactly.
# Blank → "Unclassified" (kept out of the campaign picker).
AI_SEGMENTS = ["AI Laggard", "AI Exploring", "AI Mature"]


# These two normalizers are defined UP HERE (not in the Data Loading section
# below) because the item-5 header block runs at module top and transitively
# needs them — a def lower in the file would NameError at page load.
def _normalize_ai_segment(v: str) -> str:
    """Map an AI-maturity label to a canonical segment — tolerant of casing and
    the 'exploring'/'explorer' variants. Blank / 'TBD' / unknown → Unclassified."""
    s = (v or "").strip().lower()
    if not s:
        return "Unclassified"
    if "laggard" in s:
        return "AI Laggard"
    if "explor" in s:
        return "AI Exploring"
    if "matur" in s:
        return "AI Mature"
    return "Unclassified"


def _normalize_company(name: str) -> str:
    """Lowercase, strip, collapse spaces — for fuzzy matching."""
    return " ".join((name or "").lower().split())


def _extract_suggestions(vals) -> pd.DataFrame:
    """Reduce a worksheet's raw values to segment/account/suggestion, but ONLY if
    it's the audience tab (header must carry both 'AI Maturity' and 'Email
    Theme'). Returns an empty frame otherwise, so tab auto-detection can skip it.
    """
    if not vals or len(vals) < 2:
        return pd.DataFrame()
    hdr = [str(h).strip().lower() for h in vals[0]]
    has = lambda needle: any(needle in h for h in hdr)
    if not (has("ai maturity") and has("email theme")):
        return pd.DataFrame()

    def col(needle):
        for i, h in enumerate(hdr):
            if needle in h:
                return i
        return None

    ci_seg, ci_acct, ci_theme = col("ai maturity"), col("company"), col("email theme")
    rows = []
    for r in vals[1:]:
        cell = lambda i: (str(r[i]).strip() if (i is not None and i < len(r)) else "")
        acct, theme = cell(ci_acct), cell(ci_theme)
        if not acct or not theme:
            continue
        rows.append({"segment": cell(ci_seg), "account": acct,
                     "subject": "", "suggestion": theme})
    return pd.DataFrame(rows)


def _open_suggestions_sheet():
    """gspread handle on Dhanashree's sheet, or None (not shared / no creds)."""
    from services.sheets_client import _get_client
    if not SEGMENT_SUGGESTIONS_SHEET_ID:
        return None
    try:
        client = _get_client()
        if client is None:
            return None
        return client.open_by_key(SEGMENT_SUGGESTIONS_SHEET_ID)
    except Exception:
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def _load_segment_suggestions() -> pd.DataFrame:
    """Live-read Dhanashree's audience sheet → segment/account/suggestion.

    Tries the linked gid first (cheap), then scans worksheets for the audience
    header. Dhanashree restructures this workbook freely (tabs renamed, added,
    repurposed — the original linked gid is now a copy deck), so NOTHING is
    keyed on tab name/position: a tab counts only if its header carries both
    'AI Maturity' and 'Email Theme'. Empty frame if the sheet isn't shared with
    the app's service account (graceful → header falls back to the Doc)."""
    ss = _open_suggestions_sheet()
    if ss is None:
        return pd.DataFrame()
    # 1) the linked gid, if its header fits
    try:
        if SEGMENT_SUGGESTIONS_GID:
            ws = ss.get_worksheet_by_id(int(SEGMENT_SUGGESTIONS_GID))
            df = _extract_suggestions(ws.get_all_values())
            if not df.empty:
                return df.reset_index(drop=True)
    except Exception:
        pass
    # 2) otherwise find the worksheet whose header carries AI Maturity + Email Theme
    try:
        for ws in ss.worksheets():
            df = _extract_suggestions(ws.get_all_values())
            if not df.empty:
                return df.reset_index(drop=True)
    except Exception:
        pass
    return pd.DataFrame()


# ── 3-month content plan ("Theme - 3 Months" tab) ────────────────────────────
# Dhanashree's nurture arc: TWO content buckets — "AI MATURE" (M1–M9) and
# "AI EXPLORERS + LAGGARDS" (E1–E9) — each email numbered with a theme, core
# question, new belief, and Graas POV. Located by content signature (a header
# row containing 'email theme' + 'core question'), never by tab name/gid, so
# she can rename/reorder tabs freely.
_PLAN_CODE_RE = re.compile(r"^[A-Za-z]{0,2}\d{1,2}$")


def _extract_theme_plan(vals) -> pd.DataFrame:
    """Parse the "Context arc - v2" tab: code/theme/question/audience rows.
    Signature = a header row carrying BOTH 'Email Theme' and 'Audience' (the
    retired "Theme - 3 Months" tab has no Audience column, so it can't match).
    Handles both section headers (main arc + the E/L show-don't-tell track)."""
    rows, cols = [], None
    for r in (vals or []):
        cells = [str(x).strip() for x in r]
        if not any(cells):
            continue
        low = [c.lower() for c in cells]
        first = cells[0] if cells else ""
        if any("email theme" in c for c in low) and any("audience" in c for c in low):
            def _find(needle):
                for i, c in enumerate(low):
                    if needle in c:
                        return i
                return None
            cols = {"theme": _find("email theme"), "question": _find("core question"),
                    "audience": _find("audience"), "target": _find("target"),
                    "status": _find("status")}
            continue
        if cols is not None and _PLAN_CODE_RE.match(first):
            cell = lambda i: (cells[i] if (i is not None and i < len(cells)) else "")
            theme = cell(cols["theme"])
            if theme:
                rows.append({"code": first, "theme": theme,
                             "question": cell(cols["question"]),
                             "audience": cell(cols["audience"]),
                             "target": cell(cols["target"]),
                             "status": cell(cols["status"])})
    return pd.DataFrame(rows)


@st.cache_data(ttl=1800, show_spinner=False)
def _load_theme_plan(_cache_v: int = 2) -> pd.DataFrame:
    """Live-read the Context arc plan. Empty frame when absent (graceful).
    _cache_v exists ONLY to bust st.cache_data when the parser changes —
    the cache hashes this function, not the helpers it calls. Bump it
    whenever _extract_theme_plan's output shape changes."""
    ss = _open_suggestions_sheet()
    if ss is None:
        return pd.DataFrame()
    try:
        if SEGMENT_THEME_PLAN_GID:
            ws = ss.get_worksheet_by_id(int(SEGMENT_THEME_PLAN_GID))
            df = _extract_theme_plan(ws.get_all_values())
            if not df.empty:
                return df.reset_index(drop=True)
    except Exception:
        pass
    try:
        for ws in ss.worksheets():
            df = _extract_theme_plan(ws.get_all_values())
            if not df.empty:
                return df.reset_index(drop=True)
    except Exception:
        pass
    return pd.DataFrame()


def _render_theme_plan(segment: str) -> bool:
    """Show the Context arc emails for this segment (Audience column match)."""
    df = _load_theme_plan()
    if df.empty or "audience" not in df.columns:
        return False
    seg = _normalize_ai_segment(segment)
    _needle = {"AI Laggard": "laggard", "AI Exploring": "explor", "AI Mature": "mature"}.get(seg, "")
    aud = df["audience"].astype(str).str.lower()
    sub = df[aud.str.contains("all") | (aud.str.contains(_needle) if _needle else False)]
    if sub.empty:
        return False
    st.markdown(f"**📅 Context arc — the {len(sub)} emails for {seg}** "
                "(from the 'Context arc - v2' tab)")
    for _, r in sub.iterrows():
        st.markdown(f"- **{r['code']} · {r['theme']}**")
        if str(r.get("question", "")).strip():
            st.caption(f"    ↳ {r['question']}")
    return True


def _is_voice_hold(suggestion: str) -> bool:
    s = str(suggestion or "").lower()
    return any(m in s for m in _VOICE_HOLD_MARKERS)


def _voice_hold_companies() -> set:
    """Normalized company names flagged 'Voice — Hold Until Demo' in the
    audience sheet — do-not-send until the voice demo ships. This is the ONLY
    remaining consumer of the audience-list themes (display was retired with
    the playbook). Empty set if the sheet isn't readable."""
    df = _load_segment_suggestions()
    if df.empty or "suggestion" not in df.columns:
        return set()
    held = df[df["suggestion"].apply(_is_voice_hold)]
    return {_normalize_company(c) for c in held["account"].astype(str) if str(c).strip()}


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

/* ── Guided-flow polish (composer) ─────────────────────────────────────────
   The composer's 3 radios (who / body-design / template) become Graas-blue
   segmented pills so the current pick + the next choice pull the eye. Only the
   composer uses st.radio, so this is effectively scoped to that tab. */
div[role="radiogroup"] { gap: 8px !important; row-gap: 8px !important; }
div[role="radiogroup"] > label {
    border: 1.5px solid #dfe3ec;
    border-radius: 10px;
    padding: 9px 15px;
    background: #ffffff;
    transition: border-color .15s ease, background .15s ease, box-shadow .15s ease;
}
div[role="radiogroup"] > label:hover {
    border-color: #2742FF;
    background: #f5f7ff;
}
div[role="radiogroup"] > label:has(input:checked) {
    border-color: #2742FF;
    background: linear-gradient(135deg, rgba(8,193,255,.10), rgba(39,66,255,.10));
    box-shadow: inset 0 0 0 1px #2742FF;
    font-weight: 600;
}

/* Numbered step badges — a cyan→blue gradient chip gives the page a clear
   1→2→3→4 rhythm so the eye tracks down to the next action. */
.step-h {
    display: flex; align-items: center; gap: 11px;
    font-size: 1.2rem; font-weight: 700; color: #0D0D11;
    margin: 6px 0 4px;
}
.step-h .step-num {
    display: inline-flex; align-items: center; justify-content: center;
    width: 30px; height: 30px; border-radius: 50%;
    background: linear-gradient(135deg, #08C1FF, #2742FF);
    color: #ffffff; font-size: 0.98rem; font-weight: 800;
    box-shadow: 0 2px 7px rgba(39,66,255,.38);
    flex: 0 0 30px;
}
.step-h .step-sub { font-size: .82rem; font-weight: 500; color: #8a92a1; }

/* Make the two top-level fork questions (who / body design) read louder than a
   default radio label so they register as decision points. */
div[data-testid="stRadio"] > label p { font-size: 1rem !important; font-weight: 600 !important; color: #0D0D11 !important; }
</style>
""", unsafe_allow_html=True)


def _step_header(num, title, sub=""):
    """Numbered gradient-badge step header — gives the composer a clear 1→2→3→4
    visual sequence so the eye lands on the next action."""
    sub_html = f" &nbsp;<span class='step-sub'>{sub}</span>" if sub else ""
    st.markdown(
        f"<div class='step-h'><span class='step-num'>{num}</span>"
        f"<span>{title}{sub_html}</span></div>",
        unsafe_allow_html=True,
    )


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
        elif 'ai segment' in cl or 'ai maturity' in cl or 'ai-segment' in cl:
            col_map[col] = 'ai_segment'
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
            'ai_segment': _normalize_ai_segment(_safe(row, 'ai_segment')),
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
            "ai_segment": _normalize_ai_segment(entry.get("ai_segment", "")),
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

# Schema sentry — runs on every render (not inside @st.cache_data) so missing-
# column banners stay visible until the source sheet is fixed.
from services.schema import validate_schema as _validate_schema
from services.sheets_client import fetch_sheet_tab as _fetch_tab
_alle_id = os.getenv("ALLE_SHEET_ID", "")
if _alle_id:
    _validate_schema(_fetch_tab(_alle_id, "Overall Pipeline for IN and SEA"),
                     "Overall Pipeline for IN and SEA", context="CRM contacts")

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

# Tab isolation: Streamlit runs EVERY tab body on each rerun, so an unhandled
# error in one tab aborts the whole script and blanks every *other* tab too
# (e.g. a crash in Email Composer or Newsworthy leaves Analytics blank — the
# error renders into the hidden crashing tab, so it looks like nothing happened).
# _tab_guard confines a failure to its own tab and shows it there. st.rerun() /
# st.stop() raise ScriptControlException — those must propagate so buttons work.
from contextlib import contextmanager as _contextmanager
try:
    from streamlit.runtime.scriptrunner import (
        StopException as _StopExc,
        RerunException as _RerunExc,
    )
    _CONTROL_EXC = (_StopExc, _RerunExc)
except Exception:  # pragma: no cover — import path varies across versions
    _CONTROL_EXC = ()


@_contextmanager
def _tab_guard(label):
    try:
        yield
    except Exception as e:
        # Let Streamlit's own control-flow exceptions through untouched.
        if (_CONTROL_EXC and isinstance(e, _CONTROL_EXC)) or type(e).__name__ in (
            "StopException", "RerunException", "ScriptControlException",
        ):
            raise
        st.error(
            f"⚠️ The **{label}** section hit an error and couldn't render. "
            "The other tabs still work — expand below for the traceback."
        )
        st.exception(e)


# Newsworthy tab removed 2026-08-22: its daily Claude+web_search fetch ran on
# EVERY page load (Streamlit executes all tab bodies) and could block the whole
# page for minutes on a cache miss. The Context arc + per-segment suggestions
# superseded its talking-points job. services/commerce_news.py still serves the
# Prospect Brief 'While you wait' card.
tab_contacts, tab_segments, tab_compose, tab_calendar, tab_analytics = st.tabs([
    "👥 Contacts",
    "🎯 Segments",
    "✉️ Email Composer",
    "📅 Calendar",
    "📊 Analytics",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: CONTACTS
# ══════════════════════════════════════════════════════════════════════════════

with tab_contacts, _tab_guard("Contacts"):

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

            # 📋 Prospect Brief link — surface the latest brief Doc for this
            # company if one exists in the SalesHub Drive folder. Lets
            # Dhanashree open verified research without leaving the page.
            from services.sheets_client import find_briefs_for_company as _find_briefs
            _saleshub_folder = os.getenv(
                "PROSPECT_BRIEF_DRIVE_FOLDER",
                "0ABwowt8s9tmzUk9PVA",  # SalesHub Shared Drive
            )

            @st.cache_data(ttl=300, show_spinner=False)
            def _briefs_for(co_name: str, folder: str):
                return _find_briefs(co_name, folder)

            _briefs = _briefs_for(first['company'], _saleshub_folder)
            if _briefs:
                _latest = _briefs[0]
                _older_suffix = ""
                if len(_briefs) > 1:
                    _older_suffix = (
                        f" &nbsp;<span style='color:#6B7280;font-size:0.8rem;'>"
                        f"(+{len(_briefs) - 1} older)</span>"
                    )
                st.markdown(
                    f"<div style='margin-top:10px;padding:8px 12px;"
                    f"background:#EEF6EE;border-left:3px solid #2E7D32;"
                    f"border-radius:4px;font-size:0.9rem;'>"
                    f"📋 <b>Prospect brief on file</b> &nbsp;·&nbsp; "
                    f"<a href='{_latest['url']}' target='_blank' "
                    f"style='color:#1B5E20;font-weight:600;'>"
                    f"Open in Drive →</a>{_older_suffix}"
                    f"</div>",
                    unsafe_allow_html=True,
                )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: SEGMENTS
# ══════════════════════════════════════════════════════════════════════════════

with tab_segments, _tab_guard("Segments"):
    st.markdown("### 🎯 AI Segments")
    st.caption(
        "Every company by AI maturity — the axis campaigns target. Move a company "
        "between segments below; the change writes straight to the pipeline sheet's "
        "AI Maturity column. (The old playbook re-engagement buckets were retired "
        "2026-08-26 — campaigns run on these three segments + the Context arc.)"
    )

    _sp = contacts.copy()
    _sp["ai_segment"] = _sp["ai_segment"].replace("", "Unclassified").fillna("Unclassified")
    _co_seg = (_sp.groupby("company", as_index=False)
                  .agg(Segment=("ai_segment", "first"),
                       Contacts=("has_email", "sum")))
    _co_seg["Contacts"] = _co_seg["Contacts"].astype(int)
    _seg_order_tab = ["AI Laggard", "AI Exploring", "AI Mature", "Unclassified"]

    # ── Near-duplicate company names → banner (split accounts double-email) ──
    _SUFFIXES = {"ltd", "limited", "pvt", "private", "india", "inc", "corp", "co"}

    def _dup_key(n):
        toks = [t for t in _normalize_company(n).replace(".", " ").split()
                if t not in _SUFFIXES]
        return " ".join(toks)

    _co_seg["_dk"] = _co_seg["company"].apply(_dup_key)
    _dups = _co_seg[(_co_seg["_dk"] != "") & _co_seg.duplicated("_dk", keep=False)]
    if not _dups.empty:
        _dl = []
        for _dk, _dg in _dups.groupby("_dk"):
            _dl.append(" ↔ ".join(f"**{r.company}** ({r.Segment})"
                                   for r in _dg.itertuples()))
        st.warning(
            "⚠️ **Possible duplicate companies** — the same account appears under "
            "more than one name (campaigns could double-email it). Reconcile the "
            "Lead name in the sheet/overlay:\n\n- " + "\n- ".join(_dl))

    _lcols = st.columns(4)
    for _lc, _sg in zip(_lcols, _seg_order_tab):
        _n_co = int((_co_seg["Segment"] == _sg).sum())
        _n_ct = int(_co_seg.loc[_co_seg["Segment"] == _sg, "Contacts"].sum())
        with _lc:
            st.markdown(
                f"<div style='text-align:center;padding:4px 0 10px;'>"
                f"<div style='font-size:0.95rem;font-weight:700;color:#6b7280;'>{_sg}</div>"
                f"<div style='font-size:2.2rem;font-weight:800;color:#0D0D11;line-height:1.15;'>{_n_co}</div>"
                f"<div style='font-size:0.78rem;color:#9aa1ad;'>{_n_ct} contact(s)</div>"
                f"</div>", unsafe_allow_html=True)
            _d = (_co_seg[_co_seg["Segment"] == _sg][["company", "Contacts"]]
                  .rename(columns={"company": "Company"}).sort_values("Company"))
            st.dataframe(_d, hide_index=True, use_container_width=True,
                         height=min(560, 80 + 35 * max(1, len(_d))))

    # ── Move a company between segments (writes the pipeline sheet) ──────────
    st.markdown("---")
    st.markdown("#### ↔️ Move a company")
    from services.sheets_client import _get_writer_client, _normalize_company_key_for_pipeline
    _mc1, _mc2, _mc3 = st.columns([2, 1, 1])
    with _mc1:
        _mv_co = st.selectbox("Company", sorted(_co_seg["company"]), key="seg_mv_co")
    _mv_cur = (_co_seg.loc[_co_seg["company"] == _mv_co, "Segment"].iloc[0]
               if _mv_co else "")
    with _mc2:
        _mv_to = st.selectbox("Move to", [x for x in _seg_order_tab if x != "Unclassified"],
                              key="seg_mv_to", help=f"Currently: {_mv_cur}")
    with _mc3:
        st.markdown("&nbsp;")
        if st.button("Move", type="primary", use_container_width=True, key="seg_mv_btn"):
            try:
                _wc = _get_writer_client()
                _pws = (_wc.open_by_key(os.getenv("ALLE_SHEET_ID", ""))
                           .worksheet("Overall Pipeline for IN and SEA"))
                _phdr = [str(h).strip().lower() for h in _pws.row_values(1)]
                _ai_col = next(i + 1 for i, h in enumerate(_phdr) if "ai maturity" in h)
                _leads = _pws.col_values(1)
                _tk = _normalize_company_key_for_pipeline(_mv_co)
                _nrows = 0
                for _ri, _nm in enumerate(_leads[1:], start=2):
                    if _normalize_company_key_for_pipeline(_nm) == _tk:
                        _pws.update_cell(_ri, _ai_col, _mv_to)
                        _nrows += 1
                if _nrows:
                    st.success(f"✅ **{_mv_co}**: {_mv_cur} → **{_mv_to}** "
                               f"({_nrows} row(s) updated). Hit 🔄 Refresh CRM Data to see it everywhere.")
                else:
                    st.error(f"'{_mv_co}' not found in the pipeline sheet — overlay-only "
                             "companies are edited via the Contacts tab overlay instead.")
            except StopIteration:
                st.error("No 'AI Maturity' column found in the pipeline sheet.")
            except Exception as _mv_err:
                st.error(f"Move failed: {_mv_err}")
    st.caption(f"Selected company is currently **{_mv_cur or '—'}**. Moving updates every "
               "pipeline row matching the company name.")

    # ── No Touch (safety list stays visible) ─────────────────────────────────
    _nt = contacts[contacts["playbook_no_touch"].notna()]
    with st.expander(f"🚫 No Touch — {_nt['company'].nunique()} account(s) blocked from all outreach"):
        for _ntc in sorted(_nt["company"].unique()):
            st.markdown(f"- {_ntc}")


# Templates: the playbook-era frameworks (A–F — Timing-Paused, Eval Stalled,
# Ghost, Voice-Waiting…) were retired 2026-08-26; campaigns now come from the
# Context arc calendar. Custom (blank canvas) is the only starter.
EMAIL_TEMPLATES = {
    "Custom": {"subject": "", "body": ""},
}


def _substitute(text: str, subs: dict) -> str:
    """Replace {key} placeholders case-insensitively.

    Handles {sender}, {Sender}, {SENDER}, {name}, {Name}, {NAME}, etc.
    uniformly. Unknown placeholders pass through unchanged (so typos like
    {senderr} stay visible instead of being silently dropped)."""
    if not text:
        return text
    keys_lower = {k.lower(): v for k, v in subs.items()}

    def _repl(match):
        key = match.group(1).lower()
        if key in keys_lower:
            return str(keys_lower[key])
        return match.group(0)  # unknown — leave as-is

    return re.sub(r"\{([a-zA-Z_]+)\}", _repl, text)


# ── Personalisation validation (item 4) ──────────────────────────────────────
# Tokens the composer substitutes per recipient. {sender} always resolves, so
# it's excluded — a "missing personalisation field" is one of these coming up
# blank for a recipient, which we must catch BEFORE a broken {Company} ships.
_RECIPIENT_TOKENS = {"name", "full_name", "company", "vertical", "designation"}


def _used_tokens(*texts) -> set:
    """Lowercased recipient-token names used across the given texts."""
    found = set()
    for t in texts:
        if not t:
            continue
        for m in re.finditer(r"\{([a-zA-Z_]+)\}", str(t)):
            k = m.group(1).lower()
            if k in _RECIPIENT_TOKENS:
                found.add(k)
    return found


def _row_subs(row, sender_first: str) -> dict:
    """Build the substitution dict for one recipient row (mirrors the send path)."""
    _full = str(row.get("person_name", "") or "").strip()
    return {
        "company":     row.get("company", "") or "",
        "name":        _full.split()[0] if _full else _full,
        "full_name":   _full,
        "vertical":    row.get("vertical", "") or "",
        "sender":      sender_first,
        "designation": row.get("designation", "") or "",
    }


def _missing_tokens(subs: dict, used: set) -> list:
    """Which of the used recipient-tokens resolve to blank/'nan' for this row."""
    out = []
    for k in used:
        v = str(subs.get(k, "") or "").strip()
        if not v or v.lower() == "nan":
            out.append(k)
    return sorted(out)


@st.cache_data(ttl=90, show_spinner=False)
def _cached_log_df():
    """The Sends log, one read per 90s — Analytics reuses this everywhere."""
    from services.email_sender import recent_sends
    return recent_sends(limit=10000)


@st.cache_data(ttl=90, show_spinner=False)
def _cached_tracking_df():
    """The open/click beacon log, one read per 90s."""
    from services.email_sender import fetch_tracking_events
    return fetch_tracking_events()


@st.cache_data(ttl=900, show_spinner=False)
def _cached_bounces(_v: int = 1):
    """Bounce reports from the insights@ inbox (15-min cache). Empty on any
    failure — IMAP needs SMTP_USER/SMTP_PASS with IMAP enabled."""
    try:
        from services.bounce_scanner import scan_bounces
        return scan_bounces()
    except Exception:
        return []


def _fetch_watchers_page() -> list:
    """Internal watcher emails from the Outreach Log's 'Watchers' tab.

    Defined page-side with only pre-existing service imports — the
    Streamlit-Cloud stale-module gotcha means the page must not import the
    fetch_watchers symbol from email_sender directly.
    """
    from services.sheets_client import fetch_log_rows
    sheet_id = os.getenv("EMAIL_LOG_SHEET_ID", "")
    if not sheet_id:
        return []
    try:
        df = fetch_log_rows(sheet_id, "Watchers")
    except Exception:
        return []
    if df is None or df.empty or "email" not in df.columns:
        return []
    out = []
    for e in df["email"].astype(str):
        e = e.strip().lower()
        if e and "@" in e and e not in out:
            out.append(e)
    return out


with tab_compose, _tab_guard("Email Composer"):
    st.markdown("### ✉️ Compose Outreach Email")

    # ── Step 1: Mode + recipients ─────────────────────────────────────────────
    compose_mode = st.radio(
        "Who are you emailing?",
        ["✍️ 1:1 — one person", "📣 Segment campaign — many"],
        key="compose_mode", horizontal=True,
        help="1:1 → a clean personal (Minimal) email to one contact. "
             "Segment campaign → the branded Newsletter to an AI segment.",
    )
    is_1to1 = compose_mode.startswith("✍️")
    # Design is implied by mode — no separate toggle. 1:1 = minimal, campaign = branded.
    email_layout = "minimal" if is_1to1 else "branded"

    overrides = st.session_state.setdefault("crm_name_overrides", {})
    _pool = contacts[contacts['has_email']].copy()
    _pool['person_name'] = _pool.apply(
        lambda r: overrides.get(r['email'], r['person_name']), axis=1)

    _step_header(1, "Pick the person" if is_1to1 else "Pick the segment",
                 "who receives this")

    if is_1to1:
        _pool['_label'] = _pool.apply(
            lambda r: f"{r['company']} — {r['person_name']} <{r['email']}>", axis=1)
        _opts = _pool.sort_values(['company', 'person_name'])['_label'].tolist()
        if not _opts:
            st.warning("No contacts with an email address found.")
            st.stop()
        _pick = st.selectbox("Contact", _opts, key="one_to_one_pick")
        recipients = _pool[_pool['_label'] == _pick].copy()
        st.caption("✍️ Sends one personal email to this contact.")
    else:
        _sc1, _sc2 = st.columns([2, 3])
        with _sc1:
            comp_ai_seg = st.selectbox(
                "AI Segment", AI_SEGMENTS, key="comp_ai_seg",
                help="Set per company via the 'AI Segment' column in the pipeline sheet.",
            )
        with _sc2:
            with st.expander("Refine (optional) — recency · owner", expanded=False):
                recency_opts = ["All", "🔥 Hot (<30d)", "☀️ Warm (30-90d)",
                                "❄️ Cool (90-180d)", "🧊 Cold (180+d)", "⚫ No date"]
                comp_recency = st.selectbox("Recency", recency_opts, key="comp_recency")
                _owners = sorted([o for o in contacts['outreach_owner'].unique()
                                  if o and o not in ('nan', 'Not needed', '')])
                comp_owner = st.selectbox("Owner", ["All"] + _owners, key="comp_owner")
        recipients = _pool[_pool['ai_segment'] == comp_ai_seg].copy()
        if comp_recency != "All":
            recipients = recipients[recipients['recency'] == comp_recency]
        if comp_owner != "All":
            recipients = recipients[recipients['outreach_owner'] == comp_owner]
        if recipients.empty:
            _uncl = int((_pool['ai_segment'] == 'Unclassified').sum())
            st.warning(
                f"No contacts tagged **{comp_ai_seg}** yet. Add an **AI Segment** column to "
                f"the pipeline sheet and tag companies (values: {', '.join(AI_SEGMENTS)}). "
                f"{_uncl} contacts are currently Unclassified."
            )
        st.caption(
            f"📣 {len(recipients)} contacts across "
            f"{recipients['company'].nunique() if not recipients.empty else 0} companies."
        )
        # What to send this segment — the Context arc calendar (the audience-list
        # per-account themes were retired with the playbook; the audience sheet
        # is still read invisibly for voice-hold exclusions).
        with st.expander(f"📅 Context arc — what to send {comp_ai_seg}", expanded=False):
            if not _render_theme_plan(comp_ai_seg):
                st.caption(
                    "Context arc not readable yet — check the 'Context arc - v2' tab in "
                    "Dhanashree's workbook is shared with the app's service account."
                )

    # View / edit recipient greeting names — feeds {name} in sends.
    with st.expander(f"View / edit recipient name(s) ({len(recipients)})", expanded=False):
        if not recipients.empty:
            st.caption(
                "✏️ Edit **Name** to fix how each contact is greeted in `{name}`. "
                "Names are guessed from the email address and usually need correcting; "
                "edits stick as you change mode/segment and apply to sends."
            )
            editor_df = recipients[['company', 'person_name', 'email', 'designation',
                                    'last_contact']].copy().reset_index(drop=True)
            editor_df['last_contact'] = editor_df['last_contact'].apply(
                lambda x: x.strftime('%d %b %Y') if pd.notna(x) else '—')
            editor_df = editor_df.rename(columns={
                'company': 'Company', 'person_name': 'Name', 'email': 'Email',
                'designation': 'Title', 'last_contact': 'Last Contact'})
            ed_key = f"recipient_editor_{hash(tuple(sorted(recipients['email'])))}"
            edited = st.data_editor(
                editor_df, use_container_width=True, hide_index=True,
                height=min(320, 80 + 35 * len(editor_df)), key=ed_key,
                column_config={'Name': st.column_config.TextColumn(
                    'Name ✏️', help="How this contact is greeted in the email — editable")},
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
    _step_header(2, "Choose design & compose", "shell + subject + body")

    # Body-design axis — orthogonal to the 1:1/Segment "who" axis above.
    # "Use a Graas design"  → today's Minimal (1:1) / Newsletter (Segment) shell.
    # "Paste my own HTML"   → raw: her HTML is sent exactly as authored, no shell,
    #                          no reformatting, no CID logo (email_layout="raw").
    _graas_shell_name = "Minimal note" if is_1to1 else "Newsletter"
    body_design = st.radio(
        "Body design",
        ["🎨 Use a Graas design", "📄 Paste my own HTML"],
        key="body_design", horizontal=True,
        help=f"🎨 Graas design → your text is wrapped in the {_graas_shell_name} shell. "
             "📄 Paste my own HTML → your HTML is sent exactly as written — no shell, "
             "no reformatting — for designed newsletters, images, etc. "
             "Personalisation ({name}/{company}/{vertical}) still works in both.",
    )
    use_raw = body_design.startswith("📄")
    if use_raw:
        # Override the mode-derived shell. Raw works in BOTH 1:1 and Segment.
        email_layout = "raw"

    template_name = "Custom"
    template = EMAIL_TEMPLATES["Custom"]
    if use_raw:
        st.caption(
            "📄 Sent as-authored — no Graas shell. Tokens like `{name}`/`{company}` still "
            "substitute; links are click-tracked (destinations + UTMs preserved), so opens "
            "AND clicks show in Analytics."
        )

    with st.container():
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
        if email_layout == "branded":
            headline = st.text_input(
                "Headline (big, on the newsletter)",
                value=subject, key="email_headline",
                help="The large bold headline at the top of the segment newsletter. "
                     "Defaults to the subject; edit it to be punchier. Supports "
                     "{name}/{company}/{vertical} like the body.",
            )
            deck = st.text_area(
                "Deck / sub-headline (optional)", value="", key="email_deck", height=68,
                help="One or two lines under the headline that set up the story. "
                     "Leave blank to skip.",
            )
        else:
            headline, deck = "", ""

        if use_raw:
            # Optional .html upload — read BEFORE the text_area so a new file can
            # seed the body field (Streamlit can't push into a widget's state
            # after it's instantiated on the same run). Guarded by file identity
            # so re-runs don't clobber hand-edits.
            _up = st.file_uploader(
                "Upload an .html file (optional)", type=["html", "htm"],
                key="raw_html_upload",
                help="Loads the file into the box below. You can still edit it after.",
            )
            if _up is not None:
                _uid = f"{_up.name}:{_up.size}"
                if st.session_state.get("_raw_html_uploaded_id") != _uid:
                    try:
                        st.session_state["email_body"] = _up.getvalue().decode(
                            "utf-8", errors="replace")
                        st.session_state["_raw_html_uploaded_id"] = _uid
                    except Exception as _e:
                        st.warning(f"Couldn't read that file: {_e}")
            body = st.text_area(
                "HTML body — renders as-authored", height=340, key="email_body",
                help="Paste your full email HTML. It's sent exactly as written: no "
                     "Graas shell, no markdown, no reformatting. `{name}`/`{company}`/"
                     "`{vertical}` tokens still substitute per recipient; bare URLs get "
                     "tracking links; your `<a>` tags are untouched. "
                     "⚠️ Images must be hosted at absolute https:// URLs — Gmail/Outlook "
                     "strip `data:` URIs, so pasted base64 images won't show.",
            )
            if body.strip() and "<" not in body:
                st.warning(
                    "⚠️ This looks like plain text, not HTML — in raw mode it sends as one "
                    "unformatted block (no paragraphs). Paste real HTML, or switch to "
                    "**Use a Graas design** for plain-text emails."
                )
        else:
            body = st.text_area("Body", value=template["body"], height=300, key="email_body")

    st.markdown("---")

    # ── Step 3: Preview ───────────────────────────────────────────────────────
    _step_header(3, "Preview", "how it lands, personalised")

    if not recipients.empty:
        preview_companies = recipients['company'].unique().tolist()
        preview_co = st.selectbox("Preview for", preview_companies, key="preview_co")

        preview_contacts = recipients[recipients['company'] == preview_co]
        if not preview_contacts.empty:
            pc = preview_contacts.iloc[0]
            # Render template — {name} = first name, {full_name} = full name
            # Case-insensitive: {Sender} / {sender} / {SENDER} all work.
            _pv_full = str(pc.get('person_name', '')).strip()
            _pv_first = _pv_full.split()[0] if _pv_full else _pv_full

            _pv_subs = {
                "company":    pc['company'],
                "name":       _pv_first,
                "full_name":  _pv_full,
                "vertical":   pc['vertical'],
                "sender":     sender_name,
                "designation": pc['designation'],
            }
            rendered_subject = _substitute(subject, _pv_subs)
            rendered_body = _substitute(body, _pv_subs)



            # Render the ACTUAL email shell (minimal or branded newsletter) so
            # the preview matches what lands in the inbox. CID logo is swapped
            # for a data: URI so it shows in the in-app iframe.
            from services.email_layout import (
                wrap_email, body_to_paragraphs, preview_html,
            )
            import streamlit.components.v1 as _components
            st.caption(f"To: {len(preview_contacts)} contact(s) at {preview_co} — each receives an individual email  ·  Subject: {rendered_subject}")
            if email_layout == "raw":
                # Bring-your-own HTML: render EXACTLY as authored (after token
                # substitution) — no shell, matching what the recipient gets.
                if rendered_body.strip():
                    if "<" not in rendered_body:
                        st.warning("⚠️ Plain text in raw-HTML mode — this will land as one unformatted block.")
                    st.caption("📄 Your HTML, personalised for this recipient — sent as-authored (no Graas shell).")
                    _components.html(rendered_body, height=760, scrolling=True)
                else:
                    st.info("Paste your HTML in the box above to see the preview.")
            else:
                _pv_headline = _substitute(headline, _pv_subs) if email_layout == "branded" else ""
                _pv_deck = _substitute(deck, _pv_subs) if email_layout == "branded" else ""
                _pv_shell = wrap_email(
                    email_layout,
                    body_to_paragraphs(rendered_body),
                    headline=_pv_headline, deck=_pv_deck,
                    date_str=datetime.now().strftime("%B %-d, %Y"),
                )
                _components.html(preview_html(_pv_shell), height=760, scrolling=True)

    st.markdown("---")

    # ── Step 4: Send ──────────────────────────────────────────────────────────
    _step_header(4, "Send", "test yourself first, then the batch")

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

        # 1:1 → the send. Segment → a collapsible test-to-yourself (bulk is the real action).
        _one_send = st.container() if is_1to1 else st.expander(
            "🧪 Send a test to yourself first", expanded=False)
        with _one_send:
            if is_1to1:
                st.markdown("##### Send")
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

                    target_no_touch = send_target.get("playbook_no_touch")
                    target_note = send_target.get("playbook_note", "")

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

                    _send_subs = {
                        "company":    send_target["company"],
                        "name":       _first_name,
                        "full_name":  _full_name,
                        "vertical":   send_target["vertical"],
                        "sender":     sender_name,
                        "designation": send_target.get("designation", ""),
                    }
                    rendered_subject_send = _substitute(subject, _send_subs)
                    rendered_body_send = _substitute(body, _send_subs)
                    rendered_headline_send = _substitute(headline, _send_subs)
                    rendered_deck_send = _substitute(deck, _send_subs)

                    # Item 4: warn (don't hard-block a 1:1) if this recipient is missing
                    # a personalisation field used in the email — the preview above shows
                    # the gap, but call it out explicitly so a broken "{Company}" doesn't
                    # slip to a named contact.
                    _single_missing = _missing_tokens(
                        _send_subs, _used_tokens(subject, body, headline, deck))
                    if _single_missing and not (test_mode and test_email):
                        st.warning(
                            "⚠️ **Missing personalisation for "
                            f"{send_target['company']}:** "
                            + ", ".join("`{"+t+"}`" for t in _single_missing)
                            + " is blank for this contact, so it'll render empty. "
                            "Fix the Name/field above or edit the copy before sending."
                        )

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

                    # Voice-hold — block real sends to accounts flagged
                    # "Voice — Hold Until Demo" in Dhanashree's audience sheet (held
                    # until the voice demo ships). Test mode is allowed (internal only).
                    voice_hold_block = False
                    if (not test_mode
                            and _normalize_company(send_target["company"]) in _voice_hold_companies()):
                        voice_hold_block = True
                        st.error(
                            f"🔇 **Cannot send to {send_target['company']}** — flagged "
                            f"**Voice — Hold Until Demo** in the audience sheet. These accounts "
                            f"are held until the voice demo ships. Use test mode to preview."
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
                            or voice_hold_block
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
                                        layout=email_layout,
                                        headline=rendered_headline_send,
                                        deck=rendered_deck_send,
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

        if not is_1to1:  # bulk send is only for segment campaigns
            # ── Bulk send to filtered set ─────────────────────────────────────────
            st.markdown("---")
            st.markdown("##### 📨 Bulk send to everyone in this segment")
            if is_1to1:
                st.caption(
                    "✍️ You're in **1:1** mode — use **Send the previewed email** above; "
                    "bulk isn't needed for one person."
                )
            st.caption(
                "Same body to everyone in the segment, `{name}`/`{company}`/`{vertical}` filled "
                "per person. Keep the body generic — one-off personal lines go to all."
            )

            if recipients.empty or not contact_options:
                st.caption("No recipients in current filter. Adjust filters in Step 1 above.")
            else:
                # ── Pre-flight: build filter pipeline ─────────────────────────
                bulk_pool = recipients[recipients["email"].apply(lambda e: bool(e) and "@" in str(e))].copy()
                bulk_pool["_email_norm"] = bulk_pool["email"].str.lower().str.strip()
                # One email = one send, even if the contact appears under two
                # company rows (sheet + overlay) — guards against double-sends.
                bulk_pool = bulk_pool.drop_duplicates("_email_norm")

                # Stage 1: total
                stage_total = len(bulk_pool)

                # Stage 2: remove No-Touch companies
                # bool() wrap is critical: v.get("category") returns the category STRING
                # when truthy, not True. Without the wrap, .apply() returns a Series of
                # mixed str/False values; pandas then treats it as label-indexing and
                # crashes with KeyError. Symptom is the whole page failing to render
                # (Streamlit runs every tab body regardless of which tab is visible),
                # so the Analytics tab dies too. Hit when the new unified pipeline tab
                # contains any NO_TOUCH company (Hindware, Growsari, etc.).
                def _is_no_touch(v):
                    return bool(isinstance(v, dict) and v.get("category"))
                no_touch_mask = bulk_pool.get("playbook_no_touch", pd.Series([False]*len(bulk_pool))).apply(_is_no_touch)
                bulk_no_touch = bulk_pool[no_touch_mask]
                after_no_touch = bulk_pool[~no_touch_mask]
                stage_after_nt = len(after_no_touch)

                # Stage 2b: remove voice-hold accounts (flagged "Voice — Hold Until
                # Demo" in Dhanashree's audience sheet — held until the voice demo).
                _vh_set = _voice_hold_companies()
                if _vh_set:
                    vh_mask = after_no_touch["company"].apply(
                        lambda c: _normalize_company(str(c)) in _vh_set)
                    bulk_voice_hold = after_no_touch[vh_mask]
                    after_no_touch = after_no_touch[~vh_mask]
                else:
                    bulk_voice_hold = after_no_touch.iloc[0:0]
                stage_after_vh = len(after_no_touch)

                # Stage 3: remove suppressed
                with st.spinner("Loading suppression + recent-send data…"):
                    supp_set = suppressed_emails()
                    recent_set = recent_sent_emails(get_dedup_days())
                    watcher_list = _fetch_watchers_page()
                sup_mask = after_no_touch["_email_norm"].isin(supp_set)
                bulk_supp = after_no_touch[sup_mask]
                after_supp = after_no_touch[~sup_mask]
                stage_after_supp = len(after_supp)

                # Stage 4: remove recently-sent (dedup window)
                dedup_mask = after_supp["_email_norm"].isin(recent_set)
                bulk_dedup = after_supp[dedup_mask]
                after_dedup = after_supp[~dedup_mask]
                stage_after_dedup = len(after_dedup)

                # Stage 5: remove recipients missing a personalisation field used in
                # this email (item 4). Rather than ship "Hi , ... at " to a named
                # enterprise contact, we EXCLUDE the row — surfaced below so she can
                # fix the data or edit the copy. Only tokens actually used are checked.
                used_tokens = _used_tokens(subject, body, headline, deck)
                if used_tokens:
                    _miss_mask = after_dedup.apply(
                        lambda r: bool(_missing_tokens(_row_subs(r, sender_name), used_tokens)),
                        axis=1,
                    )
                    bulk_missing = after_dedup[_miss_mask]
                    after_dedup = after_dedup[~_miss_mask]
                else:
                    bulk_missing = after_dedup.iloc[0:0]
                stage_final = len(after_dedup)

                # Headline count + a one-line skip summary (full breakdown is in the
                # "filtered out" expander below — no need for the 5-line pipeline).
                st.markdown(f"### → Will send to **{stage_final}** of {stage_total}")
                _skipped = stage_total - stage_final
                if _skipped:
                    _miss_bit = (f" · {len(bulk_missing)} missing "
                                 f"{'/'.join('{'+t+'}' for t in sorted(used_tokens))}"
                                 if len(bulk_missing) else "")
                    _vh_bit = f"{stage_after_nt - stage_after_vh} voice-hold · " if len(bulk_voice_hold) else ""
                    st.caption(
                        f"{_skipped} skipped — "
                        f"{stage_total - stage_after_nt} no-touch · "
                        f"{_vh_bit}"
                        f"{stage_after_vh - stage_after_supp} suppressed · "
                        f"{stage_after_supp - stage_after_dedup} emailed in last {get_dedup_days()}d"
                        f"{_miss_bit} · details below."
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
                        if not bulk_voice_hold.empty:
                            st.markdown(f"**🔇 Voice — Hold Until Demo ({len(bulk_voice_hold)}):** held until the voice demo ships.")
                            st.dataframe(
                                bulk_voice_hold[["company", "person_name", "email"]].rename(
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
                        if not bulk_missing.empty:
                            _tok_str = ", ".join("{"+t+"}" for t in sorted(used_tokens))
                            st.markdown(
                                f"**⚠️ Missing personalisation field ({len(bulk_missing)}):** "
                                f"excluded because a token used in this email ({_tok_str}) is "
                                f"blank for them. Fix the sheet or edit the copy, then re-check.")
                            _miss_df = bulk_missing.copy()
                            _miss_df["Missing"] = _miss_df.apply(
                                lambda r: ", ".join("{"+t+"}" for t in
                                    _missing_tokens(_row_subs(r, sender_name), used_tokens)),
                                axis=1)
                            st.dataframe(
                                _miss_df[["company", "person_name", "email", "Missing"]].rename(
                                    columns={"company": "Company", "person_name": "Name", "email": "Email"}),
                                use_container_width=True, hide_index=True, height=140)

                # Preview of who WILL be sent to — with each used token resolved per
                # recipient (item 4: validate the substitution BEFORE the batch sends).
                if stage_final > 0:
                    with st.expander(f"📋 Preview the {stage_final} recipient(s) who WILL be sent to"):
                        _prev_df = after_dedup[["company", "person_name", "email", "playbook_bucket"]].rename(
                            columns={"company": "Company", "person_name": "Name",
                                     "email": "Email", "playbook_bucket": "Bucket"})
                        if used_tokens:
                            for _t in sorted(used_tokens):
                                _prev_df[f"{{{_t}}}"] = after_dedup.apply(
                                    lambda r: _row_subs(r, sender_name).get(_t, ""), axis=1).values
                            st.caption(
                                "Columns `{name}`/`{company}`/… show exactly what each recipient "
                                "will see substituted in. (Anyone with a blank was already excluded above.)")
                        st.dataframe(_prev_df, use_container_width=True, hide_index=True, height=300)

                # Bulk send button — two-step confirm
                bulk_confirm_key = "bulk_confirm_armed"
                if bulk_confirm_key not in st.session_state:
                    st.session_state[bulk_confirm_key] = False

                if bulk_blocked_reason:
                    st.error(f"⚠️ {bulk_blocked_reason}")

                # Internal copies — optional per campaign (Dhanashree: watchers
                # shouldn't get every batch). Default ON for the first batch of a
                # campaign; untick for follow-up batches of the same campaign.
                watchers_selected = []
                if watcher_list:
                    # Smart default: if watchers already got a copy of this campaign
                    # (same subject, earlier batch), default OFF so follow-up batches
                    # don't hit them again. Ticking re-enables deliberately.
                    _w_dup = False
                    try:
                        _wlog = _cached_log_df()
                        if not _wlog.empty and "subject" in _wlog.columns and "template" in _wlog.columns:
                            _int_sent = _wlog[
                                (_wlog["status"] == "sent")
                                & _wlog["template"].astype(str).str.endswith("(internal copy)")]
                            _w_dup = (_int_sent["subject"].astype(str)
                                      .str.replace(r"^\[Internal\] ", "", regex=True)
                                      .eq(str(subject)).any())
                    except Exception:
                        pass
                    if _w_dup:
                        st.caption("ℹ️ Watchers already received a copy of this campaign "
                                   "(same subject) — internal copies default **off**; tick to send again.")
                    _w_on = st.checkbox(
                        f"📣 Send internal copies to watchers ({len(watcher_list)})",
                        value=not _w_dup, key="watchers_on",
                        help="One [Internal] copy of this campaign to each selected watcher "
                             "(Watchers tab of the Outreach Log). Not counted in the weekly cap. "
                             "Defaults off automatically when watchers already saw this campaign.",
                    )
                    if _w_on:
                        with st.expander(f"Choose watchers ({len(watcher_list)} selected by default)",
                                         expanded=False):
                            watchers_selected = st.multiselect(
                                "Watchers to copy", watcher_list, default=watcher_list,
                                key="watchers_pick", label_visibility="collapsed",
                            )
                    else:
                        watchers_selected = []

                bcols = st.columns([2, 1, 1])
                with bcols[0]:
                    if not bulk_blocked_reason:
                        _w_bit = (f"  \n**Internal copies:** {len(watchers_selected)} watcher(s) — "
                                  "not counted in cap" if watchers_selected else
                                  "  \n**Internal copies:** off for this send")
                        st.markdown(
                            f"**Will send {stage_final} email(s) via:** {sender_display_name} `<{sender_reply_to}>`  \n"
                            f"**Framework:** {template_name}  \n"
                            f"**Cap impact:** {used}/{cap} → **{used + stage_final}/{cap}**"
                            f"{_w_bit}"
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
                                _r_subs = {
                                    "company":    row["company"],
                                    "name":       r_first,
                                    "full_name":  r_full,
                                    "vertical":   row["vertical"],
                                    "sender":     sender_name,
                                    "designation": row.get("designation", ""),
                                }
                                r_subj = _substitute(subject, _r_subs)
                                r_body = _substitute(body, _r_subs)
                                r_headline = _substitute(headline, _r_subs)
                                r_deck = _substitute(deck, _r_subs)

                                _b_kwargs = dict(
                                    sender_label=sender_label,
                                    to_email=row["email"],
                                    to_name=r_full,
                                    company=row["company"],
                                    subject=r_subj,
                                    body=r_body,
                                    bucket=str(comp_ai_seg),
                                    template=template_name,
                                    bypass_dedup=False,
                                    layout=email_layout,
                                    headline=r_headline,
                                    deck=r_deck,
                                )
                                try:
                                    # precleared: the pre-flight pipeline above already ran
                                    # cap/suppression/dedup for the whole batch — skipping
                                    # the per-recipient re-reads keeps us under the Sheets
                                    # API quota (what dropped log rows on Aug 21).
                                    ok_b, msg_b = send_email(precleared=True, **_b_kwargs)
                                except TypeError:
                                    ok_b, msg_b = send_email(**_b_kwargs)
                                if ok_b:
                                    sent_n += 1
                                else:
                                    failed_n += 1
                                    failures.append((row["email"], msg_b))
                                progress_bar.progress(i / stage_final, text=f"Sending {i} of {stage_final}…")

                            # Internal watcher copies — one per watcher, personalised
                            # for a sample recipient so watchers see what the campaign
                            # actually looked like. Bypasses dedup + weekly cap; logged
                            # as "(internal copy)" so analytics can filter them out.
                            watcher_sent, watcher_failed = 0, 0
                            if watchers_selected and sent_n > 0:
                                progress_bar.progress(1.0, text="Sending internal copies…")
                                _wrow = after_dedup.iloc[0]
                                _w_full = str(_wrow.get("person_name", "")).strip()
                                _w_subs = {
                                    "company":    _wrow["company"],
                                    "name":       _w_full.split()[0] if _w_full else _w_full,
                                    "full_name":  _w_full,
                                    "vertical":   _wrow["vertical"],
                                    "sender":     sender_name,
                                    "designation": _wrow.get("designation", ""),
                                }
                                _w_kwargs = dict(
                                    sender_label=sender_label,
                                    subject="[Internal] " + _substitute(subject, _w_subs),
                                    body=_substitute(body, _w_subs),
                                    company="[INTERNAL WATCHER]",
                                    bucket="internal",
                                    template=template_name + " (internal copy)",
                                    bypass_dedup=True,
                                    layout=email_layout,
                                    headline=_substitute(headline, _w_subs),
                                    deck=_substitute(deck, _w_subs),
                                )
                                for _w_email in watchers_selected:
                                    try:
                                        ok_w, msg_w = send_email(
                                            to_email=_w_email, to_name="Graas Internal",
                                            bypass_cap=True, precleared=True, **_w_kwargs)
                                    except TypeError:
                                        # Stale service module on Cloud without the new
                                        # kwargs — send anyway (checks apply).
                                        ok_w, msg_w = send_email(
                                            to_email=_w_email, to_name="Graas Internal",
                                            **_w_kwargs)
                                    if ok_w:
                                        watcher_sent += 1
                                    else:
                                        watcher_failed += 1
                                        failures.append((f"{_w_email} (watcher)", msg_w))

                            progress_bar.empty()
                            st.session_state[bulk_confirm_key] = False
                            # Stash result for persistent banner
                            st.session_state["last_bulk_result"] = (
                                sent_n, failed_n, failures, watcher_sent, watcher_failed)
                            st.rerun()

                with bcols[2]:
                    if st.session_state[bulk_confirm_key]:
                        if st.button("Cancel", use_container_width=True, key="bulk_cancel"):
                            st.session_state[bulk_confirm_key] = False
                            st.rerun()

                # Show last bulk result if any
                last_bulk = st.session_state.get("last_bulk_result")
                if last_bulk:
                    # 5-tuple since watcher copies landed; tolerate a stale 3-tuple
                    # left in session_state from before the deploy.
                    if len(last_bulk) == 5:
                        bsent, bfail, bfailures, bwsent, bwfail = last_bulk
                    else:
                        bsent, bfail, bfailures = last_bulk
                        bwsent, bwfail = 0, 0
                    _w_note = f" · **{bwsent} internal cop{'y' if bwsent == 1 else 'ies'}**" if (bwsent or bwfail) else ""
                    if bfail == 0 and bwfail == 0:
                        st.success(f"✅ Bulk send complete — **{bsent} sent**, 0 failed{_w_note}.")
                    else:
                        st.warning(f"⚠️ Bulk send done — **{bsent} sent**, **{bfail + bwfail} failed**{_w_note}.")
                        with st.expander(f"View {bfail + bwfail} failure(s)"):
                            for em, why in bfailures:
                                st.markdown(f"- `{em}` — {why}")
                    if st.button("Dismiss bulk result", key="dismiss_bulk_result"):
                        del st.session_state["last_bulk_result"]
                        st.rerun()

        st.caption("📊 Open the **Analytics** tab to see send history, volume by sender, and outreach metrics.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB: CALENDAR — the Context arc content calendar (Sept–Dec), live from the
# workbook tab (rename-proof: matched by header signature). Read-only mirror;
# editing stays in the sheet so Dhanashree keeps full flexibility.
# ══════════════════════════════════════════════════════════════════════════════

with tab_calendar, _tab_guard("Calendar"):
    st.markdown("### 📅 Content calendar — the Context arc")
    st.caption(
        "One argument, taught in two tracks. Every email carries **Context** and one "
        "Index receipt. Emails 1–2 go to everyone; Mature gets the architecture track, "
        "Explorers + Laggards get the show-don't-tell track. Edit in "
        "[the workbook tab ↗](https://docs.google.com/spreadsheets/d/11uhucHZ6099LysoifJRmeGCx5DQ57ZxEa94Q0HjpaPo/edit?gid=1357660099) "
        "— Target window + Status columns are Dhanashree's to fill."
    )
    _cal = _load_theme_plan()
    if not _cal.empty and "audience" not in _cal.columns:
        _cal = pd.DataFrame()  # stale cache / restructured sheet — treat as unreadable
    if _cal.empty:
        st.info("Calendar not readable — check the Context arc tab is shared with the "
                "app's service account.")
    else:
        _cal_view = _cal.rename(columns={
            "code": "#", "theme": "Email", "question": "Core question",
            "audience": "Audience", "target": "Target window", "status": "Status"})
        _tracks = [
            ("📣 Everyone (both tracks open with these)", _cal_view["Audience"].str.lower().str.contains("all")),
            ("🏛️ Mature track — architecture", _cal_view["Audience"].str.lower().str.contains("matur")),
            ("📷 Explorers + Laggards track — show, don't tell", _cal_view["Audience"].str.lower().str.contains("laggard|explor", regex=True)),
        ]
        for _title, _mask in _tracks:
            _t = _cal_view[_mask]
            if _t.empty:
                continue
            st.markdown(f"#### {_title}")
            _cols_show = [c for c in ["#", "Email", "Core question", "Target window", "Status"]
                          if c in _t.columns]
            _tsty = _t[_cols_show].style.set_properties(
                subset=["Status"] if "Status" in _cols_show else [],
                **{"background-color": "#DBEAFE", "color": "#1D4ED8", "font-weight": "600"})
            st.dataframe(_tsty, hide_index=True, use_container_width=True,
                         height=min(300, 80 + 35 * len(_t)))
        st.caption(
            "Blogs: emails 4/5/6 click through to graas.ai articles (the Knowledge Graph "
            "piece links onward to the technical deep dive). Cadence: fortnightly — "
            "matches the 14-day dedup window."
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5: ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

with tab_analytics, _tab_guard("Analytics"):
    st.markdown("### 📊 Outreach Analytics")
    st.caption("Email outreach metrics from the Graas Outreach Log. "
               "Sent, opens and clicks are tracked. Replies and unsubscribes are not yet — "
               "they need Gmail reply-polling and a hosted unsubscribe endpoint.")

    from services.email_sender import (
        get_weekly_cap as _get_weekly_cap,
        preflight_check as _preflight_check,
        fetch_suppressions as _fetch_suppressions,
        add_to_suppression as _add_to_suppression,
    )

    a_pre_err = _preflight_check()
    if a_pre_err:
        st.warning(f"⚠️ {a_pre_err} — analytics will be empty until email sending is configured (see **Email Composer** tab).")

    # Pull the full log + tracking beacons ONCE (90s cache) — every section
    # below reuses these two frames instead of re-reading the sheet.
    log_df = _cached_log_df()
    track_df = _cached_tracking_df()
    if track_df is not None and not track_df.empty and "tracking_id" in track_df.columns:
        track_df = track_df.copy()
        track_df["tracking_id"] = track_df["tracking_id"].astype(str).str.strip()
        track_df["event"] = track_df.get("event", "").astype(str).str.strip().str.lower()

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

        # ── KPI tiles — externals only (tests + internal copies excluded) ─────
        def _externals(df):
            out = df
            if "company" in out.columns:
                out = out[~out["company"].astype(str).str.contains(r"\[INTERNAL WATCHER\]|\[TEST\]", regex=True, na=False)]
            if "template" in out.columns:
                out = out[~out["template"].astype(str).str.contains(r"\(test\)|\(internal copy\)", regex=True, na=False)]
            return out

        _ext7 = _externals(sent_7d)
        _ext30 = _externals(sent_30d)
        _op_ids, _cl_ids, _cl_counts = set(), set(), {}
        if track_df is not None and not track_df.empty and "tracking_id" in track_df.columns:
            _op_ids = set(track_df.loc[track_df["event"] == "open", "tracking_id"])
            _cl_ev = track_df[track_df["event"] == "click"]
            _cl_ids = set(_cl_ev["tracking_id"])
            _cl_counts = _cl_ev.groupby("tracking_id").size().to_dict()

        def _tid_series(df):
            return (df["tracking_id"].astype(str).str.strip()
                    if "tracking_id" in df.columns else pd.Series([], dtype=str))

        _t7 = _tid_series(_ext7)
        _delivered7 = len(_ext7)
        _opened7 = int(_t7.isin(_op_ids).sum())
        _clicks7 = int(sum(_cl_counts.get(t, 0) for t in _t7))
        _t30 = _tid_series(_ext30)
        _hot30 = int(_ext30.loc[_t30.isin(_cl_ids)]["company"].nunique()) if len(_ext30) else 0

        supp_df = _fetch_suppressions()
        _unsub_n = 0
        if not supp_df.empty and "reason" in supp_df.columns:
            _unsub_n = int(supp_df["reason"].astype(str).str.lower()
                           .str.contains("unsub").sum())
        _supp_total = 0 if supp_df.empty else len(supp_df)

        k1, k2, k3, k4, k5 = st.columns(5)
        _b7 = {b["email"] for b in _cached_bounces()}
        _bounced7 = int(_tid_series(_ext7).index.isin(
            _ext7[_ext7["to_email"].astype(str).str.lower().isin(_b7)].index).sum()) if _b7 else 0
        k1.metric("📤 Delivered (7d)", _delivered7 - _bounced7,
                  help=f"External sends accepted by Gmail, minus {_bounced7} known bounce(s) in the window. "
                       f"{len(_ext30)} sent in last 30d. See Delivery issues below.")
        k2.metric("👀 Open rate (7d)", f"{round(_opened7 / _delivered7 * 100)}%" if _delivered7 else "—",
                  help="Unique external sends opened. Directional — Apple Mail/Gmail prefetch inflates it.")
        k3.metric("🔗 Clicks (7d)", _clicks7,
                  help="Total link clicks on external sends — a deliberate action, the number to trust.")
        k4.metric("🔥 Hot accounts (30d)", _hot30,
                  help="Companies with at least one click in the last 30 days — see Account heat below.")
        k5.metric("🚫 Unsubscribed", _unsub_n,
                  help=f"Suppression-list entries whose reason mentions unsubscribe "
                       f"(added when someone replies 'unsubscribe'). Total suppressed: {_supp_total}.")

        # Weekly cap row — computed from the already-fetched frame (mirrors
        # get_sends_this_week incl. the internal-copy exclusion) instead of
        # re-reading the sheet.
        cap = _get_weekly_cap()
        _cap_df = sent_7d
        if "template" in _cap_df.columns:
            _cap_df = _cap_df[~_cap_df["template"].astype(str).str.endswith("(internal copy)")]
        used = len(_cap_df)
        st.markdown(f"**Weekly send cap:** {used} / {cap} used · {max(0, cap - used)} remaining")
        st.progress(min(used / cap, 1.0) if cap > 0 else 0)

        # Failure callout
        if not failed_7d.empty:
            st.error(f"⚠️ {len(failed_7d)} send failure(s) in the last 7 days — see Recent sends below for details.")

        # ── Segments at a glance — audience size + engagement per AI segment ──
        st.markdown("---")
        st.markdown("#### 🎯 Segments at a glance")
        _seg_order = ["AI Laggard", "AI Exploring", "AI Mature", "Unclassified"]
        _aud = contacts[contacts["has_email"]].copy() if "has_email" in contacts.columns else contacts.copy()
        _aud["ai_segment"] = _aud["ai_segment"].fillna("Unclassified").replace("", "Unclassified")
        _email_seg = {str(e).strip().lower(): sgm for e, sgm in zip(_aud["email"], _aud["ai_segment"])}
        _e30 = _ext30.copy()
        _e30["_seg"] = _e30["to_email"].astype(str).str.strip().str.lower().map(_email_seg).fillna("Unclassified")
        _e30["_tid"] = _tid_series(_e30)
        _seg_rows = []
        for _sg in _seg_order:
            _a = _aud[_aud["ai_segment"] == _sg]
            _sv = _e30[_e30["_seg"] == _sg]
            _seg_rows.append({
                "Segment": _sg,
                "Companies": int(_a["company"].nunique()),
                "Contacts": int(len(_a)),
                "Sends (30d)": int(len(_sv)),
                "Opened": int(_sv["_tid"].isin(_op_ids).sum()),
                "Clicks": int(sum(_cl_counts.get(t, 0) for t in _sv["_tid"])),
            })
        _seg_df = pd.DataFrame(_seg_rows)
        _ssty = (_seg_df.style
                 .set_properties(subset=["Clicks"],
                                 **{"background-color": "#DBEAFE", "color": "#1D4ED8", "font-weight": "700"})
                 .set_properties(subset=["Opened"],
                                 **{"background-color": "#F5F3FF", "color": "#6D28D9", "font-weight": "600"}))
        st.dataframe(_ssty, use_container_width=True, hide_index=True,
                     height=min(260, 80 + 35 * len(_seg_df)))
        st.caption("Audience = contacts with an email in the pipeline sheet, by AI segment. "
                   "Engagement = external campaign sends in the last 30 days, attributed via each recipient's segment.")

        # Full export WITH engagement — sends joined to the Tracking beacons so
        # the CSV answers "who opened / who clicked" without cross-referencing.
        _exp = log_df.sort_values("_ts", ascending=False).copy()
        _exp["timestamp_utc"] = _exp["_ts"].dt.strftime("%Y-%m-%d %H:%M UTC")
        _exp["opened"], _exp["open_count"] = False, 0
        _exp["clicked"], _exp["click_count"], _exp["clicked_urls"] = False, 0, ""
        _ev = track_df if track_df is not None else pd.DataFrame()
        if not _ev.empty and "tracking_id" in _ev.columns and "tracking_id" in _exp.columns:
            _opens = _ev[_ev["event"] == "open"].groupby("tracking_id").size()
            _clicks = _ev[_ev["event"] == "click"].groupby("tracking_id").size()
            _urls = (_ev[_ev["event"] == "click"].groupby("tracking_id")["dest_url"]
                     .apply(lambda s: " | ".join(sorted(set(str(x) for x in s if str(x).strip()))))
                     if "dest_url" in _ev.columns else None)
            _tid = _exp["tracking_id"].astype(str).str.strip()
            _exp["open_count"] = _tid.map(_opens).fillna(0).astype(int)
            _exp["click_count"] = _tid.map(_clicks).fillna(0).astype(int)
            _exp["opened"] = _exp["open_count"] > 0
            _exp["clicked"] = _exp["click_count"] > 0
            if _urls is not None:
                _exp["clicked_urls"] = _tid.map(_urls).fillna("")

        # ── Account heat + circulating sends ─────────────────────────────────
        # Built on the engagement-joined frame above. Real campaign sends only —
        # tests and internal watcher copies excluded.
        _rl = _exp[(_exp["status"] == "sent")
                   & (_exp["_ts"] >= now_utc - pd.Timedelta(days=30))].copy()
        _rl = _rl[~_rl["company"].astype(str).str.contains(r"\[INTERNAL WATCHER\]|\[TEST\]", regex=True, na=False)]
        _rl = _rl[~_rl["template"].astype(str).str.contains(r"\(test\)|\(internal copy\)", regex=True, na=False)]

        # ── Delivery issues (bounces) ────────────────────────────────────────
        # "sent" only means Gmail accepted it; rejections arrive later as bounce
        # mail to insights@. This surfaces them so the log means "delivered".
        _bounces = _cached_bounces()
        if _bounces:
            _bdf = pd.DataFrame(_bounces)
            _sup_now = set()
            if not supp_df.empty and "email" in supp_df.columns:
                _sup_now = set(supp_df["email"].astype(str).str.lower().str.strip())
            _bdf["Suppressed"] = _bdf["email"].isin(_sup_now)
            _open_hard = _bdf[(_bdf["hard"]) & (~_bdf["Suppressed"])]
            st.markdown("#### ↩️ Delivery issues")
            st.caption(
                "Bounce reports read from the insights@ inbox — these addresses were "
                "logged as *sent* (Gmail accepted them) but the receiving server "
                "rejected them afterwards. Hard bounces should be suppressed."
            )
            if not _open_hard.empty:
                st.error(f"⚠️ **{len(_open_hard)} hard bounce(s) not yet suppressed** — "
                         "they'll keep consuming sends until suppressed.")
                if st.button(f"🚫 Suppress {len(_open_hard)} bounced address(es)",
                             type="primary", key="supp_bounces"):
                    _ok = 0
                    for _, _br in _open_hard.iterrows():
                        if _add_to_suppression(_br["email"],
                                               f"hard bounce — {_br['reason']}",
                                               "bounce scanner"):
                            _ok += 1
                    st.success(f"✅ Suppressed {_ok} address(es).")
                    st.rerun()
            _bshow = (_bdf.rename(columns={"email": "Address", "reason": "Reason",
                                           "date": "Bounced", "subject": "Report"})
                          .assign(Type=lambda d: d["hard"].map({True: "Hard", False: "Soft"}))
                          [["Address", "Type", "Reason", "Bounced", "Suppressed"]])
            st.dataframe(_bshow, hide_index=True, use_container_width=True,
                         height=min(320, 80 + 35 * len(_bshow)))

        st.markdown("#### 🔥 Account heat (last 30d)")
        st.caption(
            "Engagement rolled up per company — multiple stakeholders opening is a "
            "buying-committee signal. Sorted hottest first: clicks, then sends opened, "
            "then total opens."
        )
        if _rl.empty:
            st.caption("No campaign sends in the last 30 days yet.")
        else:
            _heat = (_rl.groupby("company")
                       .agg(**{
                           "Contacts": ("to_email", "nunique"),
                           "Sends": ("to_email", "size"),
                           "Sends opened": ("opened", "sum"),
                           "Total opens": ("open_count", "sum"),
                           "Clicks": ("click_count", "sum"),
                           "Last send": ("_ts", "max"),
                       })
                       .reset_index()
                       .rename(columns={"company": "Company"}))
            _heat["Last send"] = _heat["Last send"].dt.strftime("%d %b")
            _heat = _heat.sort_values(["Clicks", "Sends opened", "Total opens"],
                                      ascending=False).reset_index(drop=True)
            _hsty = (_heat.style
                     .set_properties(subset=["Clicks"],
                                     **{"background-color": "#DBEAFE", "color": "#1D4ED8", "font-weight": "700"})
                     .set_properties(subset=["Sends opened", "Total opens"],
                                     **{"background-color": "#F5F3FF", "color": "#6D28D9", "font-weight": "600"}))
            st.dataframe(_hsty, use_container_width=True, hide_index=True,
                         height=min(640, 80 + 35 * len(_heat)))

        st.markdown("#### 🔁 Circulating sends (3+ opens)")
        st.caption(
            "Sends opened three or more times — the email is being revisited or passed "
            "around internally (the closest measurable proxy for a forward). Treat as a "
            "warm-lead signal; some inflation from Apple Mail/Gmail image prefetch."
        )
        _circ = _rl[_rl["open_count"] >= 3].copy()
        if _circ.empty:
            st.caption("None yet — appears once any send is opened 3+ times.")
        else:
            _circ["Sent"] = _circ["_ts"].dt.strftime("%d %b")
            _circ["Subject"] = _circ["subject"].astype(str).str.slice(0, 60)
            _circ = (_circ.rename(columns={"company": "Company", "to_email": "Recipient",
                                           "open_count": "Opens", "click_count": "Clicks"})
                         .sort_values("Opens", ascending=False))
            _csty = (_circ[["Company", "Recipient", "Subject", "Opens", "Clicks", "Sent"]].style
                     .set_properties(subset=["Clicks"],
                                     **{"background-color": "#DBEAFE", "color": "#1D4ED8", "font-weight": "700"})
                     .set_properties(subset=["Opens"],
                                     **{"background-color": "#F5F3FF", "color": "#6D28D9", "font-weight": "700"}))
            st.dataframe(_csty, use_container_width=True, hide_index=True,
                         height=min(520, 80 + 35 * len(_circ)))

        st.markdown("---")

        # ── Campaign performance — one row per campaign (subject), externals ──
        st.markdown("#### 📮 Campaign performance (last 30d)")
        if _rl.empty:
            st.caption("No campaign sends in the last 30 days.")
        else:
            _cp = (_rl.groupby("subject")
                     .agg(**{"First sent": ("_ts", "min"), "Sent": ("to_email", "size"),
                             "Opened": ("opened", "sum"), "Clicks": ("click_count", "sum"),
                             "_clicked_sends": ("clicked", "sum")})
                     .reset_index().rename(columns={"subject": "Campaign"}))
            _cp["Open %"] = (_cp["Opened"] / _cp["Sent"] * 100).round(0).astype(int)
            _cp["Click %"] = (_cp["_clicked_sends"] / _cp["Sent"] * 100).round(0).astype(int)
            _cp = _cp.sort_values("First sent", ascending=False)
            _cp["First sent"] = _cp["First sent"].dt.strftime("%d %b")
            _cp = _cp[["Campaign", "First sent", "Sent", "Opened", "Open %", "Clicks", "Click %"]]
            _psty = (_cp.style
                     .set_properties(subset=["Clicks", "Click %"],
                                     **{"background-color": "#DBEAFE", "color": "#1D4ED8", "font-weight": "700"})
                     .set_properties(subset=["Opened", "Open %"],
                                     **{"background-color": "#F5F3FF", "color": "#6D28D9", "font-weight": "600"}))
            st.dataframe(_psty, use_container_width=True, hide_index=True,
                         height=min(400, 80 + 35 * len(_cp)))
            st.caption("Campaigns are identified by subject line. Judge on **Click %** — opens are "
                       "inflated by Apple Mail/Gmail prefetch. Tests and internal copies are excluded "
                       "from every number on this page.")

        st.markdown("---")

        # ── Recent sends table ────────────────────────────────────────────────
        st.markdown("#### 📬 Recent sends")
        recent_view = log_df.sort_values("_ts", ascending=False).head(50).copy()
        recent_view["timestamp_utc"] = recent_view["_ts"].dt.strftime("%d %b %H:%M UTC")
        cols_to_show = [c for c in
            ["timestamp_utc", "sender_label", "to_email", "company", "template", "subject", "status", "error_msg"]
            if c in recent_view.columns]
        st.dataframe(recent_view[cols_to_show], use_container_width=True, hide_index=True, height=420)

        _exp_cols = [c for c in
            ["timestamp_utc", "sender_label", "to_email", "company", "template", "subject",
             "status", "error_msg", "opened", "open_count", "clicked", "click_count", "clicked_urls"]
            if c in _exp.columns]
        st.download_button(
            "⬇️ Download all sends + opens/clicks (CSV)",
            _exp[_exp_cols].to_csv(index=False).encode("utf-8"),
            file_name=f"graas_sends_engagement_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv", key="dl_sends_engagement",
        )
        st.caption(
            "⚠️ Click columns only populate for campaigns sent AFTER 21 Aug 2026 — earlier "
            "raw-HTML sends linked out directly, so their clicks were never measurable here "
            "(check GA for `utm_campaign` instead). Opens are directional (Apple Mail/Gmail prefetch)."
        )



        # ── Campaign creatives ───────────────────────────────────────────────
        # The Sends log stores the full body per send, so every campaign's
        # creative is already archived — this just makes it findable: pick a
        # campaign, see the exact copy that went out, download the HTML.
        if "body" in log_df.columns:
            st.markdown("#### 🎨 Campaign creatives")
            _cr = log_df[(log_df["status"] == "sent")
                         & (log_df["body"].astype(str).str.strip() != "")].copy()
            _cr = _cr[~_cr["template"].astype(str).str.contains(r"\(test\)|\(internal copy\)", regex=True)]
            if _cr.empty:
                st.caption("No campaign sends with stored copy yet.")
            else:
                _cr = _cr.sort_values("_ts", ascending=False)
                _first = _cr.groupby("subject", sort=False).first().reset_index()
                _counts = _cr.groupby("subject")["to_email"].nunique()
                _opts = {
                    f"{r['subject']}  —  {r['_ts'].strftime('%d %b %Y')} · {_counts.get(r['subject'], 0)} recipient(s)": r["subject"]
                    for _, r in _first.iterrows()
                }
                _pick = st.selectbox("Campaign", list(_opts.keys()), key="creative_pick")
                _row = _first[_first["subject"] == _opts[_pick]].iloc[0]
                _body = str(_row["body"])
                _is_html = _body.lstrip()[:200].lower().find("<") != -1 and (
                    "<html" in _body.lower() or "<table" in _body.lower() or "<div" in _body.lower())
                _slug = re.sub(r"[^a-z0-9]+", "-", str(_row["subject"]).lower()).strip("-")[:60] or "campaign"
                st.download_button(
                    "⬇️ Download creative (.html)" if _is_html else "⬇️ Download copy (.txt)",
                    _body.encode("utf-8"),
                    file_name=f"{_slug}.{'html' if _is_html else 'txt'}",
                    mime="text/html" if _is_html else "text/plain",
                    key="dl_creative",
                )
                with st.expander("Preview the creative as sent", expanded=False):
                    if _is_html:
                        import streamlit.components.v1 as _cmp
                        _cmp.html(_body, height=700, scrolling=True)
                    else:
                        st.text(_body)
                st.caption(
                    "The stored copy is the personalised version from one recipient of that "
                    "campaign (tokens like {name} already substituted)."
                )

    # ── Suppression list (always visible, even when no sends yet) ─────────────
    st.markdown("---")
    st.markdown("#### 🚫 Suppression list")
    st.caption(
        "Emails on this list are blocked from sending — used for people who've "
        "asked to be removed, bounced repeatedly, or shouldn't be contacted for "
        "any other reason. Stored in the **Suppressions** tab of the Outreach Log."
    )

    if "supp_df" not in dir():
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
