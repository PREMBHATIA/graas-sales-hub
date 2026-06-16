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
            "the dropdown and the form pre-fills with what we already know."
        )
    with m2:
        st.markdown("##### 🔁 Update existing (post-call)")
        st.caption("After every call")
        st.markdown(
            "Paste the existing brief's **Doc URL + your fresh call notes** "
            "(Granola export, Zoom transcript, or hand-typed). The brief amends "
            "in place — answers move into facts, confidence upgrades to "
            "*Confirmed*, the route firms up."
        )

    st.markdown("#### The living-document workflow")
    st.info(
        "**Pre-call draft → Post call-1 → Post call-2 → … → Ready for solutioning**\n\n"
        "Don't treat this as one-shot. Build it before call 1, then re-open this page "
        "after every call and run the update. The status line at the top of the brief "
        "tracks the version. When the qualification gate is met (decision-maker known, "
        "budget identified, data readiness understood, CFO metric confirmed by the customer), "
        "hand it to the **Create Proposal** page."
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
        "Saved by default to the **\"Prospect Brief (via SalesHub)\"** Shared Drive. "
        "Override the folder ID in step 4 for a different destination. The Doc is "
        "auto-shared with the emails you list, so it shows up in their *Shared with me*."
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
        existing_brief_id = st.text_input(
            "Existing brief — paste the Google Doc URL or ID",
            key="brief_existing_id",
            placeholder="https://docs.google.com/document/d/<DOC_ID>/edit  (or just the ID)",
        )
        call_notes = st.text_area(
            "New call notes (Granola summary, Zoom transcript, or paste your own)",
            key="brief_call_notes",
            height=300,
            placeholder="e.g.\n"
                        "Met Ravi (CTO) and Priya (VP Sales) on 28 Apr.\n"
                        "Confirmed: 19K dealers, 400 FSAs across 3 regions; SAP ERP; no DMS.\n"
                        "New: champion is Priya, budget owner is CFO (Anil), Q3 budget cycle.\n"
                        "Pushback: 'we've tried a chatbot before — didn't work'.\n"
                        "Asked for: a 60-day pilot proposal, one region only.",
        )
        research_text = ""

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

    st.markdown("### 5. Action")
    build_clicked = st.button(
        ("📝 Build brief" if mode.startswith("🆕") else "🔁 Update from call notes"),
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
  "executive_summary": {
    "category": "vertical + business model in one line — e.g. 'Industrial gases distributor'",
    "type": "ONE of: 'OEM / Principal / Brand' | 'Multi-brand distributor' | 'Multi-brand retailer'",
    "motion": "ONE of: 'B2B / General Trade' | 'B2C / eCommerce' | 'Both — wedge is ___'",
    "comps": "2-3 named competitors with one-clause positioning — e.g. 'Linde (premium), Aboitiz Power (regional scale), Bharat Petroleum (state-owned challenger)'",
    "history": "founding / trajectory / recent inflection in one line — e.g. 'Founded 1972; family-owned; expanded into specialty gases 2019; now 3rd-largest by volume'",
    "maturity": "AI & systems maturity assessment in one line — e.g. 'Mid: SAP-ERP since 2018, Salesforce CRM, no agents deployed; piloting GenAI for support tickets (2025)'"
  },
  "stat_band": [
    {"label": "Revenue", "value": "value, prefix estimates with ~"},
    {"label": "SKUs", "value": "..."},
    {"label": "Channel touchpoints", "value": "..."},
    {"label": "Field force", "value": "..."},
    {"label": "Geography", "value": "..."}
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
  "persona_map": [
    {"persona": "Dealers", "count": "~500", "surface": "WhatsApp / phone today", "flow_and_leaks": "Phone order → SFA → ERP → invoice → delivery. *Leak: ~20% orders miss SFA same day; 3-day credit-check delay*"}
  ],
  "pain_capability_cfo": [{"pain": "pain in their language", "capability": "All-e/KG capability", "metric": "DSO / revenue per rep / cost per order / ..."}],
  "metric_that_matters": "The metric this moves for [CFO or decision-maker name, role] is [single literal metric].",
  "discovery": {
    "business_model": ["Walk-me-through-one-order question, plus 1-2 motion questions."],
    "data_readiness": ["SKU count + catalogue cleanliness questions; sell-out data agent-readiness; **API-build effort**: who builds the APIs (in-house IT, vendor, partner) and how long — direct from systems (ERP, Loyalty, DMS) or via a data warehouse; existing layer or built from scratch."],
    "tech_integration": ["Existing agents? Channels live? System of record + API? WABA?"],
    "commercial_authority": ["Who owns the budget and the metric? Who signs?"],
    "motion_specific": {"label": "If B2B / General Trade  OR  If B2C / eCommerce", "questions": ["..."]}
  },
  "people_path_in": [
    {"name": "...", "role": "...", "why_matter": "1-line relevance", "type": "Decision-maker | Champion | Finance buyer | Meeting attendee", "linkedin": "ONE optional line (background + prior companies). Omit field if no useful info."}
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


def _build_new_brief_prompt(
    crm_data: dict,
    research: str,
    company: str,
    meeting_date: str = "",
    attendees: str = "",
) -> str:
    """Compose the user-turn prompt for a fresh pre-call brief."""
    today = datetime.now().strftime("%Y-%m-%d")
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
        f"**DO NOT DROP MANDATORY FIELDS.** Every brief must include: "
        f"executive_summary (6 fields rendered as two stacked box rows: "
        f"category/type/motion on row 1, comps/history/maturity on row 2 — NOT a "
        f"paragraph, NOT labelled lines), stat_band (all 5), what_they_have (all 10 dimensions: "
        f"Business model · Scale · Funding status · Top brands · Top competitors · "
        f"Channel structure · Catalogue size / SKU count · Tech stack · External-facing "
        f"agents · AI maturity), recent_news (**MAX 2 bullets**, the most material; or "
        f"one honest 'Nothing material in the last 12 months from public sources'), "
        f"what_missing, product_route, persona_map (each row contains the current order "
        f"flow + leak points for THAT persona — split into per-motion rows: Dealers, "
        f"Retailers via SFA, B2B customers, etc.), pain_capability_cfo, "
        f"metric_that_matters, discovery (all 4 buckets + motion_specific), "
        f"people_path_in (merge meeting attendees here; use type='Meeting attendee' + "
        f"the optional linkedin field for any attendees the user provided), entry_wedge, "
        f"next_step, opening_hook, conflicts_unknowns (appendix at the end — keep it "
        f"terse). If a fact is genuinely not findable, set the value to *\"Info not "
        f"publicly available\"* and confidence to *\"Unknown\"* — **never drop the "
        f"row**.\n\n"
        f"**REMOVED FIELDS (do not include):** order_flow (now rolled into persona_map "
        f"as a column per persona), other_signals (dropped — promote material findings to "
        f"recent_news or what_missing), meeting_attendees (merged into people_path_in "
        f"with type='Meeting attendee').\n\n"
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
                max_tokens=8000,
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
                st.error(
                    "Claude didn't return valid JSON. This usually means the model "
                    "wrapped the response in commentary or got cut off mid-output.\n\n"
                    f"**Parse error:** {parse_err}\n\n"
                    f"**First 1500 chars of response:**\n\n{raw_text[:1500]}"
                )
                st.stop()

            # Sanity-check mandatory fields are populated
            required_keys = ("executive_summary", "stat_band", "what_they_have",
                             "product_route", "pain_capability_cfo", "opening_hook")
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
        save_cols = st.columns([2, 2, 1])

        # Save to Drive (new doc) — only meaningful for pre-call mode OR if the
        # update was generated and the user wants a fresh copy
        with save_cols[0]:
            save_label = (
                "🔁 Re-upload to existing Doc"
                if st.session_state.get("last_brief_doc_id")
                else "💾 Create new Google Doc"
            )
            if st.button(save_label, type="primary", use_container_width=True, key="brief_save_btn"):
                with st.spinner("Talking to Drive…"):
                    from services.sheets_client import create_google_doc_from_docx, update_google_doc_docx
                    title = (
                        f"Prospect Brief — {st.session_state['last_brief_company']} — "
                        f"{datetime.now():%Y-%m-%d}"
                    )
                    share_with = [
                        e.strip() for e in (share_with_raw or "").split(",")
                        if e.strip() and "@" in e
                    ]
                    docx_bytes = st.session_state.get("last_brief_docx", b"")
                    if not docx_bytes:
                        st.error("No DOCX bytes in session — regenerate the brief.")
                        st.stop()
                    if st.session_state.get("last_brief_doc_id"):
                        res = update_google_doc_docx(
                            st.session_state["last_brief_doc_id"],
                            docx_bytes,
                        )
                        if res["ok"]:
                            url = f"https://docs.google.com/document/d/{st.session_state['last_brief_doc_id']}/edit"
                            st.session_state["last_brief_doc_url"] = url
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

        # Download as DOCX (opens cleanly in Word + Google Docs)
        with save_cols[1]:
            fname = f"prospect-brief-{(st.session_state['last_brief_company'] or 'untitled').lower().replace(' ', '-')}-{datetime.now():%Y-%m-%d}.docx"
            st.download_button(
                "⬇️ Download DOCX",
                data=st.session_state.get("last_brief_docx", b""),
                file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )

        # Clear
        with save_cols[2]:
            if st.button("🗑 Clear", use_container_width=True, key="brief_clear_btn"):
                for k in ("last_brief_data", "last_brief_html", "last_brief_docx",
                          "last_brief_company", "last_brief_mode",
                          "last_brief_doc_url", "last_brief_doc_id"):
                    st.session_state.pop(k, None)
                st.rerun()

        if st.session_state.get("last_brief_doc_url"):
            st.caption(f"📄 Latest Doc: {st.session_state['last_brief_doc_url']}")

            # ── Share panel — fires a Drive notification email to recipients ──
            with st.expander("📧 Share with the team", expanded=True):
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
