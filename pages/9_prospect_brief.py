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

The skill itself lives in content/skills/prospect-research-brief/SKILL.md;
the HTML scaffold in content/skills/prospect-research-brief/assets/.
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


@st.cache_data(ttl=86400)
def load_skill() -> tuple[str, str]:
    """Return (SKILL.md text, brief_template.html text). Cached for the day."""
    skill_md = SKILL_DIR / "SKILL.md"
    tmpl = SKILL_DIR / "assets" / "brief_template.html"
    if not skill_md.exists() or not tmpl.exists():
        return "", ""
    return skill_md.read_text(encoding="utf-8"), tmpl.read_text(encoding="utf-8")


SKILL_TEXT, TEMPLATE_HTML = load_skill()
if not SKILL_TEXT or not TEMPLATE_HTML:
    st.error(
        f"Could not load skill files from `{SKILL_DIR}`. "
        f"Expected `SKILL.md` and `assets/brief_template.html`."
    )
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
    # Picker from CRM + free-text fallback
    crm_names = [name for name, _ in CRM]
    selected_company = st.selectbox(
        "Pick a company (or type to add one not in CRM)",
        ["— pick or type —"] + crm_names + ["+ Other (type below)"],
        key="brief_company_picker",
    )
    custom_company = ""
    crm_data = {}
    if selected_company == "+ Other (type below)":
        custom_company = st.text_input("Company name *", key="brief_custom_company")
    elif selected_company != "— pick or type —":
        crm_data = next((d for n, d in CRM if n == selected_company), {})

    company_name = custom_company if custom_company else (
        selected_company if selected_company not in ("— pick or type —", "+ Other (type below)") else ""
    )

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
        research_text = st.text_area(
            "Research notes (paste anything: website blurb, LinkedIn, prior emails, "
            "industry profile, news clippings, screenshots-of-PDFs as text)",
            key="brief_research_text",
            height=300,
            placeholder="e.g.\n"
                        "- HQ in Mumbai, ~$290M revenue (Euromonitor) vs $50-100M (LeadIQ) — conflicting\n"
                        "- ~19,000 dealers on credit terms, distributor network across 8 states\n"
                        "- SAP since 2015, Salesforce CRM, proprietary field app\n"
                        "- Saw on LinkedIn: hiring head of e-commerce; CTO posted about agentic AI in March\n"
                        "- Possible champion: VP Sales (met at retail summit Apr 24)",
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


def _build_new_brief_prompt(crm_data: dict, research: str, company: str) -> str:
    """Compose the user-turn prompt for a fresh pre-call brief."""
    today = datetime.now().strftime("%Y-%m-%d")
    crm_block = ""
    if crm_data:
        crm_block = (
            "\n[CRM context already known about this company from the Graas pipeline:]\n"
            + json.dumps({k: v for k, v in crm_data.items() if v}, indent=2)
        )

    return (
        f"Build a pre-call Prospect Research Brief for **{company or '<NAME>'}**.\n"
        f"Today is {today}. Set the status line to *Pre-call draft*.\n\n"
        f"Use the HTML scaffold below — replace EVERY [placeholder] with real content "
        f"derived from the inputs. Delete bracketed hints, filler captions, and any "
        f"section/option/row that doesn't apply. Keep only the matching Type, Motion, "
        f"and the matching B2B-or-B2C order-flow line. Output a clean, finished HTML "
        f"brief — no brackets, no instructions, no scaffold markers. 2-3 pages.\n\n"
        f"=== INPUTS — RESEARCH ===\n{research or '(no extra research pasted — use the CRM context + your general knowledge of this company)'}\n"
        f"{crm_block}\n\n"
        f"=== HTML SCAFFOLD ===\n{TEMPLATE_HTML}\n\n"
        f"Return ONLY the filled HTML brief. No prose before or after, no markdown code "
        f"fences. The output must start with `<html>` (or `<!DOCTYPE html>`) and be a "
        f"single self-contained HTML document."
    )


def _build_update_prompt(existing_html: str, call_notes: str, company: str) -> str:
    """Compose the user-turn prompt for a post-call update."""
    today = datetime.now().strftime("%Y-%m-%d")
    return (
        f"Update the existing Prospect Brief for **{company or '<NAME>'}** with new "
        f"call notes from today ({today}).\n\n"
        f"Diff the notes against the discovery agenda. For each open question:\n"
        f"- Answered → move it into the fact tables, upgrade its Confidence to "
        f"Confirmed, strike it from the agenda.\n"
        f"- Contradicted → update the fact and flag in Conflicts & Unknowns.\n"
        f"- Unanswered → leave it in the agenda for the next call.\n"
        f"Capture anything new the call surfaced (pains, people, systems, an existing "
        f"agent, a competitor, budget/timeline).\n\n"
        f"Re-check the product route — new info may shift All-e ↔ KG or open the "
        f"layered angle. Update the CFO metric line if needed.\n\n"
        f"Decide and record the **Next step** explicitly (another discovery call / "
        f"demo / POC scoping / solutioning / park-or-disqualify) with one line on why.\n\n"
        f"Update the status line: append `→ Post call-N — {today}` where N is the "
        f"next number after the latest in the existing status. Keep all prior status "
        f"entries intact.\n\n"
        f"Keep the brief 2-3 pages.\n\n"
        f"=== NEW CALL NOTES ===\n{call_notes}\n\n"
        f"=== EXISTING BRIEF (HTML) ===\n{existing_html}\n\n"
        f"Return ONLY the updated HTML brief. No prose before or after, no markdown "
        f"code fences. Single self-contained HTML document."
    )


def _clean_brief_html(text: str) -> str:
    """Strip code fences and any pre/post commentary so we get clean HTML."""
    s = text.strip()
    # Remove ```html ... ``` or ``` ... ``` wrappers
    s = re.sub(r"^```(?:html|HTML)?\s*\n", "", s)
    s = re.sub(r"\n```\s*$", "", s)
    # If response includes prose then HTML, snip from the first <html or <!DOCTYPE
    lower = s.lower()
    for marker in ("<!doctype html", "<html"):
        idx = lower.find(marker)
        if idx > 0:
            s = s[idx:]
            break
    return s.strip()


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
            user_prompt = _build_new_brief_prompt(crm_data, research_text, company_name)
        else:
            doc_id = _extract_doc_id(existing_brief_id)
            if not doc_id:
                st.error("Paste a valid Google Doc URL or ID for the existing brief.")
                st.stop()
            if not call_notes.strip():
                st.error("Paste the new call notes.")
                st.stop()
            from services.sheets_client import fetch_drive_doc_html
            existing_html = fetch_drive_doc_html(doc_id)
            if not existing_html:
                st.error(f"Could not fetch the existing brief at `{doc_id}`. "
                         f"Check the URL/ID and that the service account has access.")
                st.stop()
            user_prompt = _build_update_prompt(existing_html, call_notes, company_name or "<this prospect>")

        # Call Claude
        with st.spinner(f"{'Building' if mode.startswith('🆕') else 'Updating'} brief — researching, classifying, drafting…"):
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                system_prompt = SKILL_TEXT
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=6000,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                raw_text = response.content[0].text
                brief_html = _clean_brief_html(raw_text)
                st.session_state["last_brief_html"] = brief_html
                st.session_state["last_brief_company"] = company_name
                st.session_state["last_brief_mode"] = ("Pre-call draft" if mode.startswith("🆕") else f"Post-call update — {datetime.now():%Y-%m-%d}")
                # When updating, remember the existing doc id so "Save back" can patch it
                if mode.startswith("🔁"):
                    st.session_state["last_brief_doc_id"] = _extract_doc_id(existing_brief_id)
                else:
                    st.session_state["last_brief_doc_id"] = ""
                st.session_state["last_brief_doc_url"] = ""
                st.rerun()
            except Exception as e:
                st.error(f"Brief generation failed: {e}")

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
                    from services.sheets_client import create_google_doc_from_html, update_google_doc_html
                    title = (
                        f"Prospect Brief — {st.session_state['last_brief_company']} — "
                        f"{datetime.now():%Y-%m-%d}"
                    )
                    share_with = [
                        e.strip() for e in (share_with_raw or "").split(",")
                        if e.strip() and "@" in e
                    ]
                    if st.session_state.get("last_brief_doc_id"):
                        res = update_google_doc_html(
                            st.session_state["last_brief_doc_id"],
                            st.session_state["last_brief_html"],
                        )
                        if res["ok"]:
                            url = f"https://docs.google.com/document/d/{st.session_state['last_brief_doc_id']}/edit"
                            st.session_state["last_brief_doc_url"] = url
                            st.success(f"✅ Updated existing Doc. [Open it →]({url})")
                        else:
                            st.error(f"Update failed: {res['error']}")
                    else:
                        res = create_google_doc_from_html(
                            html_body=st.session_state["last_brief_html"],
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

        # Download as HTML
        with save_cols[1]:
            fname = f"prospect-brief-{(st.session_state['last_brief_company'] or 'untitled').lower().replace(' ', '-')}-{datetime.now():%Y-%m-%d}.html"
            st.download_button(
                "⬇️ Download HTML",
                data=st.session_state["last_brief_html"],
                file_name=fname,
                mime="text/html",
                use_container_width=True,
            )

        # Clear
        with save_cols[2]:
            if st.button("🗑 Clear", use_container_width=True, key="brief_clear_btn"):
                for k in ("last_brief_html", "last_brief_company", "last_brief_mode",
                          "last_brief_doc_url", "last_brief_doc_id"):
                    st.session_state.pop(k, None)
                st.rerun()

        if st.session_state.get("last_brief_doc_url"):
            st.caption(f"📄 Latest Doc: {st.session_state['last_brief_doc_url']}")
