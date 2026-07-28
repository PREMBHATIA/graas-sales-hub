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
    st.markdown("#### The 30-second version")
    st.markdown(
        "**Type in a company name.** I'll research it, figure out gaps "
        "Graas can fill, and suggest a script + discovery questions for "
        "the call.\n\n"
        "**Post your call**, drop your notes — paste the Granola summary "
        "or Zoom transcript straight into the post-call section, OR just "
        "edit the Google Doc brief directly. Either way, I read your "
        "changes on the next regen and use them as the new baseline."
    )

    st.markdown("#### Two modes")
    m1, m2 = st.columns(2)
    with m1:
        st.markdown("##### 🆕 New brief (pre-call)")
        st.markdown(
            "Pick the company from CRM (or type) + paste any research notes "
            "you have. Auto-saves to Drive when done."
        )
    with m2:
        st.markdown("##### 🔁 Update existing (post-call)")
        st.markdown(
            "4-card wizard: paste prior brief URL → paste call notes → "
            "click Update. Updates the same Doc in place; tile flips to "
            "Post call-N."
        )

    st.markdown("#### Tips that change output quality")
    st.markdown(
        "- **Quote your sources** in research notes (*\"$290M per Euromonitor; "
        "$50-100M per LeadIQ — conflicting\"*). The brief flags conflicts "
        "instead of silently picking one.\n"
        "- **Note what you don't know** (*\"not yet clear if they have a DMS\"*) "
        "→ becomes a discovery question.\n"
        "- **Paste call notes verbatim**. Don't pre-summarise — the diff against "
        "the discovery agenda works better with raw notes.\n"
        "- **Edit the Doc freely**. Your edits are preserved on the next regen — "
        "the bot reads them and uses them as the new baseline. Don't redo work."
    )

    st.markdown("#### ✨ What's new")
    st.markdown(
        "- **One Doc per customer, auto-saved** — also auto-linked into "
        "pipeline sheet column S.\n"
        "- **Post-call wizard** + **Meeting Notes scratchpad** to write "
        "into during the call.\n"
        "- **Yellow row highlights** show what changed each call · "
        "**Timeline** tells you deal pace.\n"
        "- **I preserve your edits** on the next regen — your framings are "
        "the new baseline.\n"
        "- **Past-meeting auto-detect** in your research notes → brief "
        "promoted to Post call-1 automatically."
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
    # "Prospect Briefs" folder — shared with the graas.ai domain (reader) and
    # command-center (fileOrganizer). Briefs land here and inherit the domain
    # share, so anyone at graas.ai can open them from the tiles — no per-doc
    # approval — while the KB (a separate, unshared folder) stays private.
    "12GtdM6jKWu2QXT8D_6WoGq4wvmkcce7Q",
)

# Per-file domain sharing is now handled by the shared "Prospect Briefs" folder
# above (briefs inherit its graas.ai-reader permission), so this is OFF by
# default. Set PROSPECT_BRIEF_SHARE_DOMAIN=graas.ai to also stamp each brief
# individually (belt-and-suspenders, e.g. if briefs are written outside the
# shared folder).
BRIEF_SHARE_DOMAIN = os.getenv("PROSPECT_BRIEF_SHARE_DOMAIN", "")


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
                "notes_link": str(r.get("Link for full notes", "")).strip(),
            }))
        return out
    except Exception:
        return []


CRM = load_crm_companies()


# ── Layout: form on left, output on right ─────────────────────────────────────
left, right = st.columns([5, 6])

with left:
    # Single generate path. The old post-call merge/update flow was removed —
    # regenerating a fresh two-pager beats an ugly merge. `mode` is kept as a
    # constant so the downstream `mode.startswith("🆕")` branches stay valid
    # (the "🔁" branches below are now unreachable dead code).
    mode = "🆕 New brief (pre-call)"

    st.markdown("### 1. Company")
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

    st.markdown("### 2. Inputs")

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

        # 1×3 single-row layout. Card 4 (Done) removed — its content
        # duplicates the right-pane success banner + Save section, so it
        # was visual noise. Fixed-height containers so all 3 cards line
        # up evenly (card 2's textarea would otherwise stretch its row).
        _CARD_H = 400
        c1, c2, c3 = st.columns(3)
        with c1:
            with st.container(border=True, height=_CARD_H):
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
                # Convenience link → SalesHub Shared Drive root so user can
                # browse to a prior brief without leaving the page.
                _sh_drive_url = "https://drive.google.com/drive/folders/0ABwowt8s9tmzUk9PVA"
                st.markdown(
                    f"<div style='margin-top:10px;font-size:9pt;'>"
                    f"📁 <a href='{_sh_drive_url}' target='_blank' "
                    f"style='color:#2742FF;text-decoration:none;'>"
                    f"Browse SalesHub Drive folder →</a></div>",
                    unsafe_allow_html=True,
                )
        with c2:
            with st.container(border=True, height=_CARD_H):
                _b = "✅" if _card2_valid else "2."
                st.markdown(f"**{_b} Call notes**")
                st.caption("Granola / Zoom · email thread · WhatsApp · or paste your own")
                st.text_area(
                    "Notes",
                    key="brief_call_notes",
                    label_visibility="collapsed",
                    height=200,
                    placeholder="Paste raw notes, email trail, or WhatsApp chat — don't pre-summarise",
                )
                _msg = (f"✅ {len(_pc_notes.strip())} chars" if _card2_valid
                        else f"⏳ {len(_pc_notes.strip())} chars (need ≥30)")
                st.caption(_msg)
                # If the selected company has a notes link in CRM col K,
                # surface it — that content auto-pulls + merges with what
                # the user types below at Build time.
                _crm_link = (crm_data or {}).get("notes_link", "")
                if _crm_link:
                    _short = _crm_link if len(_crm_link) <= 60 else _crm_link[:57] + "…"
                    st.caption(
                        f"📎 Will also auto-pull from CRM col K: `{_short}`"
                    )
        with c3:
            with st.container(border=True, height=_CARD_H):
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

                # Working state + last-attempt outcome. Streamlit shows its own
                # top-of-page "RUNNING" indicator during the rerun, but users
                # don't always notice it — surface the same signal in-card.
                if build_clicked:
                    st.caption("⏳ Working… activity panel below shows live progress.")
                else:
                    _last_pc = st.session_state.get("last_pc_attempt_outcome")
                    if _last_pc and _last_pc.get("status") == "error":
                        _msg = str(_last_pc.get("message", ""))[:140]
                        st.error(
                            f"❌ Last attempt failed — click **Update brief** again.\n\n`{_msg}`"
                        )

        # Mirror wizard state into the var names the downstream generation
        # code expects (existing_brief_id, call_notes, build_clicked).
        existing_brief_id = _pc_url
        call_notes = _pc_notes

    # Save destination + share — tucked away in an expander; defaults
    # are right 99% of the time, so most users never touch this.
    with st.expander("⚙️ Advanced — Drive folder + share list", expanded=False):
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
        st.markdown("### 3. Build")
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
    "meeting_context": "ONE line — who's in the room + why this meeting is happening. e.g. 'Intro call with Head of Digital, requested after our LinkedIn outreach' or 'TBC — cold pre-brief'."
  },
  "summary_boxes": {
    "industry": "vertical + business model in ≤10 words. e.g. 'B2B industrial MRO marketplace + brand catalog'.",
    "type": "ONE of: 'OEM / Principal / Brand' | 'Multi-brand distributor' | 'Multi-brand retailer' | 'Marketplace / Platform'. Add a 1-3 word qualifier if useful.",
    "revenue": "figure + unit + FY, 3-8 words. e.g. '~₹6,500 Cr FY25 (GMV)'. ONE source-clean value — no parentheticals stacked.",
    "comps": "2-3 named competitors, one clause each. e.g. 'Zetwerk (fabrication), Amazon Business (horizontal), IndiaMART (leads)'.",
    "scale": "the one operational scale number that matters — SKUs / outlets / sellers / field force / geography. 3-10 words. e.g. '10M+ SKUs · 1.5M+ SMEs · 30 countries'."
  },
  "_summary_boxes_NOTE": "100% FACTUAL header strip — revenue, comps, industry, scale. No opinion, no Graas angle. These are the numbers that would survive a fact-check. Keep each cell tight (it renders in a box).",
  "key_people": [
    {
      "name": "Full name. If you genuinely can't find a real named person for a role, omit the row — do NOT invent names.",
      "designation": "exact title + org unit. e.g. 'Chief Digital Officer', 'Head of Technology, Enterprise'.",
      "linkedin": "FULL https://www.linkedin.com/in/... URL if found (renders as a hyperlink). Omit the field entirely if you don't have a real URL — never fabricate a slug.",
      "play": "ONE phrase, 8-20 words — who they are to the deal AND how to play them. Encode the stance: champion / economic buyer (signs) / tech owner / landmine defending an incumbent / ally. e.g. 'Owns the Google/Devoteam relationship — landmine on search, ally on the data layer' or 'Actually signs — aim the cost-to-serve number at him'."
    }
  ],
  "_key_people_NOTE": "3-6 people. The ONLY people list in the brief. Map the BUYING GROUP, not just the meeting attendee: the economic buyer (who signs), the tech owner (CTO / Head of Tech), the champion, and the internal owner of any incumbent platform in `stack`. LinkedIn URLs hyperlink the name. A one-name list is a research miss.",
  "stack": [
    {
      "layer": "ONE of: 'ERP' | 'CRM' | 'AI / Agents' | 'Search / Discovery' | 'CDP / Data' | 'Commerce / Storefront' | 'Ordering / B2B' | 'Chatbot' (add others only if load-bearing). MUST cover ERP, CRM, and the AI/agent stack at minimum.",
      "system": "the named product they run at this layer. e.g. 'SAP S/4HANA', 'Salesforce Sales Cloud', 'Google Vertex AI Search', 'custom React storefront'. 'None found' if genuinely absent — that's a signal, not a gap to hide.",
      "vendor": "the SI / agency / partner who built or runs it. RESEARCH THIS. e.g. 'Deloitte (SAP)', 'Devoteam (Google Diamond SI)', 'In-house'. 'Unknown' only after you've looked.",
      "owner": "internal owner name + role if found, else 'Unknown'. Cross-references key_people.",
      "verdict": "ONE of: 'Contested — incumbent entrenched, do NOT wedge here' | 'Work-on-top-of — integrate, don't replace' | 'Greenfield — no system, the wedge' | 'Ally-able — owner could champion Graas'.",
      "source": "short source for the system/vendor claim. e.g. 'job posts', 'case study on vendor site', 'press release Mar-25'.",
      "confidence": "Confirmed | Public estimate | Inferred | Unknown"
    }
  ],
  "_stack_NOTE": "This is the COMBINED asset-map + what-they-have + incumbency table — the analytical core of the brief. 4-8 rows. You MUST hunt for their ACTUAL live systems before writing — never assume greenfield. Find the real chatbot / search / agent on their live site + WHO built it. MUST include rows for ERP, CRM, and AI/Agents. The vendor column is the competitive map: an entrenched SI is a reason to AVOID a lane, not attack it.",
  "graas_fit": [
    {
      "where": "which stack layer / operational area this hangs off. e.g. 'B2B ordering', 'Search / Discovery', 'Field-force app'.",
      "fit": "QUESTION-FRAMED hypothesis, ≤20 words. Name the Graas product AND phrase it as a 'could this fit?'. e.g. 'Could All-e for Distributors sit on top of the reseller-ordering flow the SAP layer doesn't touch?' Do NOT assert fitment — hypothesize it.",
      "verify": "the ONE thing to confirm in the meeting that would make/break this fit. ≤15 words. e.g. 'Is reseller ordering still on WhatsApp + manual, or already digitised?'"
    }
  ],
  "_graas_fit_NOTE": "2-4 hypotheses MAX. Each hangs off a `stack` row. FIT IS A QUESTION, NOT A CLAIM — 'could fit X?' — because forced Graas fitment is the failure mode we're fixing. It's fine to have fewer, sharper hypotheses. If nothing fits cleanly, say so in `honesty.do_not_oversell`.",
  "do_not": [
    "Landmine — ONE phrase each. Things NOT to pitch or fight. e.g. 'Don't pitch search — they resell Algolia to their own SME customers', 'Don't fight the SAP layer — Deloitte owns it, 3-yr contract', 'Don't lead B2C — the storefront is a cost centre they're winding down'.",
    "..."
  ],
  "_do_not_NOTE": "2-4 landmines. The single most valuable output for a rep walking in cold. Draw from stack (contested lanes), from products the prospect SELLS (never pitch someone their own product), and from the logo-wall cross-check (see prompt).",
  "wedges_worth_exploring": [
    "1-3 SHORT exploratory phrases — the sharpest angles worth a try, NOT a confident recommendation. Question marks welcome. Each absorbs 'where the money/mandate actually is' and hangs off a greenfield/ally-able stack row or a graas_fit hypothesis. e.g. 'Reseller-ordering flow — greenfield, no SI owns it; is it still manual?' or 'The +21%-growth B2B segment looks more open than the contested B2C storefront.'",
    "..."
  ],
  "_wedges_worth_exploring_NOTE": "1-3 items MAX, phrases not paragraphs. This REPLACES the old assertive 'wedge' — the tone is 'worth exploring?', not 'plant the flag here'. If nothing looks open, it's honest to have ONE item that says the angle is unclear until discovery. Question marks are encouraged.",
  "discovery": [
    "Up to 5 operational questions for the meeting — flows, metrics, integrations, budgets, ownership. Each ≤20 words. NEVER ask an attendee's role/background. e.g. 'Is reseller ordering digitised or still manual/WhatsApp?', 'Who owns the budget for a digital pilot?', 'What did your own AI build NOT solve that's still a gap?'"
  ],
  "_discovery_NOTE": "APPENDIX. MAX 5 questions total. Operational only, ≤20 words each. Fewer, sharper beats a padded list. Lead with the question that tests the shakiest assumption behind any graas_fit hypothesis.",
  "appendix_research": [
    {
      "fact": "ONE important, 100%-CONFIRMED fact that didn't make the main two-pager but is worth having on hand — funding round, a confirmed exec hire, a regulatory driver, a segment growth number, a confirmed competitor/partner move. CONFIRMED ONLY — no inferences or estimates.",
      "source": "short source with date. e.g. 'Economic Times, Jun-25'."
    }
  ],
  "_appendix_research_NOTE": "APPENDIX. 0-6 rows. Overflow bucket for CONFIRMED research that didn't earn a spot on the main page. Every row must be verifiable against a real source — if it's only inferred or estimated, DROP it. Keep the main two-pager clean; park the confirmed rest here."
}"""


REFERENCE_PROPOSALS_FOLDER_ID = "1tBMrcpiIDVhg5e0-N1ytjuzbDexQyheX"


# DEPRECATED static list — kept only as a SHAPE REFERENCE for what
# _fetch_commerce_tech_story() returns. The page no longer reads from
# this list (it would be fabricated content). The live fetch returns the
# same dict shape: {tag, title, body, why, source_label, source_url}.
# REMOVE this entire constant in a follow-up cleanup once the live
# fetch has been in production for a few weeks.
_COMMERCE_TECH_STORIES_DEPRECATED = [
    {
        "tag": "🇺🇸 US · agentic commerce",
        "title": "Amazon Rufus — shopping becomes a conversation",
        "body": (
            "Amazon's Rufus AI assistant is now embedded inside the Amazon "
            "app, answering product questions, comparing SKUs and "
            "personalising recommendations live. Early reports show "
            "Rufus users have higher session times and AOV than search-only."
        ),
        "why": (
            "The default eCom UX is shifting from search-and-filter to "
            "ask-and-receive. Every retailer with a marketplace presence "
            "(or their own storefront) now has to answer: do we build "
            "our own agentic layer, or watch Amazon set the bar?"
        ),
        "source_label": "Amazon news blog",
        "source_url": "https://www.aboutamazon.com/news/retail/amazon-rufus-generative-ai-shopping-assistant",
    },
    {
        "tag": "🇮🇳 India · quick commerce",
        "title": "Zepto, Blinkit, Instamart — 10-min war goes nuclear",
        "body": (
            "Quick commerce in India crossed $5B GMV run-rate, with Zepto "
            "raising at $5B valuation and Blinkit profitable in 8 cities. "
            "Dark-store density is the moat, but AI-driven SKU optimisation "
            "per dark store is where the margin lives."
        ),
        "why": (
            "Distribution + AI + dark-store ops = the new D2C playbook in "
            "SEA-style markets. Every kirana-distribution prospect is "
            "watching this. Q-commerce is also redefining 'what fast "
            "fulfilment looks like' for FMCG brands sitting upstream."
        ),
        "source_label": "TechCrunch India",
        "source_url": "https://www.google.com/search?q=Zepto+Blinkit+Instamart+quick+commerce+valuation+2026&tbm=nws",
    },
    {
        "tag": "🇺🇸 US · merchant tooling",
        "title": "Shopify Magic + Sidekick — AI co-pilot for every merchant",
        "body": (
            "Shopify shipped Magic (AI copy, product images, FAQs) and "
            "Sidekick (conversational store manager) to all merchants — no "
            "extra fee. SMBs now have a built-in AI co-pilot for marketing, "
            "support and inventory questions."
        ),
        "why": (
            "Verticalised AI inside a platform crushes standalone tools. "
            "If you're selling a third-party AI capability into a Shopify "
            "merchant, you have ~12 months before Shopify ships their own "
            "version. Move fast or pick a non-overlapping wedge."
        ),
        "source_label": "Shopify",
        "source_url": "https://www.shopify.com/magic",
    },
    {
        "tag": "🇮🇩 SEA · live commerce",
        "title": "TikTok Shop Indonesia — #2 platform in 18 months",
        "body": (
            "TikTok Shop is now the #2 ecom platform in Indonesia after "
            "Tokopedia, with creator-led live shopping driving the lift. "
            "Local sellers report 30-50% of GMV via live sessions; "
            "the algorithm rewards conversational, not catalogue, UX."
        ),
        "why": (
            "Live commerce + creator discovery is the SEA default — not "
            "an experiment. Indonesian retail prospects (pharmacy, FMCG, "
            "fashion) need agentic product search + cart flows that work "
            "inside chat / live, not just web storefronts."
        ),
        "source_label": "Reuters",
        "source_url": "https://www.google.com/search?q=TikTok+Shop+Indonesia+live+commerce+platform+share&tbm=nws",
    },
    {
        "tag": "🇺🇸 US · capital signal",
        "title": "SpaceX $350B secondary — what late-stage tech capital says",
        "body": (
            "SpaceX closed a secondary at $350B valuation, making it the "
            "most valuable private company globally. Even with rate-cycle "
            "headwinds, investors are writing massive cheques for "
            "infrastructure + defensible moats."
        ),
        "why": (
            "Late-stage capital still flowing — but to category-defining "
            "infra plays. For Graas customers in capital-restructuring "
            "years (Pyfa, Kalbe-style), this signals where the "
            "competitive AI investment is going and what the bar is for "
            "'tech budget' framing."
        ),
        "source_label": "Bloomberg",
        "source_url": "https://www.google.com/search?q=SpaceX+secondary+sale+350B+valuation&tbm=nws",
    },
    {
        "tag": "🌏 Global · AI for retail",
        "title": "Anthropic + OpenAI verticalise into retail/commerce",
        "body": (
            "Both Anthropic (Claude for Enterprise) and OpenAI (Operator + "
            "Custom GPTs for retail) are shipping verticalised agentic "
            "features for ecom. Retailer-specific evals, prebuilt connectors "
            "to Shopify/SAP/Salesforce, and managed agentic workflows."
        ),
        "why": (
            "The general-purpose AI window is closing for retailers. "
            "Vertical AI = Graas's lane. If a prospect is evaluating "
            "OpenAI's retail features, the question becomes 'commerce-"
            "native vs general-purpose with retail skin' — anchor on "
            "Graas's commerce-only DNA."
        ),
        "source_label": "Anthropic news",
        "source_url": "https://www.anthropic.com/news",
    },
]


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


from services.commerce_news import (
    fetch_commerce_tech_stories as _fetch_commerce_tech_stories,
    pick_story_for_session as _pick_story_for_session,
)


def _fetch_commerce_tech_story() -> dict:
    """Pick ONE story for this session from the daily 3-story pool."""
    return _pick_story_for_session(_fetch_commerce_tech_stories())



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
        f"Build a two-page pre-call Prospect Brief for **{company or '<NAME>'}**.\n"
        f"Today is {today}. header.date_prepared = {today}"
        f"{f'. header.meeting_date = {meeting_date}' if meeting_date else ''}.\n\n"
        f"This is a TWO-PAGER a rep reads in the 5 minutes before a call. It is a "
        f"sharp point of view, not an analyst report. Fewer, truer, harder-hitting "
        f"beats comprehensive. Every cell is a PHRASE (5-15 words), never a "
        f"paragraph. Compress with commas/semicolons; strip filler ('the company', "
        f"'is a leading', 'they also have').\n\n"
        f"**YOU HAVE THE `web_search` TOOL. USE IT HARD — this brief lives or dies on "
        f"research.** Run the searches a sharp analyst would: company site + investor "
        f"pages, recent news (12 mo), LinkedIn for named people, funding "
        f"(Crunchbase/Tracxn/DealStreetAsia), industry press. Source hierarchy: "
        f"filings/website = Confirmed; news = Confirmed for the event; aggregators "
        f"(LeadIQ/Lusha/Euromonitor) = Public estimate. Geography: start India, else "
        f"check SEA and state the real market in header.market.\n\n"
        f"**RULE 1 — HUNT THE ACTUAL LIVE STACK. NEVER ASSUME GREENFIELD.** Before you "
        f"write a single `stack` row, go find what they actually run: open their live "
        f"site and look for the real chatbot / search bar / product-finder / agent; "
        f"read their job posts (they name SAP, Salesforce, Vertex, Algolia, etc.); "
        f"find press releases and vendor case studies naming the SI who built it. For "
        f"EVERY named AI / commerce / data / search / chatbot system, identify the "
        f"external SI/agency behind it AND the internal owner. 'Greenfield' is a "
        f"verdict you EARN after looking — a wrong 'greenfield' call is the #1 way "
        f"this brief embarrasses the rep. The `stack` table MUST include rows for "
        f"ERP, CRM, and the AI/Agents layer at minimum, plus whatever else is "
        f"load-bearing (search, storefront, B2B ordering, CDP).\n\n"
        f"**RULE 2 — GRAAS FIT IS A QUESTION, NOT A CLAIM.** The old brief force-fit "
        f"Graas into every section; that's the failure we're fixing. In `graas_fit`, "
        f"phrase each hypothesis as 'could Graas product X fit layer Y?' and give the "
        f"ONE thing to verify in the meeting. 2-4 hypotheses MAX, each hanging off a "
        f"real `stack` row. If the fit is thin, have FEWER — and let the "
        f"`wedges_worth_exploring` line carry a question mark rather than a false "
        f"promise. A speculative fit stated as fact is worse than an honest "
        f"'unclear until we ask'.\n\n"
        f"**RULE 3 — LANDMINES (`do_not`).** The single most useful thing for a rep "
        f"walking in cold. 2-4 things NOT to pitch or fight: contested lanes an SI "
        f"owns (from `stack`), and — critically — products the PROSPECT THEMSELVES "
        f"SELLS. Cross-check the prospect's customer/logo wall and their own product "
        f"catalog against Graas's offering: never pitch someone a capability they "
        f"resell to their own customers. Name the landmine plainly.\n\n"
        f"**RULE 4 — STAY HONEST BY DEFAULT.** There is no confessional 'honesty' "
        f"section any more — honesty lives in the TONE. Keep graas_fit "
        f"question-framed; let wedges_worth_exploring carry question marks; and only "
        f"put a fact in `appendix_research` if it is 100% CONFIRMED against a real "
        f"source. Never state an inference as fact. A brief that quietly oversells "
        f"gets the rep caught flat in the room.\n\n"
        f"**RULE 5 — NO REPETITION.** Each load-bearing fact appears in EXACTLY ONE "
        f"place. summary_boxes = the factual header (revenue/comps/industry/scale). "
        f"stack = systems + vendors + owners. appendix_research = CONFIRMED overflow "
        f"facts that didn't make the main page. key_people = the only people list. If "
        f"you're about to restate a number, reference it in 3 words instead.\n\n"
        f"**RULE 6 — PEOPLE.** `key_people` maps the buying group (economic buyer who "
        f"signs, tech owner, champion, incumbent-platform owner), not just the "
        f"meeting attendee. Put a FULL LinkedIn URL in the `linkedin` field when you "
        f"find one (the renderer hyperlinks the name); omit the field rather than "
        f"fabricate a slug. Each `play` encodes the stance (champion/signer/landmine/"
        f"ally) + how to work them.\n\n"
        f"**SUMMARY BOXES ARE 100% FACTUAL AND TIGHT (3-10 words each).** Figure + "
        f"unit + qualifier, nothing more. No Graas angle, no opinion — these must "
        f"survive a fact-check. Right: '~₹6,500 Cr FY25 (GMV)'. Wrong: a stacked "
        f"'~₹6,500 Cr (~$780M; consolidated; per AR FY25, Tracxn TTM differs)'.\n\n"
        f"**PROOF POINTS (for `do_not` cross-check + your own grounding).** The list "
        f"below is every Graas customer/POC we have a proposal on file for — the ONLY "
        f"customers you may ever name. NEVER invent customer names, results, or "
        f"figures. Use this to sanity-check the logo-wall landmine (are we already "
        f"live with one of their competitors?) and to keep any Graas claim honest.\n\n"
        f"{proof_points_block}\n\n"
        f"**MANDATORY FIELDS — return every one, populated:** company, header "
        f"(with meeting_context), summary_boxes (all 5, factual), key_people (3-6, "
        f"real names + LinkedIn URLs where found), stack (4-8 rows incl. ERP/CRM/AI — "
        f"system + vendor/SI + owner + verdict + source + confidence; HUNT the real "
        f"systems), graas_fit (2-4 QUESTION-framed hypotheses off stack rows), "
        f"do_not (2-4 landmines), wedges_worth_exploring (1-3 SHORT exploratory "
        f"angles, question marks welcome — NOT a confident recommendation), "
        f"discovery (≤5 operational questions — appendix), appendix_research (0-6 "
        f"CONFIRMED-only overflow facts w/ source — appendix; drop anything merely "
        f"inferred). If a load-bearing fact is genuinely unfindable, write "
        f"'Info not publicly available' + confidence 'Unknown' — never invent it.\n\n"
        f"=== INPUTS — INTERNAL RESEARCH / CONTEXT ===\n{research or '(no internal notes pasted — research the company from public sources using web_search)'}\n"
        f"{crm_block}{meeting_block}\n\n"
        f"=== JSON SCHEMA (fill exactly this shape; keys starting with _ are guidance, do NOT output them) ===\n{BRIEF_JSON_SCHEMA}\n\n"
        f"Return ONLY the JSON object as your final message. No prose before or after, "
        f"no markdown code fences. Must parse with json.loads()."
    )


def _build_update_prompt(existing_brief_text: str, call_notes: str, company: str) -> str:
    """Compose the user-turn prompt for a post-call update — returns updated JSON."""
    today = datetime.now().strftime("%Y-%m-%d")
    return (
        f"Update the existing Prospect Brief for **{company or '<NAME>'}** with new "
        f"call notes from today ({today}).\n\n"
        f"**USER EDITS ARE AUTHORITATIVE — INCREMENTAL UPDATE ONLY.** The "
        f"existing brief text below is what currently lives in the Doc. "
        f"Between bot generations, the salesperson manually edits the Doc — "
        f"fixing facts, tightening prose, adding the right framing, removing "
        f"things they don't agree with. Their edits are AUTHORITATIVE. Treat "
        f"the existing brief as the new baseline; do NOT rewrite content "
        f"that's already there.\n\n"
        f"Signals that text in the existing brief is a USER EDIT (preserve "
        f"verbatim):\n"
        f"  • Specific numbers / dates / proper nouns the bot wouldn't have "
        f"invented (e.g. '₹6,057 Cr FY26', 'Founded 1991 (K Raheja Corp)', "
        f"'INTUNE at 84 stores', 'India Weds ₹300 Cr')\n"
        f"  • Named events / programmes the salesperson knows about (e.g. "
        f"'Shoppers Stop 2.0 relaunch 2024', 'BCG transformation partnership')\n"
        f"  • Concrete quote-style framings ('Anchor on Personal Shopper at "
        f"₹1,200 Cr', 'lead with the loss-making INTUNE EBITDA frame')\n"
        f"  • Compact phrasing that's tighter than typical bot output\n"
        f"  • Anything that contradicts general public info but matches what "
        f"the salesperson would know from inside the room\n\n"
        f"Your job is to ADD what the new call notes surfaced — NOT to "
        f"rewrite the brief from scratch. For each section: start with the "
        f"existing text. Where the new notes add an item → APPEND it. Where "
        f"the new notes upgrade an Inferred fact to Confirmed → UPDATE the "
        f"confidence on that row, keep the user's wording. Where the new "
        f"notes contradict a fact → flag in Conflicts & Unknowns showing both. "
        f"Only rewrite a cell if the new call notes contain a specific "
        f"contradiction or upgrade. Leave the rest as the user wrote it.\n\n"
        f"If unsure whether a phrase is bot- or user-written → ASSUME USER and "
        f"preserve. False preservation is cheap (you reuse good prose); false "
        f"rewrite is expensive (the user loses work and has to redo it).\n\n"
        f"Diff the notes against the discovery agenda. For each open question:\n"
        f"- Answered → move it into the fact tables, upgrade Confidence to Confirmed, "
        f"strike from the agenda.\n"
        f"- Contradicted → update the fact and flag in Conflicts & Unknowns.\n"
        f"- Unanswered → leave in the agenda for the next call.\n"
        f"Capture anything new the call surfaced (pains, people, systems, agents, "
        f"competitors, budget/timeline).\n\n"
        f"Re-check the product route — new info may shift All-e ↔ KG or open the "
        f"layered angle. Update the CFO metric if needed.\n\n"
        f"**BACKFILL THE INCUMBENCY + BUYING-GROUP FIELDS (older briefs predate "
        f"them, and the user may have added this as free text — pull it into the "
        f"structured fields, don't leave it stranded):**\n"
        f"(a) **incumbency_map** — for every major AI / commerce / data platform they "
        f"run, name the external SI / agency that built it AND the internal owner, "
        f"with a contested / greenfield / ally-able verdict. Take anything the user "
        f"already wrote (e.g. 'built by Devoteam', 'owned by Head of Technology') and "
        f"RESEARCH the rest. These SIs are the real competition.\n"
        f"(b) **people_path_in** — surface the FULL buying group: the economic buyer "
        f"(who signs), the tech owner (CTO / Head of Tech), and each incumbent-"
        f"platform owner — not just the meeting attendee — each tagged with how to "
        f"play them (champion / signer / landmine / ally).\n"
        f"(c) **product_route / wedge** — pick the lane with real pain AND no "
        f"entrenched incumbent; NAME the contested space you're avoiding and who owns "
        f"it; prefer the greenfield B2B / distribution lane over a contested B2C "
        f"pain. If the user's edits already argue this, keep their call.\n\n"
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

    def _news_card_html() -> str:
        """Build the 'While you wait' commerce-tech story card. Pulls
        a fresh story via Claude + web_search (cached 1h). Honest
        fallback when fetch fails — never fabricates content."""
        s = _fetch_commerce_tech_story()
        if not s:
            # Honest fallback — no fake content
            return """
            <div style='background:#f5f5f5;border:1px solid #ddd;
            border-radius:12px;padding:18px 22px;margin-top:36px;
            font-size:10pt;line-height:1.5;color:#666;font-style:italic;'>
              📰 Couldn't fetch today's commerce-tech news right now.
              It'll be back next time you load the page. Either web_search
              is rate-limited or the day's headlines aren't surfacing
              anything substantive yet.
            </div>
            """
        _src_link = (
            f"<div style='margin-top:12px;font-size:9pt;'>"
            f"🔗 <a href='{s['source_url']}' target='_blank' "
            f"style='color:#2a522a;text-decoration:none;border-bottom:"
            f"1px dotted #5a8c5a;'>Source: {s['source_label']} →</a>"
            f"</div>"
        )
        return f"""
        <div style='background:#eef6ee;border:1px solid #c8e0c8;
        border-radius:12px;padding:18px 22px;margin-top:36px;
        font-size:10.5pt;line-height:1.55;color:#1a1a1a;'>
          <div style='font-size:8.5pt;color:#3a6a3a;font-weight:600;
          letter-spacing:0.5px;margin-bottom:2px;'>
            📰 WHILE YOU WAIT — TODAY IN COMMERCE-TECH · {s['tag']}
          </div>
          <div style='font-size:12pt;font-weight:600;color:#2a522a;
          margin-bottom:8px;'>{s['title']}</div>
          {s['body']}
          <div style='background:#dcefdc;border-left:3px solid #5a8c5a;
          padding:8px 12px;margin-top:12px;font-size:9.5pt;line-height:1.5;'>
            <strong>Why this matters for Graas:</strong> {s['why']}
          </div>
          {_src_link}
        </div>
        """

    def _render_brief(html: str, company: str, mode_label: str):
        # When no brief has been generated yet (or after Clear), show a warm
        # explainer in the preview column that doubles as the "fill in the
        # form" guidance + sets the mental model that edits in Drive ARE
        # picked up on the next regen. Disappears once html is set.
        if not html:
            placeholder.markdown(
                """
                <div style='background:#eaf2ff;border:1px solid #c8d4ff;
                border-radius:10px;padding:14px 18px;margin-top:4px;
                font-size:10pt;line-height:1.5;color:#1a1a1a;'>
                  <div style='font-size:10.5pt;font-weight:600;color:#2742FF;
                  margin-bottom:6px;'>Fill in the form on the left → click
                  Build brief (or Update from call notes).</div>
                  The generated brief will render here.
                </div>
                <div style='background:#f9f7ee;border:1px solid #e9dfb8;
                border-radius:12px;padding:18px 22px;margin-top:18px;
                font-size:10.5pt;line-height:1.55;color:#1a1a1a;'>
                  <div style='font-size:12pt;font-weight:600;color:#7a5c00;
                  margin-bottom:8px;'>🤖 Yo — while I cook this up…</div>
                  When the brief lands in Drive, <strong>hammer it</strong>
                  — edit, delete, rewrite anything I got wrong, padded out,
                  or repeated. I read your edits next time you regen and
                  use them as my new baseline. The more you trim my fluff,
                  the sharper I get.
                  <br><br>
                  <em>🤝 Don't hold back. I'm here to learn from you, not
                  the other way round.</em>
                  <div style='font-size:9pt;color:#666;margin-top:14px;
                  font-style:italic;'>
                    💡 Paragraph too long? Chop it to a phrase. I'll pick
                    up the pattern.
                  </div>
                </div>
                """ + _news_card_html() + """
                """,
                unsafe_allow_html=True,
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
            from services.sheets_client import fetch_drive_doc_text, fetch_crm_notes_link
            existing_text = fetch_drive_doc_text(doc_id)
            if not existing_text:
                st.error(f"Could not fetch the existing brief at `{doc_id}`. "
                         f"Check the URL/ID and that the service account has access.")
                st.stop()
            # Auto-pull CRM col K (Granola / Google Doc / other notes link)
            # so the salesperson doesn't have to copy-paste. The fetched
            # content is APPENDED to whatever they typed in the call notes
            # textarea — both sources merge into the input to Claude.
            _crm_notes_link = (crm_data or {}).get("notes_link", "")
            _src_type, _fetched_text = (None, "")
            if _crm_notes_link:
                _src_type, _fetched_text = fetch_crm_notes_link(_crm_notes_link)
            if _fetched_text:
                call_notes = (
                    f"=== CALL NOTES FROM CRM (col K, auto-pulled from "
                    f"{_src_type or 'link'}: {_crm_notes_link}) ===\n"
                    f"{_fetched_text}\n\n"
                    f"=== ADDITIONAL NOTES (pasted by user) ===\n"
                    f"{call_notes}"
                )
                st.session_state["last_crm_notes_pull"] = (
                    "ok", _src_type or "link", len(_fetched_text)
                )
            elif _crm_notes_link:
                st.session_state["last_crm_notes_pull"] = (
                    "fail", _src_type or "link", 0
                )
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

            # Sanity-check mandatory fields are populated (two-pager schema)
            required_keys = ["company", "summary_boxes", "key_people",
                             "stack", "graas_fit", "do_not",
                             "wedges_worth_exploring", "discovery"]
            missing_required = [k for k in required_keys if not brief_data.get(k)]
            if missing_required:
                st.warning(
                    "Brief generated but missing required fields: "
                    f"`{', '.join(missing_required)}`. The Doc will still render — "
                    "consider regenerating with more research notes."
                )

            # Inject timeline metadata from the CRM into brief_data so the
            # renderer can show a Timeline section. Combines first-conv +
            # last-conv from the pipeline sheet with post_call_log dates +
            # today — gives the salesperson temporal anchoring (how long
            # this deal has been running, days-since-last-touch, etc.)
            # without any LLM involvement (all dates are known facts).
            brief_data["_timeline_meta"] = {
                "first_conv": (crm_data or {}).get("first_conv", ""),
                "latest_conv": (crm_data or {}).get("latest_conv", ""),
                "today": f"{datetime.now():%Y-%m-%d}",
            }

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
                    grant_domain_access,
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
                        if BRIEF_SHARE_DOMAIN:
                            grant_domain_access(existing_doc_id, BRIEF_SHARE_DOMAIN)
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
                            if BRIEF_SHARE_DOMAIN:
                                grant_domain_access(_new_id, BRIEF_SHARE_DOMAIN)
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

            st.session_state["last_pc_attempt_outcome"] = {"status": "ok"}
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
            st.session_state["last_pc_attempt_outcome"] = {
                "status": "error", "message": str(e),
            }
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

        # Surface CRM col-K notes auto-pull status (Granola / Google Doc /
        # other link auto-fetched before generation). Best-effort — only
        # shown when something was attempted.
        _np = st.session_state.get("last_crm_notes_pull")
        if _np:
            _nkind, _ntype, _nchars = _np
            if _nkind == "ok":
                st.caption(
                    f"📎 Pulled notes from CRM col K ({_ntype}, "
                    f"{_nchars:,} chars) — merged with your call-notes input."
                )
            elif _nkind == "fail":
                st.caption(
                    f"📎 CRM col K had a {_ntype} link but I couldn't fetch "
                    f"it — used only your pasted call notes."
                )

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
                          "last_pipeline_writeback",
                          "last_crm_notes_pull"):
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
                        if BRIEF_SHARE_DOMAIN:
                            from services.sheets_client import grant_domain_access as _gda
                            _gda(st.session_state["last_brief_doc_id"], BRIEF_SHARE_DOMAIN)
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
                            if BRIEF_SHARE_DOMAIN:
                                from services.sheets_client import grant_domain_access as _gda
                                _gda(res["doc_id"], BRIEF_SHARE_DOMAIN)
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
