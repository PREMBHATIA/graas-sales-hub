"""Create Prospect Brief — pre-call research → living account brief.

Wraps the prospect-research-brief Claude skill behind a browser UI so the
team can build + maintain Prospect Briefs without the CLI. Workflow:

  Pre-call: Pick company → paste research → "Build brief" → Claude returns a
  filled HTML brief from the skill's template → preview inline → "Save to
  Drive" creates a native Google Doc in the Graas Pre-Sales folder.

  Post-call: Pick the existing brief → paste call notes → "Update from notes"
  → Claude diffs against the discovery agenda, upgrades confidence on now-
  confirmed facts, resolves conflicts, decides the next step → re-upload to
  the same Doc (history preserved).

The skill (system prompt) lives in content/skills/prospect-research-brief/SKILL.md;
the JSON-schema target shape is defined inline in BRIEF_JSON_SCHEMA below; the
DOCX + HTML renderers live in services/brief_renderer.py.
"""

import os
import re
import sys
import json
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

_env_path = str(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(dotenv_path=_env_path)


# ── Page setup ────────────────────────────────────────────────────────────────
st.markdown("## 📋 Create Prospect Research Brief")
st.caption("Pre-call research → 2-3 page account brief, then a living doc updated after "
           "every call until it's ready for solutioning. Output is a native Google Doc.")

with st.expander("ℹ️ How to use this — read once, then collapse", expanded=False):
    st.markdown("#### What this does")
    st.markdown(
        "Type a company name → Claude **web-researches the company** (website, "
        "LinkedIn, news, filings, funding databases) → produces a **2-3 page "
        "Prospect Brief Google Doc** you can share with the team. The brief tells you:"
    )
    st.markdown(
        "- **What they have** — business model, tech stack, channels, AI maturity (confidence tagged)\n"
        "- **What they're missing** — gap analysis vs. what good looks like for their motion\n"
        "- **Where to probe in discovery** — prioritized question list, not a generic checklist\n"
        "- **Which product to pursue** — All-e, Knowledge Graph, or layered — tied to a CFO metric\n"
        "- **People & path in** — who to engage, the champion, the budget owner"
    )

    st.markdown("#### Two modes")
    m1, m2 = st.columns(2)
    with m1:
        st.markdown("##### 🆕 New brief (pre-call)")
        st.caption("Before the first conversation")
        st.markdown(
            "Paste research notes — website, LinkedIn, news, prior emails, "
            "industry profile. If the company is in the CRM, pick it from "
            "the dropdown and the form pre-fills with what we already know.\n\n"
            "**Output:** auto-saved to Drive on generation — the live Doc link "
            "appears under the preview and on the Recent briefs tile below. "
            "Download as .docx is optional, for a local copy."
        )
    with m2:
        st.markdown("##### 🔁 Update existing (post-call)")
        st.caption("After every call · 4-card wizard guides you through it")
        st.markdown(
            "The wizard takes a prior brief Doc URL + your call notes and "
            "amends the brief in place. Each card validates before the next "
            "one unlocks — no upfront instructions needed."
        )

    st.markdown("#### The living-document workflow")
    st.info(
        "**Pre-call draft → Post call-1 → Post call-2 → … → Ready for solutioning**\n\n"
        "Don't treat this as one-shot. Build it before call 1, then re-open this page "
        "after every call and run the update. The status line at the top of the brief "
        "tracks the version. **You don't need to download/upload between calls — the "
        "Doc updates in place at the same URL.** When the qualification gate is met "
        "(decision-maker known, budget identified, data readiness understood, CFO "
        "metric confirmed by the customer), hand it to the **Create Proposal** page."
    )

    st.markdown("#### What happens after a post-call update")
    st.markdown(
        "- **Same Doc URL** gets updated (Drive keeps the prior version).\n"
        "- A **Post-call analysis** section appears at the top showing what "
        "THIS call added (newest first).\n"
        "- **Rows that changed are highlighted yellow** so you can scan the "
        "brief and see what's new without diffing.\n"
        "- The Recent briefs tile keeps pointing to the same Doc — shared "
        "links don't break."
    )

    st.markdown("#### Tips that change output quality")
    st.markdown(
        "- **Quote your sources** in the research notes "
        "(*\"$290M revenue per Euromonitor; $50-100M per LeadIQ — conflicting\"*). "
        "The brief flags the conflict instead of silently picking one.\n"
        "- **Note what you don't know** (*\"not yet clear if they have a DMS\"*). "
        "The brief turns it into a discovery question.\n"
        "- **Paste call notes verbatim**. Don't pre-summarize — the diff against the "
        "discovery agenda works better with raw notes."
    )

    st.markdown("#### Where the Doc lives")
    st.markdown(
        "**Auto-saved** to the **\"Prospect Brief (via SalesHub)\"** Shared Drive on "
        "every generation — pre-call AND post-call. Override the folder ID in step 4 "
        "for a different destination. The Doc is auto-shared with the emails you list, "
        "so it shows up in their *Shared with me*."
    )
    st.markdown("---")


# ── Anthropic key ─────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
try:
    if hasattr(st, "secrets") and "ANTHROPIC_API_KEY" in st.secrets:
        ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass

if not ANTHROPIC_API_KEY:
    st.warning("Add `ANTHROPIC_API_KEY` to `.streamlit/secrets.toml` or `.env` to enable the brief builder.")
    st.stop()


# ── Load the skill + template ────────────────────────────────────────────────
SKILL_DIR = Path(__file__).parent.parent / "content" / "skills" / "prospect-research-brief"


@st.cache_data(ttl=60)
def load_skill() -> str:
    """Return SKILL.md text as the system prompt. Cached for 60s so edits
    surface quickly after a deploy without a manual restart."""
    skill_md = SKILL_DIR / "SKILL.md"
    if not skill_md.exists():
        return ""
    return skill_md.read_text(encoding="utf-8")


SKILL_TEXT = load_skill()
if not SKILL_TEXT:
    st.error(f"Could not load `SKILL.md` from `{SKILL_DIR}`.")
    st.stop()


# ── Drive folder config ───────────────────────────────────────────────────────
# Default destination: the "Prospect Brief (via SalesHub)" Shared Drive.
# Service accounts can't own files in personal My Drive (0 GB storage quota),
# but they CAN write to Shared Drives where the SA is a Content Manager.
# Override per-session in the UI, or set PROSPECT_BRIEF_DRIVE_FOLDER in env.
DEFAULT_DRIVE_FOLDER = os.getenv(
    "PROSPECT_BRIEF_DRIVE_FOLDER",
    "0ABwowt8s9tmzUk9PVA",  # Shared Drive: Prospect Brief (via SalesHub)
)


# ── CRM context lookup (so picking a known company auto-fills) ────────────────
@st.cache_data(ttl=900)
def load_crm_companies() -> list:
    """Return a list of (display_name, dict) for companies in the All-e pipeline.

    Used for the company picker — type a name and the form pre-fills with
    vertical, region, last conv, and a summary of conversation details.
    """
    sheet_id = os.getenv("ALLE_SHEET_ID", "")
    if not sheet_id:
        return []
    try:
        from services.sheets_client import fetch_sheet_tab
        df = fetch_sheet_tab(sheet_id, "Overall Pipeline for IN and SEA")
        if df.empty or "Lead name" not in df.columns:
            return []
        df = df[df["Lead name"].astype(str).str.strip() != ""]
        out = []
        for _, r in df.iterrows():
            name = str(r["Lead name"]).strip()
            out.append((name, {
                "company": name,
                "vertical": str(r.get("Vertical", "")).strip(),
                "region": str(r.get("Region", "")).strip(),
                "status": str(r.get("Lead status", "")).strip(),
                "active_dropped": str(r.get("Active / Dropped", "")).strip(),
                "first_conv": str(r.get("First conv date", "")).strip(),
                "latest_conv": str(r.get("Latest conv date", "")).strip(),
                "conv_details": str(r.get("Latest Conv details", "")).strip(),
                "comments": str(r.get("Comments", "")).strip(),
                "contacts": str(r.get("Email of Key Personnel ", "")).strip(),
            }))
        return out
    except Exception:
        return []


CRM = load_crm_companies()


# ── Layout: form on left, output on right ─────────────────────────────────────
left, right = st.columns([5, 6])

with left:
    st.markdown("### 1. Mode")
    mode = st.radio(
        " ",
        ["🆕 New brief (pre-call)", "🔁 Update existing (post-call)"],
        key="brief_mode",
        label_visibility="collapsed",
        horizontal=True,
    )

    st.markdown("### 2. Company")
    # Two paths: pick from CRM, OR type any name (overrides the picker).
    # The text_input is always visible — typing into the selectbox just
    # filters its options, so users who want a non-CRM company have to
    # type it explicitly here.
    crm_names = [name for name, _ in CRM]
    selected_company = st.selectbox(
        "Pick a company in the CRM",
        ["— pick from CRM —"] + crm_names,
        key="brief_company_picker",
        help="Picks a known prospect from the All-e pipeline. To use a company not in CRM, leave this on '— pick from CRM —' and type the name in the field below.",
    )
    custom_company = st.text_input(
        "…or type a company not in the CRM",
        key="brief_custom_company",
        placeholder="e.g. Godrej Indonesia",
        help="Overrides the picker above. Use this for any company outside our pipeline.",
    ).strip()

    crm_data = {}
    if custom_company:
        # Custom name wins — no CRM context to fall back on.
        company_name = custom_company
    elif selected_company != "— pick from CRM —":
        crm_data = next((d for n, d in CRM if n == selected_company), {})
        company_name = selected_company
    else:
        company_name = ""

    if crm_data:
        with st.expander(f"📋 CRM context for {selected_company}", expanded=False):
            st.markdown(
                f"**Vertical:** {crm_data.get('vertical') or '—'}  \n"
                f"**Region:** {crm_data.get('region') or '—'}  \n"
                f"**Status:** {crm_data.get('status') or '—'} · {crm_data.get('active_dropped') or '—'}  \n"
                f"**First conv:** {crm_data.get('first_conv') or '—'}  \n"
                f"**Latest conv:** {crm_data.get('latest_conv') or '—'}  \n"
                f"**Last conv details:** {crm_data.get('conv_details') or '—'}  \n"
                f"**Known contacts:** {crm_data.get('contacts') or '—'}"
            )

    st.markdown("### 3. Inputs")

    if mode.startswith("🆕"):
        meeting_date = st.text_input(
            "Meeting date (optional — paste from the calendar invite)",
            key="brief_meeting_date",
            placeholder="e.g. 2026-06-20, or leave blank",
        ).strip()
        attendees_raw = st.text_area(
            "External attendees (optional — names + titles from the invite, one per line)",
            key="brief_attendees",
            height=80,
            placeholder="e.g.\nRavi Kumar — CTO\nPriya Sharma — VP Sales\nAnil Mehta — CFO",
        )
        research_text = st.text_area(
            "Research notes (optional — Claude will web-research the company itself; "
            "paste anything you already have to ground or steer the search: prior emails, "
            "internal context, notes from previous meetings, conflicting figures you've seen)",
            key="brief_research_text",
            height=240,
            placeholder="e.g.\n"
                        "- Met VP Sales at retail summit Apr 24 — possible champion\n"
                        "- Heard CFO is sensitive on DSO; recent earnings call mentioned receivables\n"
                        "- Two sources disagree on revenue — flag the conflict\n"
                        "- (Leave blank to let Claude research from public sources)",
        )
        existing_brief_id = ""
        call_notes = ""
    else:
        # ── Post-call wizard — 4 side-by-side cards. Cards 1+2 must be valid
        # before card 3's button enables. Card 4 shows the result after build.
        meeting_date = ""
        attendees_raw = ""
        research_text = ""

        # Live URL validation for card 1 — probe Drive metadata so we can
        # tell the user "we can see it" vs "SA can't read this" vs "not a
        # Doc" without making them guess.
        _pc_url = st.session_state.get("brief_existing_id", "")
        _pc_url_status = ("⏳", "Paste the prior brief's Doc URL above")
        _pc_doc_title = ""
        if _pc_url.strip():
            _m = re.search(r"/d(?:ocument)?/d?/?([A-Za-z0-9_-]{20,})", _pc_url)
            _did = _m.group(1) if _m else (_pc_url.strip() if re.match(r"^[A-Za-z0-9_-]{20,}$", _pc_url.strip()) else "")
            if not _did:
                _pc_url_status = ("❌", "Couldn't parse a Doc ID from that URL")
            else:
                try:
                    import google.auth.transport.requests as _greq
                    from services.sheets_client import _get_drive_credentials
                    _sess = _greq.AuthorizedSession(_get_drive_credentials())
                    _resp = _sess.get(
                        f"https://www.googleapis.com/drive/v3/files/{_did}"
                        "?fields=name,mimeType&supportsAllDrives=true",
                        timeout=10,
                    )
                    if _resp.status_code == 200:
                        _meta = _resp.json()
                        _pc_doc_title = _meta.get("name", "(no name)")
                        _pc_url_status = ("✅", _pc_doc_title)
                    else:
                        _pc_url_status = ("❌", f"SA can't read this file (HTTP {_resp.status_code})")
                except Exception as _e:
                    _pc_url_status = ("❌", f"Fetch failed: {type(_e).__name__}")

        _card1_valid = _pc_url_status[0] == "✅"
        _pc_notes = st.session_state.get("brief_call_notes", "")
        _card2_valid = len(_pc_notes.strip()) >= 30
        _ready = _card1_valid and _card2_valid

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            with st.container(border=True):
                _b = "✅" if _card1_valid else ("❌" if _pc_url.strip() else "1.")
                st.markdown(f"**{_b} Prior brief**")
                st.caption("Paste the URL of the previous version")
                st.text_input(
                    "Doc URL",
                    key="brief_existing_id",
                    label_visibility="collapsed",
                    placeholder="docs.google.com/document/d/…",
                )
                st.caption(f"{_pc_url_status[0]} {_pc_url_status[1]}")
        with c2:
            with st.container(border=True):
                _b = "✅" if _card2_valid else "2."
                st.markdown(f"**{_b} Call notes**")
                st.caption("Granola / Zoom export, or paste your own")
                st.text_area(
                    "Notes",
                    key="brief_call_notes",
                    label_visibility="collapsed",
                    height=200,
                    placeholder="Paste raw notes — don't pre-summarise",
                )
                _msg = (f"✅ {len(_pc_notes.strip())} chars" if _card2_valid
                        else f"⏳ {len(_pc_notes.strip())} chars (need ≥30)")
                st.caption(_msg)
        with c3:
            with st.container(border=True):
                _b = "▶️" if _ready else "🔒"
                st.markdown(f"**{_b} Update brief**")
                st.caption("Folds the notes into the existing brief")
                build_clicked = st.button(
                    "Update brief",
                    type="primary",
                    use_container_width=True,
                    key="brief_pc_build_btn",
                    disabled=not _ready,
                )
                if _ready:
                    st.caption("✅ Ready to build")
                elif _card1_valid:
                    st.caption("🔒 Need call notes (card 2)")
                elif _card2_valid:
                    st.caption("🔒 Need a valid Doc URL (card 1)")
                else:
                    st.caption("🔒 Fill cards 1 + 2")
        with c4:
            with st.container(border=True):
                _autosave = st.session_state.get("last_brief_autosave_status")
                _done = bool(_autosave and _autosave[0] in ("updated", "created"))
                _b = "✅" if _done else "📥"
                st.markdown(f"**{_b} Done**")
                st.caption("Open + share")
                if _done:
                    _, _url = _autosave
                    st.markdown(f"[Open updated Doc →]({_url})")
                    _trashed_n = st.session_state.get("last_brief_trashed_count", 0)
                    if _trashed_n:
                        st.caption(f"🧹 Trashed {_trashed_n} older")
                else:
                    st.caption("⏳ Run step 3 to populate")

        # Mirror wizard state into the var names the downstream generation
        # code expects (existing_brief_id, call_notes, build_clicked).
        existing_brief_id = _pc_url
        call_notes = _pc_notes

    st.markdown("### 4. Save destination")
    drive_folder = st.text_input(
        "Drive folder ID (defaults to Graas Pre-Sales)",
        value=DEFAULT_DRIVE_FOLDER,
        key="brief_drive_folder",
        help="Paste the ID from a Drive folder URL: docs.google.com/drive/folders/THIS_PART",
    )

    share_with_raw = st.text_input(
        "Share the new Doc with (comma-separated emails — optional)",
        value="prem@graas.ai, amruta@graas.ai",
        key="brief_share_with",
        help="If omitted, only the service account + folder-share inheritance apply.",
    )

    # Pre-call uses a single standalone Build button. Post-call has its own
    # button inside card 3 of the wizard (assigned to `build_clicked` above)
    # and does NOT need a second one here.
    if mode.startswith("🆕"):
        st.markdown("### 5. Action")
        build_clicked = st.button(
            "📝 Build brief",
            type="primary",
            use_container_width=True,
            key="brief_build_btn",
        )


# ── Helpers ───────────────────────────────────────────────────────────────────
def _extract_doc_id(input_str: str) -> str:
    """Pull a Drive doc ID out of a URL or accept a bare ID."""
    s = (input_str or "").strip()
    if not s:
        return ""
    m = re.search(r"/document/d/([A-Za-z0-9_-]+)", s)
    if m:
        return m.group(1)
    m = re.search(r"/d/([A-Za-z0-9_-]+)", s)
    if m:
        return m.group(1)
    # Already an ID
    if re.match(r"^[A-Za-z0-9_-]{20,}$", s):
        return s
    return ""


# JSON schema we ask Claude to fill — keep this string version in sync with
# services/brief_renderer.py (both render_brief_docx and render_brief_html).
BRIEF_JSON_SCHEMA = """{
  "company": "string — display name",
  "header": {
    "date_prepared": "YYYY-MM-DD",
    "meeting_date": "YYYY-MM-DD or 'TBC'",
    "market": "India / Indonesia / Vietnam / Thailand / Philippines / Malaysia / Singapore — primary",
    "status": "Pre-call draft  (post-call: 'Pre-call draft → Post call-1 — YYYY-MM-DD …')"
  },
  "_changed_rows": {
    "DESCRIPTION": "Post-call only — populate during update mode; leave as {} (empty object) for pre-call drafts. Maps each table-section name to the array of row indices (0-based) that were changed/added by THIS call. Used by the renderer to apply YELLOW row-highlighting so the salesperson can scan the brief and see at-a-glance what's new without diffing against a prior Doc version.",
    "what_they_have": [0, 3],
    "asset_graas_map": [],
    "persona_map": [],
    "pain_capability_cfo": [2],
    "graas_proof_points": [],
    "people_path_in": [1],
    "meeting_game_plan": [],
    "objection_handling": []
  },
  "post_call_log": [
    {
      "call_number": "integer — 1 for the first post-call update, 2 for the second, etc. Pre-call drafts leave this entire array empty.",
      "date": "YYYY-MM-DD of THIS call",
      "what_we_learned": "1-2 phrases — the headline outcome of this call. What does the team now know that they didn't before?",
      "now_confirmed": ["facts previously Inferred/Public estimate that this call nailed down. Each item is one phrase."],
      "newly_surfaced": ["new pains / people / systems / competitors / budget signals / agents the call revealed. Each item is one phrase."],
      "still_open": ["open questions from the discovery agenda that this call did NOT answer — they carry forward to the next call."],
      "route_or_next_step_change": "ONE phrase — what shifted in product_route / metric_that_matters / next_step after this call. If nothing shifted, write 'no change'."
    }
  ],
  "strategic_hook": "ONE line, MAX 25 words. The X→Y mapping pitch frame — what they've already built (their assets) → the Graas layer that sits on top. Renders at the top of the brief, sets the meeting frame. e.g. 'You've built KALCare + EMOS + KlikDokter. Graas adds the agentic intelligence layer — without ripping out a single system you run today.' Must reference real assets you found in research.",
  "asset_graas_map": [
    {
      "asset": "Their digital surface name + parenthetical scope. MUST be a real product/platform they own. e.g. 'KALCare / Kalbe Store (B2C omnichannel)', 'KlikDokter (telemedicine + e-pharmacy)', 'EMOS / MOSTRANS (Enseval B2B order + transport)'",
      "what_it_does": "ONE phrase, 8-18 words. What the asset does today, including channels/marketplaces/touchpoints. e.g. 'Official stores on Tokopedia, Shopee, Lazada, Bukalapak, Blibli, JD.id + own webstore'",
      "graas_layer": "ONE phrase, 6-15 words. Which Graas product/layer sits on top. e.g. 'hoppr + Turbo — unify marketplace data, instant analyst' or 'All-e Prescription Intelligence (Tata 1mg pattern)' or 'All-e for Distributors / Retailers / Field Agents'"
    }
  ],
  "executive_summary": {
    "category": "vertical + business model in one line — e.g. 'Industrial gases distributor'",
    "type": "ONE of: 'OEM / Principal / Brand' | 'Multi-brand distributor' | 'Multi-brand retailer'",
    "motion": "ONE of: 'B2B / General Trade' | 'B2C / eCommerce' | 'Both — wedge is ___'",
    "comps": "2-3 named competitors with one-clause positioning — e.g. 'Linde (premium), Aboitiz Power (regional scale), Bharat Petroleum (state-owned challenger)'",
    "history": "founding / trajectory / recent inflection in one line — e.g. 'Founded 1972; family-owned; expanded into specialty gases 2019; now 3rd-largest by volume'",
    "maturity": "AI & systems maturity assessment in one line — e.g. 'Mid: SAP-ERP since 2018, Salesforce CRM, no agents deployed; piloting GenAI for support tickets (2025)'"
  },
  "stat_band": [
    {"label": "Revenue", "value": "ONE concise value, 3-8 words MAX. Just figure + unit + maybe one qualifier. No sources, no parentheticals. e.g. '~IDR 35T FY25', NOT '~IDR 35.3T (~$2.2B USD) FY2025 (Kalbe consolidated, per Yahoo Finance TTM)'"},
    {"label": "SKUs", "value": "3-8 words. e.g. '~1,000+ across 6 therapy classes'"},
    {"label": "Channel touchpoints", "value": "3-8 words. e.g. '>1M outlets · 100+ EMOS users'"},
    {"label": "Field force", "value": "3-8 words. e.g. '~5K Enseval · ~17K Group'"},
    {"label": "Geography", "value": "3-8 words. e.g. 'Indonesia + 71 branches + SEA export'"}
  ],
  "_type_motion_note": "type and motion now live INSIDE executive_summary (above) — they render as boxes in the Exec Summary section. Top-level keys are kept here only for back-compat with existing briefs in session state; do not populate them in new output.",
  "what_they_have": [
    {"dimension": "Business model", "what_we_know": "PHRASE 5-15 words", "confidence": "Confirmed|Public estimate|Inferred|Unknown", "source": "short source"},
    {"dimension": "Scale", "what_we_know": "...", "confidence": "...", "source": "..."},
    {"dimension": "Funding status", "what_we_know": "Listed / PE-backed / VC-funded (round, year, lead) / bootstrapped; profitable or loss-making", "confidence": "...", "source": "..."},
    {"dimension": "Top brands", "what_we_know": "3-5 recognisable brands", "confidence": "...", "source": "..."},
    {"dimension": "Top competitors", "what_we_know": "2-3 competitors", "confidence": "...", "source": "..."},
    {"dimension": "Channel structure", "what_we_know": "HQ → distributors → retailers; counts", "confidence": "...", "source": "..."},
    {"dimension": "Catalogue size / SKU count", "what_we_know": "...", "confidence": "...", "source": "..."},
    {"dimension": "Tech stack", "what_we_know": "ERP / CRM / DMS / SFA / channels — name vendors", "confidence": "...", "source": "..."},
    {"dimension": "External-facing agents", "what_we_know": "agents/chatbots deployed? — the All-e vs KG signal", "confidence": "...", "source": "..."},
    {"dimension": "AI maturity", "what_we_know": "...", "confidence": "...", "source": "..."}
  ],
  "recent_news": ["MAX 2 bullets, the most material events in the last 12 months. With inline citation."],
  "what_missing": ["Gap phrased as a question or honest gap statement.", "..."],
  "product_route": "All-e / Knowledge Graph / Layered — 2-3 lines on why this follows from motion + signals; name wedge vs expansion.",
  "_persona_map_REMOVED": "The persona_map field is DEPRECATED — do not output it. Its content overlapped heavily with pain_capability_cfo (the operational pains) and asset_graas_map (the digital surfaces it covered). The leak-point detail per persona now lives inline in pain_capability_cfo where it belongs.",
  "pain_capability_cfo": [
    {"pain": "pain in their language", "capability": "All-e/KG capability", "metric": "DSO / revenue per rep / cost per order / ..."}
  ],
  "_pain_capability_cfo_CAP": "HARD CAP: 3 rows MAX. Pick the three highest-value pains. More rows dilute the pitch.",
  "metric_that_matters": "The metric this moves for [CFO or decision-maker name, role] is [single literal metric].",
  "discovery_must_haves": [
    "5 questions — operational only (flows, metrics, integrations, budgets). These run FIRST at the meeting and must not be dropped. e.g. 'Walk me through one order end-to-end', 'Who owns the budget for a digital pilot?', 'Current conversion rate + AOV on the live channel?'",
    "...", "...", "...", "..."
  ],
  "discovery_nice_to_haves": [
    "5 questions — operational, asked only if time permits. Same rules as must-haves.",
    "...", "...", "...", "..."
  ],
  "_discovery_RULES": "BOTH lists are EXACTLY 5 entries each (10 total). OPERATIONAL questions only — never ask about an attendee's role/background (that's already in people_path_in as 'Unknown' which IS the ask). Each question ≤20 words. Drop anything generic or already-confirmed elsewhere in the brief.",
  "people_path_in": [
    {"name": "...", "role": "...", "why_matter": "1-line relevance", "type": "Decision-maker | Champion | Finance buyer | Meeting attendee", "linkedin": "ONE optional line (background + prior companies). Omit field if no useful info.", "lead_with": "ONE phrase, 8-20 words — for THIS person specifically, which product/section to lead with and ONE reason grounded in their LinkedIn signal. e.g. 'Lead with hoppr + cite SOC2/PDPA up front — he's a Certified Ethical Hacker.' Only populate for meeting attendees; omit field for non-attendees."}
  ],
  "why_now": [
    "2-4 phrases — the macro / regulatory / segment-momentum reasons this prospect should act NOW (not in 6 months). e.g. 'IDR depreciation + softer consumer = 2026 is an efficiency year, not a growth year — hoppr/All-e attack cost-to-serve directly.'",
    "'Health Law 17/2023 mandates pharmacy distribution digitalisation — EMOS is their response; Graas accelerates the mandate.'",
    "'Distribution +21% YoY is their fastest-growing segment — the segment most exposed to manual ordering leakage.'"
  ],
  "meeting_game_plan": [
    {"minute": "0-5", "segment": "Open on their growth signal", "talking_point": "Lead with the sharpest data point or quote — e.g. 'Distribution is +21% YoY in a tough macro — that's where intelligence pays back fastest.' Name the attendee who'll resonate most."},
    {"minute": "5-15", "segment": "Asset map / strategic frame", "talking_point": "Walk the asset_graas_map: 'You've built X + Y + Z. Graas adds the layer on top — without ripping anything out.' (lead attendee name)"},
    {"minute": "15-30", "segment": "Product-fit-1 + proof point", "talking_point": "Deep on the first Graas product fit, with the relevant graas_proof_points customer as proof. (lead attendee name)"},
    {"minute": "30-45", "segment": "Product-fit-2 + proof point", "talking_point": "Second product fit, second proof point. (lead attendee name)"},
    {"minute": "45-55", "segment": "Discovery + objection handle", "talking_point": "Run 3-5 of the sharpest discovery questions live; anticipate top 1-2 objections from objection_handling."},
    {"minute": "55-60", "segment": "Close on next step", "talking_point": "Propose the next_step.action explicitly, name a follow-up date."}
  ],
  "graas_proof_points": [
    {
      "customer": "Customer name + 1-3 word context. MUST be from the KNOWN GRAAS WINS list in the prompt — do NOT invent customers. e.g. 'Tata 1mg (e-pharmacy)' or 'PI Industries (ag inputs)'",
      "result": "ONE phrase, 6-15 words. The measurable outcome with figures. e.g. '78% prescription→product accuracy; cart time 4-6 min → <2 min'",
      "applies_here": "ONE phrase, 8-18 words. WHY this win is relevant for THIS prospect specifically — tie it to one of their assets or pains. e.g. 'Drop-in for KlikDokter — same telemedicine + e-pharmacy pattern, PDP-Law compliant'"
    }
  ],
  "objection_handling": [
    {"objection": "likely objection in their words, e.g. 'We already built EMOS / KALCare / KlikDokter.'", "response": "Graas response — 1-2 phrases, lead with the reframe. e.g. 'Exactly why this is low-risk. Graas is the intelligence layer ON TOP — we integrate with your systems of record, we don't replace them.'"}
  ],
  "entry_wedge": "lowest-friction way in",
  "next_step": {"action": "another discovery call | demo | POC scoping | solutioning | park", "why": "one-line rationale", "gate_met": false, "still_open": "what's missing (motion / route / customer-confirmed CFO metric / data / DM)"},
  "opening_hook": "one or two lines grounded in their actual numbers — phrase as a question, no quote marks (we add them).",
  "conflicts_unknowns": {
    "conflicting": "conflicting figures, both numbers shown",
    "unverified": "load-bearing unverified facts",
    "key_fact": "the one fact that would most change the recommendation"
  }
}"""


REFERENCE_PROPOSALS_FOLDER_ID = "1tBMrcpiIDVhg5e0-N1ytjuzbDexQyheX"


def _normalize_company_key(name: str) -> str:
    """Reduce a company name to a dedup key that survives common typing
    variations — case, joiner words (and/&/+/x), country suffix, and the
    Indonesian PT…Tbk legal-name wrapper.

    Examples:
      "Kalbe Enseval Indonesia"       → "kalbe enseval"
      "kalbe and enseval indonesia"   → "kalbe enseval"
      "PT Enseval Putera Tbk"         → "enseval putera"
      "Procter & Gamble India"        → "procter gamble"
    """
    if not name:
        return ""
    s = name.lower().strip()
    # Drop Indonesian legal prefix/suffix
    s = re.sub(r"^pt\s+", "", s)
    s = re.sub(r"\s+tbk\s*$", "", s)
    # Drop joiner words between brand tokens
    s = re.sub(r"\s+(and|&|\+|x)\s+", " ", s)
    # Drop trailing country/market suffix (the title's date carries timing)
    s = re.sub(
        r"\s+(india|indonesia|vietnam|thailand|philippines|malaysia|singapore|sea)\s*$",
        "",
        s,
    )
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _resolve_existing_brief_for_company(
    company_name: str, target_folder: str,
) -> tuple:
    """Search target_folder for prior briefs matching this company key,
    then trash all but the latest. Returns (latest_doc_id_or_empty,
    trashed_count). Used by BOTH auto-save AND manual save so the two
    paths cannot create duplicate Docs for the same company.

    Without this shared helper, manual save's CREATE branch was naïve —
    if user clicked it after auto-save had already created a Doc, the
    folder ended up with two Docs for the same company (one orphan).
    """
    from services.sheets_client import list_drive_folder_docs, trash_drive_file
    if not company_name:
        return ("", 0)
    co_key = _normalize_company_key(company_name)
    if not co_key:
        return ("", 0)
    existing = list_drive_folder_docs(target_folder) or []
    matches = []  # modifiedTime-desc
    for d in existing:
        nm = d.get("name", "")
        if not nm.lower().startswith("prospect brief"):
            continue
        m = re.match(
            r"Prospect Brief\s*[—\-]\s*(.+?)\s*[—\-]\s*\d{4}-\d{2}-\d{2}",
            nm,
        )
        if not m:
            continue
        if _normalize_company_key(m.group(1)) == co_key:
            matches.append(d["id"])
    if not matches:
        return ("", 0)
    latest_id = matches[0]
    trashed = 0
    for stale_id in matches[1:]:
        tr = trash_drive_file(stale_id)
        if tr.get("ok"):
            trashed += 1
    return (latest_id, trashed)


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_proof_points_block() -> str:
    """Scan the Reference Proposals folder and build the prompt block listing
    every customer/POC we have a proposal for + a snippet of each.

    This is the SOLE source of truth for graas_proof_points — the bot must
    only cite from this list (no fabricating customers). Cached 1h per
    session to avoid re-scanning on every brief gen.
    """
    from services.sheets_client import list_drive_folder_docs, fetch_drive_doc_text

    docs = list_drive_folder_docs(REFERENCE_PROPOSALS_FOLDER_ID)
    if not docs:
        return ("(No proposals available — graas_proof_points must be left empty. "
                "Do NOT invent customers.)")
    lines = []
    for d in docs:
        title = d["name"].replace("Copy of ", "").strip()
        try:
            body = (fetch_drive_doc_text(d["id"]) or "").strip()
            snippet = " ".join(body.split())[:700]
        except Exception:
            snippet = ""
        lines.append(f"- **{title}** — {snippet}")
    return "\n".join(lines)


def _build_new_brief_prompt(
    crm_data: dict,
    research: str,
    company: str,
    meeting_date: str = "",
    attendees: str = "",
) -> str:
    """Compose the user-turn prompt for a fresh pre-call brief."""
    today = datetime.now().strftime("%Y-%m-%d")
    proof_points_block = _fetch_proof_points_block()
    crm_block = ""
    if crm_data:
        crm_block = (
            "\n[CRM context already known about this company from the Graas pipeline:]\n"
            + json.dumps({k: v for k, v in crm_data.items() if v}, indent=2)
        )

    meeting_block = ""
    if meeting_date or attendees.strip():
        meeting_block = "\n=== MEETING CONTEXT ===\n"
        if meeting_date:
            meeting_block += f"Meeting date: {meeting_date}\n"
        if attendees.strip():
            meeting_block += f"External attendees from the invite (research LinkedIn for each):\n{attendees.strip()}\n"

    return (
        f"Build a pre-call Prospect Research Brief for **{company or '<NAME>'}**.\n"
        f"Today is {today}. Set status = *Pre-call draft*. Header.date_prepared = {today}"
        f"{f'. Header.meeting_date = {meeting_date}' if meeting_date else ''}.\n\n"
        f"**You have the `web_search` tool. Use it.** Before filling the brief, run the "
        f"searches a junior analyst would run: company website + investor pages, recent "
        f"news (last 12 months), LinkedIn for the attendees (when provided), funding "
        f"history (Crunchbase / Tracxn / DealStreetAsia), industry coverage (Economic "
        f"Times, Mint, Reuters, Tech in Asia). Apply the source hierarchy from the skill: "
        f"company filings/website = Confirmed; news = Confirmed for the event reported; "
        f"aggregators (LeadIQ/Lusha/Euromonitor) = Public estimate. Cite sources inline.\n"
        f"Geography: start with India; if the company isn't there, check South East Asia "
        f"and state the actual market in header.market.\n\n"
        f"**Return a single JSON object** matching the schema below. Every cell must be a "
        f"PHRASE, 5-15 words, not a sentence — the rendered brief is a tight 2-pager. "
        f"Compress lists with commas and semicolons. Strip filler ('the company', 'they "
        f"also have', 'is a leading').\n\n"
        f"**STAT BAND CELLS ARE TIGHTER STILL — 3-8 WORDS MAX EACH.** The stat band is a "
        f"header strip, not a paragraph. Put the figure + unit + maybe one qualifier — "
        f"nothing more. Source attribution belongs in the *What they have* ledger's "
        f"Source column, NEVER in stat band cells. Long-form prose in stat band cells "
        f"stretches the table row height in Google Docs and squishes other columns — "
        f"the table renders scrambled. Right: '~IDR 35T FY25'. Wrong: '~IDR 35.3T (~$2.2B "
        f"USD) FY2025 (Kalbe consolidated, per Yahoo Finance TTM); Enseval standalone "
        f"~IDR 33.0T FY2025 (per enseval.com)'. Put the source detail in the ledger "
        f"row instead.\n\n"
        f"**SALES ↔ SOLUTIONING BALANCE.** This is a SALES brief that ALSO "
        f"contains solutioning + discovery — NOT a solutioning doc with a sales "
        f"intro. Target ratio: ~35% sales (strategic_hook, asset_graas_map, "
        f"why_now, graas_proof_points, meeting_game_plan, objection_handling, "
        f"opening_hook, lead_with per attendee) / ~65% solutioning + discovery "
        f"(what_they_have, persona_map, pain_capability_cfo, discovery, "
        f"conflicts_unknowns). Keep solutioning sections DENSE — phrases not "
        f"paragraphs — so the sales sections carry visual weight. A meeting-"
        f"ready brief reads like a play-script, not an analyst report.\n\n"
        f"**STRICT FACT DEDUP — each load-bearing fact appears in EXACTLY ONE "
        f"section.** Other sections REFERENCE it shorthand without restating "
        f"the full fact. The brief's sections are different VIEWS of the same "
        f"underlying data, not copies of it. Examples:\n"
        f"  ✗ BAD: '60% online; in-house OMS; 3 data engineers' appears in "
        f"Exec Summary Maturity AND What they have Scale AND Pain table AND "
        f"Asset map AND People row.\n"
        f"  ✓ GOOD: full fact in ONE section (e.g. What they have Scale row); "
        f"other sections reference shorthand ('the in-house OMS team' or 'the "
        f"60% online split'). Each fact lands once; the reader assembles the "
        f"picture from one place per topic.\n"
        f"Apply this rigorously across asset_graas_map, executive_summary, "
        f"what_they_have, pain_capability_cfo, people_path_in.lead_with, "
        f"meeting_game_plan, and post_call_log.now_confirmed. If you find "
        f"yourself typing the same phrase twice, the second mention should "
        f"be a 3-4 word reference, not a restate.\n\n"
        f"**DISCOVERY IS FORWARD-LOOKING.** discovery_must_haves and "
        f"discovery_nice_to_haves are the agenda for the NEXT call — they "
        f"must NOT include questions that were ALREADY answered. On a post-"
        f"call update: walk through post_call_log[0] (the latest call's) "
        f"now_confirmed list; for each item there, REMOVE the corresponding "
        f"question from the discovery lists. Replace with new questions "
        f"surfaced by this call's newly_surfaced items, or by gaps in the "
        f"new info. Discovery shrinks (answered) AND grows (new gaps) "
        f"between calls — it's never a static restate.\n\n"
        f"**RESEARCH DEPTH RULES — apply these before filling the brief:**\n"
        f"1. **Per-segment / per-division growth.** For any multi-segment / "
        f"multi-division company (pharma w/ Rx+OTC+Nutrition+Distribution; "
        f"conglomerate; multi-vertical group), find revenue + YoY growth PER "
        f"segment. The fastest-growing segment is usually the meeting opener "
        f"(e.g. 'Distribution is your fastest-growing segment +21% YoY' is far "
        f"sharper than 'group revenue +8%'). Surface this in the Scale row of "
        f"what_they_have AND in the opening_hook.\n"
        f"2. **Enumerate ALL digital surfaces.** Pharma / distribution / retail "
        f"prospects usually run 3+ digital products: B2C eCom (their own store + "
        f"each marketplace presence), B2B ordering platforms, telemedicine/health "
        f"apps, DTC web, mobile apps, field-force apps, marketplace seller "
        f"centres. Don't stop at one or two. Each digital surface is a potential "
        f"Graas entry point and MUST be enumerated in asset_graas_map.\n\n"
        f"**AVAILABLE GRAAS PROOF POINTS — STRICT RULE.** You may cite ONLY "
        f"customers/POCs from the list below (these are the proposals we have on "
        f"file in the Reference Proposals folder — every name + outcome here is "
        f"verified). NEVER invent or guess customer names, results, or figures. "
        f"If a fact about a customer isn't in the snippet below, do not state "
        f"it. If no proposal maps cleanly to this prospect's pains, leave "
        f"graas_proof_points empty — better than fabricating. 'Working with' "
        f"includes POCs and pilots, not just live customers.\n\n"
        f"{proof_points_block}\n\n"
        f"**DO NOT DROP MANDATORY FIELDS.** Every brief must include: "
        f"strategic_hook (one-line X→Y frame at the top — what they've already "
        f"built mapped to the Graas layer that sits on top; MUST reference real "
        f"assets surfaced in research, not generic claims), "
        f"asset_graas_map (enumerate ALL their digital surfaces — 3+ rows "
        f"typical — each mapped to the Graas layer that fits; this is the "
        f"structured unpack of strategic_hook), "
        f"why_now (2-4 phrases on macro/regulatory/segment-momentum reasons "
        f"this prospect should act THIS quarter, not later — sales weight), "
        f"graas_proof_points (2-4 entries chosen from AVAILABLE GRAAS PROOF "
        f"POINTS list above, each tied to one of this prospect's assets or "
        f"pains; NEVER fabricate — leave empty if no proposal maps cleanly), "
        f"meeting_game_plan (6-row minute-by-minute run-sheet for the meeting, "
        f"each row naming the lead attendee and a concrete talking point — "
        f"sales weight), "
        f"executive_summary (6 fields rendered as two stacked box rows: "
        f"category/type/motion on row 1, comps/history/maturity on row 2 — NOT a "
        f"paragraph, NOT labelled lines), stat_band (all 5), what_they_have (all 10 dimensions: "
        f"Business model · Scale · Funding status · Top brands · Top competitors · "
        f"Channel structure · Catalogue size / SKU count · Tech stack · External-facing "
        f"agents · AI maturity), recent_news (**MAX 2 bullets**, the most material; or "
        f"one honest 'Nothing material in the last 12 months from public sources'), "
        f"what_missing, product_route, "
        f"pain_capability_cfo (**MAX 3 rows** — pick the three highest-value pains; "
        f"more rows dilute the pitch), "
        f"metric_that_matters, discovery_must_haves (**EXACTLY 5 questions** — "
        f"operational only, no role-clarification, each ≤20 words), "
        f"discovery_nice_to_haves (**EXACTLY 5 questions** — same rules), "
        f"people_path_in (merge meeting attendees here; use type='Meeting attendee' + "
        f"the optional linkedin field for any attendees the user provided; for each "
        f"Meeting attendee, ALSO populate lead_with — the product/section to lead "
        f"with for that person and ONE reason grounded in their LinkedIn signal), "
        f"objection_handling (**TOP 3 ONLY** — the most likely objections the room "
        f"will raise; responses ≤2 sentences each), entry_wedge, "
        f"meeting_game_plan (**EXACTLY 3 rows** — Open / Pitch / Close — talking "
        f"points ≤1 sentence each; this is a 3-bullet meeting plan, not a 6-row "
        f"minute-by-minute), "
        f"next_step, opening_hook, conflicts_unknowns (appendix at the end — keep it "
        f"terse). If a fact is genuinely not findable, set the value to *\"Info not "
        f"publicly available\"* and confidence to *\"Unknown\"* — **never drop the "
        f"row**.\n\n"
        f"**REMOVED FIELDS (do not include):** order_flow (now rolled into persona_map "
        f"as a column per persona), other_signals (dropped — promote material findings to "
        f"recent_news or what_missing), meeting_attendees (merged into people_path_in "
        f"with type='Meeting attendee'), discovery (the old 4-bucket discovery dict "
        f"has been REPLACED by discovery_must_haves + discovery_nice_to_haves — do "
        f"not output the old `discovery` field), persona_map (REMOVED — its "
        f"operational pain detail now lives in pain_capability_cfo).\n\n"
        f"**APPENDIX LAYOUT NOTE.** The renderer splits the brief into a MAIN section "
        f"(strategic_hook, exec_summary, stat_band, why_now, meeting_game_plan, "
        f"pain_capability_cfo, what_they_have, people_path_in, objection_handling, "
        f"next_step, opening_hook) and an APPENDIX section (asset_graas_map, "
        f"graas_proof_points, discovery_must_haves, "
        f"discovery_nice_to_haves, Meeting Notes (blank for the salesperson), "
        f"recent_news, conflicts_unknowns). You don't control the placement — just "
        f"return the fields; the renderer handles the order.\n\n"
        f"=== INPUTS — INTERNAL RESEARCH / CONTEXT ===\n{research or '(no internal notes pasted — research the company from public sources using web_search)'}\n"
        f"{crm_block}{meeting_block}\n\n"
        f"=== JSON SCHEMA (fill exactly this shape) ===\n{BRIEF_JSON_SCHEMA}\n\n"
        f"Return ONLY the JSON object as your final message. No prose before or after, "
        f"no markdown code fences. Must parse with json.loads()."
    )


def _build_update_prompt(existing_brief_text: str, call_notes: str, company: str) -> str:
    """Compose the user-turn prompt for a post-call update — returns updated JSON."""
    today = datetime.now().strftime("%Y-%m-%d")
    return (
        f"Update the existing Prospect Brief for **{company or '<NAME>'}** with new "
        f"call notes from today ({today}).\n\n"
        f"Diff the notes against the discovery agenda. For each open question:\n"
        f"- Answered → move it into the fact tables, upgrade Confidence to Confirmed, "
        f"strike from the agenda.\n"
        f"- Contradicted → update the fact and flag in Conflicts & Unknowns.\n"
        f"- Unanswered → leave in the agenda for the next call.\n"
        f"Capture anything new the call surfaced (pains, people, systems, agents, "
        f"competitors, budget/timeline).\n\n"
        f"Re-check the product route — new info may shift All-e ↔ KG or open the "
        f"layered angle. Update the CFO metric if needed.\n\n"
        f"Decide and record the **next_step** explicitly with one line on why.\n\n"
        f"Update header.status: append `→ Post call-N — {today}` where N is the next "
        f"number after the latest. Keep prior status entries intact in the string.\n\n"
        f"**CHANGE TRACKING (critical for highlighting).** Populate the "
        f"`_changed_rows` object with the row indices YOU updated (or added) "
        f"in each table-shaped field as a result of THIS call. Keys: "
        f"what_they_have, asset_graas_map, persona_map, pain_capability_cfo, "
        f"graas_proof_points, people_path_in, meeting_game_plan, "
        f"objection_handling. Values: 0-based arrays of row indices that "
        f"changed. Example: if you upgraded the Scale row (index 1) in "
        f"what_they_have and added a new persona at the end of persona_map "
        f"(now 4 rows total, the new one at index 3), return "
        f"{{'what_they_have': [1], 'persona_map': [3], ...}} (empty arrays "
        f"for tables you didn't touch). The renderer paints those rows yellow "
        f"so the salesperson sees what's new at a glance. Don't be stingy — "
        f"if a row's content shifted in any meaningful way, flag it.\n\n"
        f"**POST-CALL LOG (critical for this update flow).** PREPEND a new entry "
        f"to the `post_call_log` array as the FIRST item (most recent on top). "
        f"PRESERVE every prior entry verbatim — never delete or rewrite old "
        f"entries. The new entry must include: call_number = (highest existing "
        f"call_number + 1, or 1 if empty), date = {today}, what_we_learned "
        f"(1-2 phrases on the call's headline outcome), now_confirmed (facts "
        f"upgraded from Inferred to Confirmed because of this call), "
        f"newly_surfaced (new pains/people/systems/competitors/budget the call "
        f"revealed), still_open (discovery questions the call did NOT answer), "
        f"route_or_next_step_change (one phrase on what shifted in route / "
        f"metric_that_matters / next_step, or 'no change'). This section is "
        f"what the salesperson reads first when re-opening the brief — make it "
        f"crisp and load-bearing.\n\n"
        f"Output rules: same 2-pager density (phrases not sentences); keep all mandatory "
        f"fields populated; if a fact stays unverified use *Info not publicly available* "
        f"+ Unknown.\n\n"
        f"=== NEW CALL NOTES ===\n{call_notes}\n\n"
        f"=== EXISTING BRIEF (plain text export of the Doc) ===\n{existing_brief_text}\n\n"
        f"=== JSON SCHEMA (return exactly this shape) ===\n{BRIEF_JSON_SCHEMA}\n\n"
        f"Return ONLY the updated JSON object. No prose, no code fences. Must parse "
        f"with json.loads()."
    )


def _extract_json_object(text: str) -> dict:
    """Extract the first JSON object from a model response.

    Strips ```json fences, then finds the first `{` and parses from there. Raises
    ValueError with a useful message if no JSON object is found.
    """
    s = (text or "").strip()
    # Strip ```json ... ``` fences if present
    s = re.sub(r"^```(?:json|JSON)?\s*\n", "", s)
    s = re.sub(r"\n```\s*$", "", s)
    s = s.strip()
    start = s.find("{")
    if start < 0:
        raise ValueError("No JSON object found in response")
    # Try to parse from the first `{`; json.loads is strict about trailing content
    try:
        return json.loads(s[start:])
    except json.JSONDecodeError:
        # Fall back to a balanced-brace scan from start
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            c = s[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(s[start:i + 1])
        raise ValueError("Couldn't find a balanced JSON object in response")


# ── Output side ───────────────────────────────────────────────────────────────
with right:
    st.markdown("### Brief Preview")

    # If we have a previously generated brief in this session, show it
    if "last_brief_html" not in st.session_state:
        st.session_state["last_brief_html"] = ""
        st.session_state["last_brief_company"] = ""
        st.session_state["last_brief_mode"] = ""
        st.session_state["last_brief_doc_url"] = ""

    placeholder = st.empty()

    def _render_brief(html: str, company: str, mode_label: str):
        if not html:
            placeholder.info(
                "Fill in the form on the left and click **Build brief** "
                "(or **Update from call notes**). The generated brief renders here."
            )
            return
        placeholder.markdown(
            f"**{company}** — {mode_label}",
            unsafe_allow_html=False,
        )
        # Render the brief in an iframe-style container so its styling doesn't
        # leak into Streamlit's own page styles.
        import streamlit.components.v1 as components
        components.html(html, height=800, scrolling=True)

    # Trigger the build
    if build_clicked:
        if mode.startswith("🆕"):
            if not company_name:
                st.error("Pick or type a company name first.")
                st.stop()
            # Web search is enabled, so a bare company name is enough — but warn so
            # the salesperson knows what's about to happen.
            if not crm_data and not research_text.strip():
                st.info(
                    f"**{company_name}** isn't in the CRM and no notes were pasted — "
                    "Claude will research from public sources (website, LinkedIn, news, "
                    "filings). Quality depends on what's publicly findable. Paste any "
                    "internal context next time to ground or steer the search."
                )
            user_prompt = _build_new_brief_prompt(
                crm_data, research_text, company_name,
                meeting_date=meeting_date,
                attendees=attendees_raw,
            )
        else:
            if not company_name:
                st.error("Pick or type a company name first (Card 0 / step 2).")
                st.stop()
            doc_id = _extract_doc_id(existing_brief_id)
            if not doc_id:
                st.error("Paste a valid Google Doc URL or ID for the existing brief.")
                st.stop()
            if not call_notes.strip():
                st.error("Paste the new call notes.")
                st.stop()
            from services.sheets_client import fetch_drive_doc_text
            existing_text = fetch_drive_doc_text(doc_id)
            if not existing_text:
                st.error(f"Could not fetch the existing brief at `{doc_id}`. "
                         f"Check the URL/ID and that the service account has access.")
                st.stop()
            user_prompt = _build_update_prompt(existing_text, call_notes, company_name or "<this prospect>")

        # Call Claude with streaming so we can surface every web search + draft step
        # live. For "new brief" we hand Claude the web_search tool; for "update from
        # notes" we don't (existing brief + new notes are the source of truth).
        status_label = (
            f"Researching **{company_name}** on the web…"
            if mode.startswith("🆕")
            else "Diffing call notes against the discovery agenda…"
        )
        status_box = st.status(status_label, expanded=True)
        try:
            import anthropic
            import json as _json
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            system_prompt = SKILL_TEXT
            kwargs = dict(
                model="claude-sonnet-4-6",
                # Brief expanded to ~12 mandatory sections (game plan, asset map,
                # proof points, etc.) — at 8K Claude was hitting max_tokens
                # mid-JSON, leaving the parser with just an opening "{".
                max_tokens=16000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            if mode.startswith("🆕"):
                kwargs["tools"] = [{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 10,
                }]

            # Activity log inside the status box. Lines are stored as HTML so we can
            # wrap them in a small-font div for a tighter visual footprint.
            activity_lines: list = []
            search_count = 0
            source_count = 0
            text_chars = 0
            import html as _html

            with status_box:
                activity_box = st.empty()

                def _render_activity():
                    body = "<br>".join(activity_lines) if activity_lines else "<i>Connecting to Claude…</i>"
                    activity_box.markdown(
                        f"<div style='font-size: 0.78em; line-height: 1.4; color: #444; "
                        f"font-family: ui-monospace, SFMono-Regular, Menlo, monospace;'>"
                        f"{body}</div>",
                        unsafe_allow_html=True,
                    )

                def _push(line: str):
                    activity_lines.append(line)
                    _render_activity()

                def _replace_last(line: str):
                    if activity_lines:
                        activity_lines[-1] = line
                    else:
                        activity_lines.append(line)
                    _render_activity()

                _render_activity()
                with client.messages.stream(**kwargs) as stream:
                    pending_input_json = ""
                    for event in stream:
                        etype = getattr(event, "type", None)
                        if etype == "content_block_start":
                            block = getattr(event, "content_block", None)
                            btype = getattr(block, "type", "")
                            if btype == "server_tool_use" and getattr(block, "name", "") == "web_search":
                                pending_input_json = ""
                                search_count += 1
                                _push(f"🔍 <b>Search #{search_count}</b> — preparing query…")
                            elif btype == "web_search_tool_result":
                                # block.content is the list of results
                                results = getattr(block, "content", None) or []
                                if not isinstance(results, list):
                                    results = []
                                source_count += len(results)
                                if results:
                                    last = activity_lines[-1] if activity_lines else f"🔍 <b>Search #{search_count}</b>"
                                    last = last.replace(" — preparing query…", "")
                                    _replace_last(f"{last} → <b>{len(results)}</b> result(s)")
                                    for r in results[:4]:
                                        title = (getattr(r, "title", None) or "")[:90]
                                        url = getattr(r, "url", None) or ""
                                        if title or url:
                                            disp = _html.escape(title or url)
                                            safe_url = _html.escape(url, quote=True)
                                            if url:
                                                activity_lines.append(f"&nbsp;&nbsp;&nbsp;· <a href='{safe_url}' target='_blank' style='color:#666; text-decoration:none;'>{disp}</a>")
                                            else:
                                                activity_lines.append(f"&nbsp;&nbsp;&nbsp;· {disp}")
                                    if len(results) > 4:
                                        activity_lines.append(f"&nbsp;&nbsp;&nbsp;· +{len(results) - 4} more")
                                    _render_activity()
                                else:
                                    _replace_last(activity_lines[-1] + " → no results")
                            elif btype == "text":
                                _push("✏️ <b>Drafting the brief…</b>")
                        elif etype == "content_block_delta":
                            delta = getattr(event, "delta", None)
                            dtype = getattr(delta, "type", None)
                            if dtype == "input_json_delta":
                                # Accumulate partial JSON until it parses, then show the query
                                pending_input_json += getattr(delta, "partial_json", "") or ""
                                try:
                                    parsed = _json.loads(pending_input_json)
                                    q = parsed.get("query", "")
                                    if q and activity_lines and activity_lines[-1].startswith(f"🔍 <b>Search #{search_count}</b>"):
                                        safe_q = _html.escape(q)
                                        _replace_last(f"🔍 <b>Search #{search_count}</b> — \"{safe_q}\"")
                                except Exception:
                                    pass
                            elif dtype == "text_delta":
                                text_chars += len(getattr(delta, "text", "") or "")
                                # Lightly tick the drafting line every ~500 chars
                                if text_chars and text_chars % 500 < 20 and activity_lines:
                                    if activity_lines[-1].startswith("✏️"):
                                        _replace_last(f"✏️ <b>Drafting the brief…</b> ({text_chars:,} chars)")

                    final_message = stream.get_final_message()

            # Multi-block final: extract text blocks only
            text_parts = []
            for block in final_message.content:
                if getattr(block, "type", None) == "text":
                    text_parts.append(block.text)
            raw_text = "\n".join(p for p in text_parts if p).strip()

            if not raw_text:
                status_box.update(label="❌ No brief returned", state="error", expanded=True)
                st.error(
                    "Claude returned no text — only tool calls. This usually means the "
                    "model burned all its budget on web search and ran out of tokens. "
                    "Try again, or paste some research notes to reduce the search scope."
                )
                st.stop()

            summary = []
            if search_count:
                summary.append(f"{search_count} search(es)")
            if source_count:
                summary.append(f"{source_count} source(s)")
            if text_chars:
                summary.append(f"{text_chars:,} chars drafted")
            status_box.update(
                label="✅ Brief ready" + (f" — {' · '.join(summary)}" if summary else ""),
                state="complete",
                expanded=False,
            )

            # Parse JSON, render HTML for preview + DOCX for save
            try:
                brief_data = _extract_json_object(raw_text)
            except Exception as parse_err:
                status_box.update(label="❌ Couldn't parse JSON", state="error", expanded=True)
                stop_reason = getattr(final_message, "stop_reason", "unknown")
                hint = ""
                if stop_reason == "max_tokens":
                    hint = (
                        "\n\n**Diagnosis:** Claude hit `max_tokens` mid-JSON — "
                        "the response was cut off before the closing brace. "
                        "Bump `max_tokens` in the API call or trim the brief schema."
                    )
                elif stop_reason == "end_turn":
                    hint = (
                        "\n\n**Diagnosis:** Claude finished cleanly but wrapped "
                        "the JSON in commentary. Tighten the 'JSON ONLY' "
                        "instruction at the end of the prompt."
                    )
                st.error(
                    "Claude didn't return valid JSON. This usually means the model "
                    "wrapped the response in commentary or got cut off mid-output.\n\n"
                    f"**Parse error:** {parse_err}\n\n"
                    f"**Stop reason:** `{stop_reason}` · **Output length:** "
                    f"{len(raw_text):,} chars"
                    f"{hint}\n\n"
                    f"**First 1500 chars of response:**\n\n{raw_text[:1500]}"
                )
                st.stop()

            # Sanity-check mandatory fields are populated
            required_keys = ["strategic_hook", "asset_graas_map", "why_now",
                             "executive_summary", "stat_band", "what_they_have",
                             "product_route", "graas_proof_points",
                             "pain_capability_cfo", "meeting_game_plan",
                             "objection_handling", "opening_hook",
                             "discovery_must_haves", "discovery_nice_to_haves"]
            # Post-call updates MUST surface what the call added. Without a
            # populated post_call_log, the brief renders as a "looks like a
            # pre-call draft" which is the exact silent-failure we hit earlier.
            if mode.startswith("🔁"):
                required_keys.append("post_call_log")
            missing_required = [k for k in required_keys if not brief_data.get(k)]
            if missing_required:
                st.warning(
                    "Brief generated but missing required fields: "
                    f"`{', '.join(missing_required)}`. The Doc will still render — "
                    "consider regenerating with more research notes."
                )

            from services.brief_renderer import render_brief_html, render_brief_docx
            try:
                brief_html = render_brief_html(brief_data)
                brief_docx = render_brief_docx(brief_data)
            except Exception as render_err:
                status_box.update(label="❌ Render failed", state="error", expanded=True)
                st.error(
                    "Got valid JSON but the renderer choked on it. This is usually a "
                    "schema mismatch (a field shape Claude returned isn't what we "
                    f"expect).\n\n**Error:** {render_err}"
                )
                st.stop()

            st.session_state["last_brief_data"] = brief_data
            st.session_state["last_brief_html"] = brief_html
            st.session_state["last_brief_docx"] = brief_docx
            st.session_state["last_brief_company"] = company_name
            st.session_state["last_brief_mode"] = ("Pre-call draft" if mode.startswith("🆕") else f"Post-call update — {datetime.now():%Y-%m-%d}")
            if mode.startswith("🔁"):
                st.session_state["last_brief_doc_id"] = _extract_doc_id(existing_brief_id)
            else:
                st.session_state["last_brief_doc_id"] = ""
            st.session_state["last_brief_doc_url"] = ""

            def _write_brief_link_to_pipeline(co_name, doc_url, mode, date_s):
                """Best-effort write of the brief link into the pipeline
                sheet's SalesHub Brief column. Failures are surfaced as a
                small caption — never blocks the user flow."""
                try:
                    from services.sheets_client import upsert_brief_link_into_pipeline
                    _r = upsert_brief_link_into_pipeline(
                        company_name=co_name, doc_url=doc_url,
                        mode=mode, date_str=date_s,
                    )
                    if _r.get("ok") and _r.get("rows_updated"):
                        st.session_state["last_pipeline_writeback"] = (
                            "ok", _r["rows_updated"],
                        )
                    elif _r.get("ok"):
                        st.session_state["last_pipeline_writeback"] = (
                            "nomatch", co_name,
                        )
                    else:
                        st.session_state["last_pipeline_writeback"] = (
                            "fail", _r.get("error", "unknown"),
                        )
                except Exception as _e:
                    st.session_state["last_pipeline_writeback"] = (
                        "fail", f"{type(_e).__name__}: {_e}",
                    )

            # ── Auto-save to Drive ──────────────────────────────────────────
            # The "last generated brief for each customer" should land on the
            # Recent briefs tile (and the Doc) without a separate click. We
            # look up any existing brief for this company in the target
            # folder; if found → update in place (URL + version history
            # preserved); else → create new.
            try:
                from services.sheets_client import (
                    create_google_doc_from_docx,
                    update_google_doc_docx,
                    list_drive_folder_docs,
                )
                target_folder = drive_folder or DEFAULT_DRIVE_FOLDER
                existing_doc_id = ""

                # Shared dedup-and-trash helper. Always pick the latest
                # SalesHub match for this company; trash older duplicates
                # so only one brief per customer survives.
                _latest_id, _trashed_n = _resolve_existing_brief_for_company(
                    company_name, target_folder,
                )
                if _trashed_n:
                    st.session_state["last_brief_trashed_count"] = _trashed_n

                if mode.startswith("🔁"):
                    # Post-call: prefer the user-pasted source — but only if
                    # it's a native Google Doc AND in the SalesHub Shared
                    # Drive (so the update is visible in tiles). Else fall
                    # back to the latest SalesHub match (or CREATE if none).
                    _src_id = st.session_state.get("last_brief_doc_id", "")
                    if _src_id:
                        import google.auth.transport.requests as _greq
                        from services.sheets_client import _get_drive_credentials
                        try:
                            _sess = _greq.AuthorizedSession(_get_drive_credentials())
                            _meta = _sess.get(
                                f"https://www.googleapis.com/drive/v3/files/{_src_id}"
                                "?fields=mimeType,driveId,parents&supportsAllDrives=true",
                                timeout=15,
                            ).json() or {}
                            _is_native_doc = (
                                _meta.get("mimeType") ==
                                "application/vnd.google-apps.document"
                            )
                            _in_saleshub = (
                                _meta.get("driveId") == DEFAULT_DRIVE_FOLDER
                                or target_folder in (_meta.get("parents") or [])
                            )
                            if _is_native_doc and _in_saleshub:
                                existing_doc_id = _src_id
                        except Exception:
                            pass

                # If we still don't have a target (pre-call OR post-call
                # where source was external), take the latest SalesHub match.
                if not existing_doc_id and _latest_id:
                    existing_doc_id = _latest_id

                # Compute the brief mode + call count for stamping into Drive
                # appProperties — tile renderer reads these to colour pre-call
                # vs post-call differently.
                _pcl = brief_data.get("post_call_log") or []
                _call_count = len(_pcl) if isinstance(_pcl, list) else 0
                _brief_mode = (f"Post call-{_call_count}" if _call_count > 0
                               else "Pre-call draft")
                _props = {
                    "brief_mode": _brief_mode,
                    "brief_call_count": _call_count,
                    "brief_company_key": _co_key,
                }

                # Compute the expected title up front — used both when
                # CREATING new (line below) and when UPDATING an existing
                # doc whose title may be stale (e.g. blank company from an
                # early aborted Build).
                _expected_title = (
                    f"Prospect Brief — {company_name} — "
                    f"{datetime.now():%Y-%m-%d}"
                )

                if existing_doc_id:
                    _res = update_google_doc_docx(
                        existing_doc_id, brief_docx,
                        new_title=_expected_title,
                    )
                    if _res.get("ok"):
                        _url = f"https://docs.google.com/document/d/{existing_doc_id}/edit"
                        st.session_state["last_brief_doc_id"] = existing_doc_id
                        st.session_state["last_brief_doc_url"] = _url
                        st.session_state["last_brief_autosave_status"] = (
                            "updated", _url
                        )
                        from services.sheets_client import set_drive_app_properties
                        set_drive_app_properties(existing_doc_id, _props)
                        _write_brief_link_to_pipeline(
                            company_name, _url, _brief_mode,
                            f"{datetime.now():%Y-%m-%d}",
                        )
                else:
                    _res = create_google_doc_from_docx(
                        docx_bytes=brief_docx,
                        title=_expected_title,
                        parent_folder_id=target_folder,
                        share_with=None,
                    )
                    if _res.get("ok"):
                        _new_id = _res.get("doc_id", "")
                        st.session_state["last_brief_doc_id"] = _new_id
                        st.session_state["last_brief_doc_url"] = _res.get("doc_url", "")
                        st.session_state["last_brief_autosave_status"] = (
                            "created", _res.get("doc_url", "")
                        )
                        if _new_id:
                            from services.sheets_client import set_drive_app_properties
                            set_drive_app_properties(_new_id, _props)
                            _write_brief_link_to_pipeline(
                                company_name, _res.get("doc_url", ""),
                                _brief_mode, f"{datetime.now():%Y-%m-%d}",
                            )
                    else:
                        st.session_state["last_brief_autosave_status"] = (
                            "failed", _res.get("error") or "unknown error"
                        )
                # Bust the Recent-briefs tile cache so the new/updated doc
                # appears immediately on the page below. The function is
                # defined further down the script, so on the first rerun
                # where this branch fires, it won't be in this scope yet —
                # st.cache_data.clear() invalidates all caches as a fallback.
                try:
                    _list_recent_briefs.clear()
                except NameError:
                    st.cache_data.clear()
            except Exception as _save_err:
                st.session_state["last_brief_autosave_status"] = (
                    "failed", str(_save_err)
                )

            _should_rerun = True
        except Exception as e:
            # Streamlit's flow-control exceptions (RerunException, StopException) must
            # propagate, not get masked as a "generation failed" error.
            if type(e).__name__ in ("RerunException", "StopException"):
                raise
            try:
                status_box.update(label="❌ Generation failed", state="error", expanded=True)
            except Exception:
                pass
            st.error(f"Brief generation failed: {e}")
            _should_rerun = False

        if locals().get("_should_rerun"):
            st.rerun()

    # Render whatever's in session state
    _render_brief(
        st.session_state["last_brief_html"],
        st.session_state["last_brief_company"],
        st.session_state["last_brief_mode"],
    )

    # ── Save / Export actions ────────────────────────────────────────────────
    if st.session_state["last_brief_html"]:
        st.markdown("---")
        st.markdown("### Save")

        # Surface the auto-save status that ran during generation. The
        # brief lands in Drive (and on the Recent briefs tile) without a
        # click. After success, the manual save button is demoted into
        # an expander — it's only needed for the rare re-render-after-
        # code-fix workflow. On failure, it surfaces as the primary CTA.
        _autosave = st.session_state.get("last_brief_autosave_status")
        _autosave_ok = bool(_autosave and _autosave[0] in ("updated", "created"))
        if _autosave:
            _kind, _payload = _autosave
            _trashed_n = st.session_state.get("last_brief_trashed_count", 0)
            _trashed_suffix = (
                f" · trashed {_trashed_n} older duplicate" + ("s" if _trashed_n != 1 else "")
                if _trashed_n else ""
            )
            if _kind == "updated":
                st.success(f"✅ Auto-updated existing Doc in Drive. [Open it →]({_payload}){_trashed_suffix}")
            elif _kind == "created":
                st.success(f"✅ Auto-saved new Doc to Drive. [Open it →]({_payload}){_trashed_suffix}")
            elif _kind == "failed":
                st.warning(
                    f"⚠️ Auto-save to Drive failed: {_payload}. "
                    f"Use the manual save below."
                )

        # Pipeline-sheet write-back status (a small caption — best-effort,
        # not load-bearing; salesperson can ignore if it didn't match)
        _pw = st.session_state.get("last_pipeline_writeback")
        if _pw:
            _pkind, _ppayload = _pw
            if _pkind == "ok":
                st.caption(f"🔗 Pipeline sheet updated · {_ppayload} row(s)")
            elif _pkind == "nomatch":
                st.caption(
                    f"ℹ️ No pipeline-sheet row matched **{_ppayload}** "
                    f"— add a row in 'Overall Pipeline for IN and SEA' to "
                    f"link this brief from the sheet."
                )
            elif _pkind == "fail":
                st.caption(f"⚠️ Pipeline sheet write-back failed: {_ppayload}")

        # Primary actions row: Download + Clear (always visible).
        # Manual save lives below — prominent on auto-save failure,
        # demoted into an expander on success.
        _dl_col, _clear_col = st.columns([3, 1])
        with _dl_col:
            fname = f"prospect-brief-{(st.session_state['last_brief_company'] or 'untitled').lower().replace(' ', '-')}-{datetime.now():%Y-%m-%d}.docx"
            st.download_button(
                "⬇️ Download DOCX",
                data=st.session_state.get("last_brief_docx", b""),
                file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        with _clear_col:
            if st.button("🗑 Clear", use_container_width=True, key="brief_clear_btn"):
                for k in ("last_brief_data", "last_brief_html", "last_brief_docx",
                          "last_brief_company", "last_brief_mode",
                          "last_brief_doc_url", "last_brief_doc_id",
                          "last_brief_autosave_status",
                          "last_brief_trashed_count",
                          "last_pipeline_writeback"):
                    st.session_state.pop(k, None)
                st.rerun()

        # Manual save — wrapped in expander when auto-save succeeded
        # (rare-use, mostly for pushing renderer fixes), or rendered
        # directly when auto-save failed (primary recovery action).
        def _manual_save_button():
            _doc_id = st.session_state.get("last_brief_doc_id")
            if _autosave_ok:
                _label = ("🔄 Re-render Doc with latest code"
                          if _doc_id else "💾 Save to Drive again")
            else:
                _label = ("🔁 Re-upload to existing Doc"
                          if _doc_id else "💾 Create new Google Doc")
            return st.button(
                _label,
                type="secondary" if _autosave_ok else "primary",
                use_container_width=True,
                key="brief_save_btn",
            )

        def _run_manual_save():
            """Re-render + upload to Drive. Called from both the expander
            (re-render-after-fix workflow) and the on-failure fallback."""
            with st.spinner("Talking to Drive…"):
                from services.sheets_client import (
                    create_google_doc_from_docx,
                    update_google_doc_docx,
                    set_drive_app_properties as _sap,
                )
                title = (
                    f"Prospect Brief — {st.session_state['last_brief_company']} — "
                    f"{datetime.now():%Y-%m-%d}"
                )
                share_with = [
                    e.strip() for e in (share_with_raw or "").split(",")
                    if e.strip() and "@" in e
                ]
                # Re-render from brief_data so the upload always reflects
                # the current renderer code (avoids stale session bytes).
                _brief_data = st.session_state.get("last_brief_data", {})
                if _brief_data:
                    try:
                        from services.brief_renderer import render_brief_docx as _rrd
                        docx_bytes = _rrd(_brief_data)
                        st.session_state["last_brief_docx"] = docx_bytes
                    except Exception as _rerr:
                        st.warning(
                            f"Re-render failed ({_rerr}) — falling back to "
                            f"session-state bytes."
                        )
                        docx_bytes = st.session_state.get("last_brief_docx", b"")
                else:
                    docx_bytes = st.session_state.get("last_brief_docx", b"")
                if not docx_bytes:
                    st.error("No DOCX bytes in session — regenerate the brief.")
                    st.stop()
                # appProperties for the tile badge
                _pcl_for_props = _brief_data.get("post_call_log") or []
                _cc_for_props = (len(_pcl_for_props) if isinstance(_pcl_for_props, list) else 0)
                _mp = {
                    "brief_mode": (f"Post call-{_cc_for_props}" if _cc_for_props > 0
                                   else "Pre-call draft"),
                    "brief_call_count": _cc_for_props,
                    "brief_company_key": _normalize_company_key(
                        st.session_state.get("last_brief_company", "")
                    ),
                }
                # Pipeline-sheet write-back parameters (best-effort; matches
                # the auto-save behaviour so manual saves stay in sync)
                from services.sheets_client import upsert_brief_link_into_pipeline as _ublp
                _pl_co = st.session_state.get("last_brief_company", "")
                _pl_mode = _mp.get("brief_mode", "Pre-call draft")
                _pl_date = f"{datetime.now():%Y-%m-%d}"

                # Run the SAME dedup-and-trash as auto-save before deciding
                # update vs create. Without this, clicking "Save to Drive
                # again" right after auto-save created a duplicate Doc for
                # the same company.
                _ms_target_folder = drive_folder or DEFAULT_DRIVE_FOLDER
                _ms_latest_id, _ms_trashed_n = _resolve_existing_brief_for_company(
                    _pl_co, _ms_target_folder,
                )
                # If we already know the doc_id from session state, prefer
                # it; otherwise fall back to the dedup-found latest.
                if not st.session_state.get("last_brief_doc_id") and _ms_latest_id:
                    st.session_state["last_brief_doc_id"] = _ms_latest_id

                if st.session_state.get("last_brief_doc_id"):
                    res = update_google_doc_docx(
                        st.session_state["last_brief_doc_id"],
                        docx_bytes,
                        new_title=title,
                    )
                    if res["ok"]:
                        url = f"https://docs.google.com/document/d/{st.session_state['last_brief_doc_id']}/edit"
                        st.session_state["last_brief_doc_url"] = url
                        _sap(st.session_state["last_brief_doc_id"], _mp)
                        try:
                            _ublp(_pl_co, url, _pl_mode, _pl_date)
                        except Exception:
                            pass
                        st.success(f"✅ Updated existing Doc. [Open it →]({url})")
                    else:
                        st.error(f"Update failed: {res['error']}")
                else:
                    res = create_google_doc_from_docx(
                        docx_bytes=docx_bytes,
                        title=title,
                        parent_folder_id=(drive_folder or None),
                        share_with=share_with or None,
                    )
                    if res["ok"]:
                        st.session_state["last_brief_doc_url"] = res["doc_url"]
                        if res.get("doc_id"):
                            _sap(res["doc_id"], _mp)
                        try:
                            _ublp(_pl_co, res["doc_url"], _pl_mode, _pl_date)
                        except Exception:
                            pass
                        st.success(f"✅ Created in Drive. [Open it →]({res['doc_url']})")
                    else:
                        err = res.get("error") or "unknown"
                        st.error(
                            f"Drive create failed: {err}\n\n"
                            f"If this is a permissions error, share the parent folder "
                            f"(`{drive_folder}`) with the service account email "
                            f"(`command-center@prefab-bruin-491807-n0.iam.gserviceaccount.com`) "
                            f"as **Editor**, then try again."
                        )

        if _autosave_ok:
            # Auto-save worked → demote manual save into an expander.
            with st.expander("🛠 More save actions", expanded=False):
                st.caption(
                    "**Re-render Doc with latest code** — pushes a fresh render of "
                    "this same brief into the existing Doc, without paying for "
                    "another Claude call. Useful when renderer fixes have shipped "
                    "since your last Build."
                )
                if _manual_save_button():
                    _run_manual_save()
        else:
            # Auto-save failed (or never ran) → manual save is the primary CTA.
            if _manual_save_button():
                _run_manual_save()

        if st.session_state.get("last_brief_doc_url"):
            st.caption(f"📄 Latest Doc: {st.session_state['last_brief_doc_url']}")

            # ── Share panel — fires a Drive notification email to recipients ──
            with st.expander("📧 Share with the team", expanded=False):
                st.caption(
                    "Adds the recipient as a Doc editor AND sends Google's "
                    "share-notification email so they actually see it."
                )
                preset_emails = [
                    ("Prem", "prem@graas.ai"),
                    ("Amruta", "amruta@graas.ai"),
                ]
                share_cols = st.columns(len(preset_emails))
                selected_presets: list = []
                for i, (label, email) in enumerate(preset_emails):
                    with share_cols[i]:
                        if st.checkbox(f"{label} ({email})", value=True, key=f"share_preset_{email}"):
                            selected_presets.append(email)

                extras_raw = st.text_input(
                    "Other emails (optional, comma-separated)",
                    key="share_extra_emails",
                    placeholder="e.g. cofounder@graas.ai, sales@graas.ai",
                )
                extras = [e.strip() for e in (extras_raw or "").split(",") if e.strip() and "@" in e]

                msg = st.text_area(
                    "Message (optional — appended to Google's notification email)",
                    key="share_msg",
                    height=70,
                    placeholder=f"e.g. 'Pre-call brief for {st.session_state.get('last_brief_company', '<company>')}. "
                                f"Please scan before our meeting.'",
                )

                share_btn_col, _ = st.columns([2, 5])
                with share_btn_col:
                    if st.button("📨 Send share notification", type="primary",
                                 use_container_width=True, key="share_send_btn"):
                        recipients = list(dict.fromkeys(selected_presets + extras))  # dedupe, keep order
                        if not recipients:
                            st.warning("Pick at least one recipient.")
                        else:
                            from services.sheets_client import share_drive_file_with_notification
                            with st.spinner(f"Sharing with {len(recipients)} recipient(s)…"):
                                res = share_drive_file_with_notification(
                                    doc_id=st.session_state.get("last_brief_doc_id")
                                            or _extract_doc_id(st.session_state["last_brief_doc_url"]),
                                    emails=recipients,
                                    message=msg.strip(),
                                )
                            if res["sent"]:
                                st.success(f"✅ Notified: {', '.join(res['sent'])}")
                            if res["failed"]:
                                for f in res["failed"]:
                                    st.error(f"❌ {f['email']}: {f['error']}")


# ─────────────────────────────────────────────────────────────────────────────
# Recent briefs — tiles at the bottom of the page (page-wide, outside columns)
# Pulls from the SalesHub Shared Drive. Click any tile to jump to the Doc.
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown("### 🗂 Recent briefs")
st.caption("Pulled from the SalesHub Shared Drive · click any tile to open the Doc")


@st.cache_data(ttl=300)
def _list_recent_briefs(folder_id: str) -> list:
    """List recent Prospect Brief Docs in the Shared Drive (5-min cache)."""
    from services.sheets_client import list_drive_folder_docs
    docs = list_drive_folder_docs(folder_id)
    # Filter to Prospect Brief files only (Architect/Soln files share the folder)
    return [d for d in docs if d["name"].lower().startswith("prospect brief")]


_recent = _list_recent_briefs(DEFAULT_DRIVE_FOLDER)
if not _recent:
    st.caption("_No briefs saved to this Drive folder yet._")
else:
    # Parse company + date from each filename, then dedupe by company
    # (case-insensitive) — newest wins since the source list is already
    # sorted modifiedTime-desc.
    _parsed = []
    _seen_companies: set = set()
    for _d in _recent:
        _name = _d["name"]
        _m = re.match(r"Prospect Brief\s*[—\-]\s*(.+?)\s*[—\-]\s*(\d{4}-\d{2}-\d{2})", _name)
        if _m:
            _company, _date_str = _m.group(1).strip(), _m.group(2)
        else:
            _company = (_name.replace("Prospect Brief —", "")
                            .replace("Prospect Brief -", "").strip() or _name)
            _date_str = ""
        _key = _normalize_company_key(_company)
        if _key in _seen_companies:
            continue
        _seen_companies.add(_key)
        _props = _d.get("app_properties", {}) or {}
        _parsed.append({
            "company": _company,
            "date": _date_str,
            "id": _d["id"],
            "mode": _props.get("brief_mode", ""),
            "call_count": int(_props.get("brief_call_count", "0") or 0),
        })

    # Legend above tiles — explains the colour code at a glance.
    st.caption(
        "🆕 <span style='background:#f0f0f0;padding:1px 6px;border-radius:4px;"
        "border:1px solid #ddd;'>Pre-call draft</span> &nbsp;·&nbsp; "
        "🔁 <span style='background:#e6efff;padding:1px 6px;border-radius:4px;"
        "border:1px solid #b6cfff;'>Post call-N</span>",
        unsafe_allow_html=True,
    )

    # 6-column tiles, 2 rows max = 12 unique-company tiles shown.
    # Each tile carries a coloured badge for its mode (pre-call vs post-call N)
    # read from the Doc's Drive appProperties, set at auto-save time.
    _tiles = _parsed[:12]
    _rows = [_tiles[i:i + 6] for i in range(0, len(_tiles), 6)]
    for _row in _rows:
        _cols = st.columns(6)
        for _col, _p in zip(_cols, _row):
            _url = f"https://docs.google.com/document/d/{_p['id']}/edit"
            _mode = _p.get("mode", "")
            _cc = _p.get("call_count", 0)
            if _mode.startswith("Post call") or _cc > 0:
                _badge_icon = "🔁"
                _badge_text = _mode or f"Post call-{_cc}"
                _badge_bg, _badge_border = "#e6efff", "#b6cfff"
            elif _mode == "Pre-call draft" or not _mode:
                _badge_icon = "🆕"
                _badge_text = "Pre-call draft"
                _badge_bg, _badge_border = "#f0f0f0", "#dddddd"
            else:
                _badge_icon = "📄"
                _badge_text = _mode
                _badge_bg, _badge_border = "#f0f0f0", "#dddddd"
            with _col:
                with st.container(border=True):
                    st.markdown(
                        f"<div style='font-size: 0.85em; font-weight: 600; line-height: 1.2; "
                        f"margin-bottom: 2px;'>{_p['company']}</div>"
                        f"<div style='font-size: 0.65em; margin: 2px 0;'>"
                        f"<span style='background:{_badge_bg};border:1px solid {_badge_border};"
                        f"padding:1px 5px;border-radius:4px;'>"
                        f"{_badge_icon} {_badge_text}</span></div>"
                        f"<div style='font-size: 0.7em; color: #888;'>{_p['date']}</div>"
                        f"<a href='{_url}' target='_blank' style='font-size: 0.75em;'>Open →</a>",
                        unsafe_allow_html=True,
                    )
    if len(_parsed) > 12:
        st.caption(f"_+{len(_parsed) - 12} older briefs — open the Drive folder to see more._")
