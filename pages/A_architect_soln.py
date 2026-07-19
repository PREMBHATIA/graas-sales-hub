"""Architect a Soln — turn a Prospect Brief into a structured Solution Doc.

The Soln Doc sits between the Brief (facts) and the Proposal (commercials):

    Prospect Brief  →  Solution Architecture  →  Create Proposal
    (confirmed         (what we build,           (what we charge,
     facts)             KPIs, gaps, timeline)     SOW, commercials)

The page is a structured generator, not a chat:
  1. Load brief (Drive URL or paste text)
  2. Optionally pick reference proposals to pattern-match against
  3. Optionally add new context (post-brief meeting notes, eng inputs)
  4. Click Architect → Claude returns JSON → renderer turns it into a DOCX
  5. Preview inline → Save to Drive → Share with team

Deliberately scoped OUT:
  - No pricing / commercials (→ Create Proposal)
  - No objection handling (live coaching is a different surface)
  - No demo planning, no strategic emails

The skill is content/skills/all-e-solutions-architect/SKILL.md.
The renderer is services/soln_renderer.py.
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
st.markdown("## 🏗️ Architect a Soln")
st.caption("Turn a Prospect Brief into a structured Solution Doc — what we build, "
           "KPIs each agent needs to hit, what data gaps are blocking us, and the timeline.")

with st.expander("ℹ️ How to use this — read once, then collapse", expanded=False):
    st.markdown(
        "#### What this does\n"
        "Takes a finalised Prospect Brief and produces a **Solution Architecture Doc** "
        "with four sections:\n"
        "1. **Core functionality** — per-agent: persona, surfaces, what it does, phase\n"
        "2. **Key agent KPIs** — target + baseline + where the baseline came from\n"
        "3. **Missing fields & data gaps** — what to ask the customer for before final commercials\n"
        "4. **Timeline** — phase, duration, milestone\n\n"
        "#### Workflow position\n"
        "**Prospect Brief → Architect a Soln → Create Proposal.** "
        "This page assumes you have a brief. Without one, the architecture is "
        "hand-wavy. Load the brief Doc URL or paste the text.\n\n"
        "#### What this *doesn't* do\n"
        "- ❌ Pricing / commercials → that's **Create Proposal**\n"
        "- ❌ Objection handling, demo planning, strategic emails → out of scope\n"
        "- ❌ Discovery prep → that's **Create Prospect Brief**"
    )

# ── Anthropic key ─────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
try:
    if hasattr(st, "secrets") and "ANTHROPIC_API_KEY" in st.secrets:
        ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass

if not ANTHROPIC_API_KEY:
    st.warning("Add `ANTHROPIC_API_KEY` to `.streamlit/secrets.toml` or `.env` to enable the architect.")
    st.stop()


# ── Load the All-e Solutions Architect skill ─────────────────────────────────
@st.cache_data(ttl=60)
def load_skill_prompt() -> str:
    """SKILL.md as the foundation system prompt."""
    skill_path = Path(__file__).parent.parent / "content" / "skills" / "all-e-solutions-architect" / "SKILL.md"
    if not skill_path.exists():
        return ""
    return skill_path.read_text(encoding="utf-8")


SKILL_CONTENT = load_skill_prompt()
if not SKILL_CONTENT:
    st.error("Could not load all-e-solutions-architect SKILL.md from "
             "`content/skills/all-e-solutions-architect/`. Check the file exists.")
    st.stop()


# ── Drive folder config ──────────────────────────────────────────────────────
DEFAULT_DRIVE_FOLDER = os.getenv(
    "PROSPECT_BRIEF_DRIVE_FOLDER",
    "0ABwowt8s9tmzUk9PVA",
)
REFERENCE_PROPOSALS_FOLDER = os.getenv(
    "REFERENCE_PROPOSALS_FOLDER",
    "1tBMrcpiIDVhg5e0-N1ytjuzbDexQyheX",
)


# ── Reference proposals (cached helpers) ──────────────────────────────────────
@st.cache_data(ttl=3600)
def list_reference_proposals() -> list:
    from services.sheets_client import list_drive_folder_docs
    return list_drive_folder_docs(REFERENCE_PROPOSALS_FOLDER)


@st.cache_data(ttl=3600)
def fetch_reference_text(doc_id: str) -> str:
    from services.sheets_client import fetch_drive_doc_text
    return fetch_drive_doc_text(doc_id)


def _clean_proposal_name(raw: str) -> str:
    s = raw
    for prefix in ("Copy of ", "Copy of"):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
            break
    return s


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
    if re.match(r"^[A-Za-z0-9_-]{20,}$", s):
        return s
    return ""


# ── JSON schema (Claude fills this exactly) ──────────────────────────────────
SOLN_JSON_SCHEMA = """{
  "company": "string — display name (use the brief's company)",
  "header": {
    "date_prepared": "YYYY-MM-DD",
    "based_on_brief": "Brief URL OR 'pasted text' if user pasted directly",
    "status": "Draft v1"
  },
  "executive_summary": "ONE paragraph, 2-3 sentences naming (a) what we propose to build for this customer in their language, (b) the one CFO metric it moves, and (c) the wedge agent or Phase 1 capability. No marketing language.",
  "core_functionality": [
    {
      "agent_name": "Specific agent name (e.g. 'Dealer Ordering Agent', not 'AI Bot')",
      "persona": "Who uses it (Dealers / Distributors / FSAs / Retailers / Consumers / Support)",
      "surfaces": ["WhatsApp", "Voice", "SFA mobile", "Web", "LINE", "etc — actual surfaces, not vague channels"],
      "what_it_does": "PHRASE 10-25 words — capability + key behaviour. e.g. 'Captures orders conversationally; validates credit limit against SAP; books order; notifies dealer of dispatch.'",
      "phase": "Phase 1 (Pilot) / Phase 2 / Production / Future"
    }
  ],
  "key_agent_kpis": [
    {
      "agent": "Which agent this KPI measures (matches a core_functionality entry)",
      "kpi": "Specific measurable metric — e.g. 'Order containment rate (% orders captured via agent vs phone)'",
      "target": "Number + timeframe — e.g. '60% within 90 days post-go-live'",
      "baseline": "Current state — e.g. '0% (all phone today)' OR 'TBD — to be established in pilot week 1-2'",
      "baseline_source": "Where the baseline came from — e.g. 'Confirmed via brief: persona row Dealers' OR 'TBD — Phase 1 measurement'"
    }
  ],
  "missing_fields": [
    {
      "field": "Specific data point or system access needed — e.g. 'SAP order-create API availability + auth model'",
      "why_needed": "Why this blocks the build / final commercials — phrase as the impact, not the technicality",
      "owner": "Who on customer side owns this — e.g. 'Customer IT (Vikram Iyer)' OR 'Unassigned — need to identify in next call'",
      "ask": "Concrete next-call ask — e.g. 'Confirm REST/SOAP API exists; share auth model + sandbox creds'"
    }
  ],
  "timeline": [
    {"phase": "Discovery + scoping", "duration": "2 weeks", "milestone": "Signed-off SOW"},
    {"phase": "Build + UAT", "duration": "6 weeks", "milestone": "Pilot agent live in UAT"},
    {"phase": "Pilot run", "duration": "4 weeks", "milestone": "KPI baseline established"},
    {"phase": "Production handover", "duration": "2 weeks", "milestone": "Live in primary region"}
  ],
  "reference_patterns": ["Names of reference proposals consulted, if any. Omit if none."]
}"""


def _build_soln_prompt(brief_text: str, brief_source: str, company: str,
                       additional_context: str, reference_docs: list) -> str:
    """Compose the user-turn prompt for the architect."""
    today = datetime.now().strftime("%Y-%m-%d")

    ref_block = ""
    if reference_docs:
        ref_block = "\n=== REFERENCE PROPOSALS (draw architecture patterns from these) ===\n"
        for d in reference_docs:
            ref_block += f"\n--- BEGIN: {d['name']} ---\n{d['text']}\n--- END ---\n"

    extra_block = ""
    if additional_context.strip():
        extra_block = f"\n=== ADDITIONAL CONTEXT (post-brief meeting notes / eng inputs / constraints) ===\n{additional_context.strip()}\n"

    return (
        f"Architect a solution for **{company or '<NAME>'}**. Today is {today}.\n\n"
        f"You have a finalised Prospect Brief below. Use it as the **source of truth** "
        f"for facts about this customer — Type, Motion, persona & order flow, pain → "
        f"capability → CFO metric, tech stack, conflicts & unknowns. Don't re-derive "
        f"any of that; design what to BUILD.\n\n"
        f"**Output rules:**\n"
        f"- Return a JSON object matching the schema below. No prose, no markdown fences.\n"
        f"- **Core functionality:** one row per distinct agent. Each agent has a "
        f"specific name (not 'AI assistant'), a real persona from the brief, concrete "
        f"surfaces (WhatsApp / Voice / SFA / etc — not 'AI channel'), and a phrase "
        f"describing what it does + key behaviour. Phase each one (Phase 1 / 2 / "
        f"Production). 2-5 agents is the typical range — don't pad.\n"
        f"- **Key agent KPIs:** 1-3 per agent. Each KPI must have a target AND a "
        f"baseline (or 'TBD — established in pilot week N'). Baseline source notes "
        f"WHERE the number came from (the brief, an industry benchmark, or TBD).\n"
        f"- **Missing fields:** scan the brief for anything marked Unknown / Info not "
        f"publicly available, anything in Conflicts & Unknowns, persona/flow leak "
        f"points where the leak is unverified, and tech-stack uncertainty (e.g. API "
        f"availability). Each gap = a field name, why it blocks, who on customer side "
        f"owns it, and the concrete next-call ask. Be specific.\n"
        f"- **Timeline:** realistic phase durations. Default 14-week Pilot pattern is "
        f"(2w Discovery → 6w Build+UAT → 4w Pilot → 2w Production handover); adjust "
        f"based on integration complexity from the brief.\n"
        f"- **Executive Summary:** 2-3 sentences, customer's language, names the CFO "
        f"metric and the wedge agent.\n\n"
        f"=== PROSPECT BRIEF (source of truth) ===\n"
        f"Source: {brief_source}\n\n"
        f"{brief_text}\n"
        f"{extra_block}{ref_block}\n"
        f"=== JSON SCHEMA (return exactly this shape) ===\n{SOLN_JSON_SCHEMA}\n\n"
        f"Return ONLY the JSON object. No prose, no markdown fences."
    )


def _extract_json_object(text: str) -> dict:
    """Extract the first JSON object from a model response."""
    s = (text or "").strip()
    s = re.sub(r"^```(?:json|JSON)?\s*\n", "", s)
    s = re.sub(r"\n```\s*$", "", s)
    s = s.strip()
    start = s.find("{")
    if start < 0:
        raise ValueError("No JSON object found in response")
    try:
        return json.loads(s[start:])
    except json.JSONDecodeError:
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
        raise ValueError("Couldn't find a balanced JSON object")


# ── Layout: form on left, output on right ─────────────────────────────────────
left, right = st.columns([5, 6])

with left:
    st.markdown("### 1. Brief context")
    st.caption("Load the Prospect Brief (the Drive URL is the fastest path).")

    brief_url = st.text_input(
        "Prospect Brief — Google Doc URL or ID",
        key="soln_brief_url",
        placeholder="https://docs.google.com/document/d/<DOC_ID>/edit",
        help="Brief generated by the Create Prospect Brief page. We fetch it as text.",
    )

    brief_paste = st.text_area(
        "…or paste the brief text directly (fallback if Drive isn't accessible)",
        key="soln_brief_paste",
        height=160,
        placeholder="Paste the full brief content here — only used if the URL above is empty.",
    )

    st.markdown("### 2. Company")
    company_name = st.text_input(
        "Company (auto-detected from brief; override if needed)",
        key="soln_company_name",
        placeholder="e.g. PT Propan Raya",
    )

    st.markdown("### 3. Reference patterns (optional)")
    ref_options = list_reference_proposals()
    if ref_options:
        picked_ref_names = st.multiselect(
            "Reference proposals to draw architecture patterns from",
            options=[_clean_proposal_name(r["name"]) for r in ref_options],
            key="soln_picked_refs",
            help="Selected proposals get loaded so the architect can match patterns "
                 "(Castrol-style voice positioning, Nippon-style phasing, etc.).",
        )
    else:
        picked_ref_names = []
        st.caption("⚠️ No reference proposals in the Drive folder.")

    st.markdown("### 4. Additional context (optional)")
    additional_context = st.text_area(
        "New meeting notes / engineering inputs / specific constraints",
        key="soln_additional",
        height=120,
        placeholder="e.g. 'Post-brief call with their CTO: confirmed SAP S/4HANA has "
                    "REST APIs; vendor onboarding is a 4-week ABU process; they want "
                    "WhatsApp voice + text as the wedge.'",
    )

    st.markdown("### 5. Action")
    architect_clicked = st.button(
        "🏗️ Architect the solution",
        type="primary",
        use_container_width=True,
        key="soln_arch_btn",
    )


# Resolve selected reference proposals → full texts
reference_docs = []
if picked_ref_names:
    name_to_doc = {_clean_proposal_name(r["name"]): r for r in ref_options}
    for name in picked_ref_names:
        meta = name_to_doc.get(name)
        if not meta:
            continue
        text = fetch_reference_text(meta["id"])
        if text:
            reference_docs.append({"name": name, "text": text})


# ── Output side ───────────────────────────────────────────────────────────────
with right:
    st.markdown("### Solution Doc Preview")

    if "last_soln_html" not in st.session_state:
        st.session_state["last_soln_html"] = ""
        st.session_state["last_soln_docx"] = b""
        st.session_state["last_soln_company"] = ""
        st.session_state["last_soln_doc_url"] = ""
        st.session_state["last_soln_doc_id"] = ""

    placeholder = st.empty()

    def _render_soln(html: str, company: str):
        if not html:
            placeholder.info(
                "Load a brief on the left and click **Architect the solution**. "
                "The generated solution doc renders here."
            )
            return
        placeholder.markdown(f"**{company}** — Solution Architecture", unsafe_allow_html=False)
        import streamlit.components.v1 as components
        components.html(html, height=800, scrolling=True)

    # Trigger
    if architect_clicked:
        # Resolve brief text — URL takes precedence, falls back to paste
        brief_text = ""
        brief_source = ""
        doc_id = _extract_doc_id(brief_url)
        if doc_id:
            from services.sheets_client import fetch_drive_doc_text
            brief_text = fetch_drive_doc_text(doc_id)
            if brief_text:
                brief_source = f"Drive doc {doc_id}"
            else:
                st.error(
                    f"Could not fetch the brief at `{doc_id}`. Check the URL and "
                    "that the service account has access. You can paste the brief "
                    "text into the fallback box instead."
                )
                st.stop()
        elif brief_paste.strip():
            brief_text = brief_paste.strip()
            brief_source = "pasted text"
        else:
            st.error(
                "Load a brief first — either paste a Drive URL or paste the brief "
                "text into the fallback box. Architecting without a brief produces "
                "hand-wavy output."
            )
            st.stop()

        # If company name wasn't set, try to grab from the brief text
        if not company_name.strip():
            m = re.search(r"Prospect Brief\s*[—\-]\s*([^\n\r]+)", brief_text)
            if m:
                company_name = m.group(1).strip()

        user_prompt = _build_soln_prompt(
            brief_text=brief_text,
            brief_source=brief_source,
            company=company_name,
            additional_context=additional_context,
            reference_docs=reference_docs,
        )

        status_box = st.status(
            f"Architecting solution for **{company_name or 'this prospect'}**…",
            expanded=True,
        )
        try:
            import anthropic
            import html as _html
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            with status_box:
                activity_box = st.empty()
                activity_lines: list = []

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

                _render_activity()
                _push("📋 Loading brief + reference proposals into context…")
                if reference_docs:
                    _push(f"📚 {len(reference_docs)} reference proposal(s) attached")
                _push("✏️ <b>Drafting solution architecture…</b>")

                text_chars = 0
                with client.messages.stream(
                    model="claude-sonnet-4-6",
                    max_tokens=6000,
                    system=SKILL_CONTENT,
                    messages=[{"role": "user", "content": user_prompt}],
                ) as stream:
                    for event in stream:
                        etype = getattr(event, "type", None)
                        if etype == "content_block_delta":
                            delta = getattr(event, "delta", None)
                            if getattr(delta, "type", None) == "text_delta":
                                text_chars += len(getattr(delta, "text", "") or "")
                                if text_chars and text_chars % 400 < 30 and activity_lines:
                                    if activity_lines[-1].startswith("✏️"):
                                        activity_lines[-1] = f"✏️ <b>Drafting…</b> ({text_chars:,} chars)"
                                        _render_activity()
                    final_message = stream.get_final_message()

            # Extract text
            text_parts = []
            for block in final_message.content:
                if getattr(block, "type", None) == "text":
                    text_parts.append(block.text)
            raw_text = "\n".join(p for p in text_parts if p).strip()

            if not raw_text:
                status_box.update(label="❌ No solution returned", state="error", expanded=True)
                st.error("Claude returned no text. Try again.")
                st.stop()

            try:
                soln_data = _extract_json_object(raw_text)
            except Exception as parse_err:
                status_box.update(label="❌ Couldn't parse JSON", state="error", expanded=True)
                st.error(
                    f"Claude didn't return valid JSON.\n\n**Parse error:** {parse_err}\n\n"
                    f"**First 1500 chars of response:**\n\n{raw_text[:1500]}"
                )
                st.stop()

            # Ensure reference_patterns reflects what we actually passed in
            if reference_docs and not soln_data.get("reference_patterns"):
                soln_data["reference_patterns"] = [d["name"] for d in reference_docs]

            from services.soln_renderer import render_soln_html, render_soln_docx
            try:
                soln_html = render_soln_html(soln_data)
                soln_docx = render_soln_docx(soln_data)
            except Exception as render_err:
                status_box.update(label="❌ Render failed", state="error", expanded=True)
                st.error(f"Got valid JSON but the renderer choked.\n\n**Error:** {render_err}")
                st.stop()

            status_box.update(
                label=f"✅ Solution drafted — {text_chars:,} chars",
                state="complete",
                expanded=False,
            )

            st.session_state["last_soln_data"] = soln_data
            st.session_state["last_soln_html"] = soln_html
            st.session_state["last_soln_docx"] = soln_docx
            st.session_state["last_soln_company"] = company_name or soln_data.get("company", "")
            st.session_state["last_soln_doc_url"] = ""
            st.session_state["last_soln_doc_id"] = ""
            _should_rerun = True
        except Exception as e:
            if type(e).__name__ in ("RerunException", "StopException"):
                raise
            try:
                status_box.update(label="❌ Generation failed", state="error", expanded=True)
            except Exception:
                pass
            st.error(f"Solution generation failed: {e}")
            _should_rerun = False

        if locals().get("_should_rerun"):
            st.rerun()

    _render_soln(
        st.session_state["last_soln_html"],
        st.session_state["last_soln_company"],
    )

    # ── Save / Export ────────────────────────────────────────────────────────
    if st.session_state["last_soln_html"]:
        st.markdown("---")
        st.markdown("### Save")
        save_cols = st.columns([2, 2, 1])

        with save_cols[0]:
            save_label = (
                "🔁 Re-upload to existing Doc"
                if st.session_state.get("last_soln_doc_id")
                else "💾 Create new Google Doc"
            )
            if st.button(save_label, type="primary", use_container_width=True, key="soln_save_btn"):
                with st.spinner("Talking to Drive…"):
                    from services.sheets_client import create_google_doc_from_docx, update_google_doc_docx
                    title = (
                        f"Solution Architecture — {st.session_state['last_soln_company']} — "
                        f"{datetime.now():%Y-%m-%d}"
                    )
                    docx_bytes = st.session_state.get("last_soln_docx", b"")
                    if not docx_bytes:
                        st.error("No DOCX bytes in session — regenerate.")
                        st.stop()
                    if st.session_state.get("last_soln_doc_id"):
                        res = update_google_doc_docx(st.session_state["last_soln_doc_id"], docx_bytes)
                        if res["ok"]:
                            url = f"https://docs.google.com/document/d/{st.session_state['last_soln_doc_id']}/edit"
                            st.session_state["last_soln_doc_url"] = url
                            try:
                                from services.sheets_client import grant_domain_access as _gda
                                _dom = os.getenv("PROSPECT_BRIEF_SHARE_DOMAIN", "graas.ai")
                                if _dom:
                                    _gda(st.session_state["last_soln_doc_id"], _dom)
                            except Exception:
                                pass
                            st.success(f"✅ Updated Doc. [Open it →]({url})")
                        else:
                            st.error(f"Update failed: {res['error']}")
                    else:
                        res = create_google_doc_from_docx(
                            docx_bytes=docx_bytes,
                            title=title,
                            parent_folder_id=DEFAULT_DRIVE_FOLDER,
                            share_with=["prem@graas.ai", "amruta@graas.ai"],
                        )
                        if res["ok"]:
                            st.session_state["last_soln_doc_url"] = res["doc_url"]
                            st.session_state["last_soln_doc_id"] = res["doc_id"]
                            try:
                                from services.sheets_client import grant_domain_access as _gda
                                _dom = os.getenv("PROSPECT_BRIEF_SHARE_DOMAIN", "graas.ai")
                                if res.get("doc_id") and _dom:
                                    _gda(res["doc_id"], _dom)
                            except Exception:
                                pass
                            st.success(f"✅ Created in Drive. [Open it →]({res['doc_url']})")
                        else:
                            st.error(f"Drive create failed: {res.get('error') or 'unknown'}")

        with save_cols[1]:
            fname = f"solution-arch-{(st.session_state['last_soln_company'] or 'untitled').lower().replace(' ', '-')}-{datetime.now():%Y-%m-%d}.docx"
            st.download_button(
                "⬇️ Download DOCX",
                data=st.session_state.get("last_soln_docx", b""),
                file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )

        with save_cols[2]:
            if st.button("🗑 Clear", use_container_width=True, key="soln_clear_btn"):
                for k in ("last_soln_data", "last_soln_html", "last_soln_docx",
                          "last_soln_company", "last_soln_doc_url", "last_soln_doc_id"):
                    st.session_state.pop(k, None)
                st.rerun()

        if st.session_state.get("last_soln_doc_url"):
            st.caption(f"📄 Latest Doc: {st.session_state['last_soln_doc_url']}")

            # Share panel — same Drive notification pattern as Prospect Brief
            with st.expander("📧 Share with the team", expanded=True):
                st.caption(
                    "Adds the recipient as a Doc editor AND sends Google's "
                    "share-notification email."
                )
                preset_emails = [("Prem", "prem@graas.ai"), ("Amruta", "amruta@graas.ai")]
                share_cols = st.columns(len(preset_emails))
                selected_presets: list = []
                for i, (label, email) in enumerate(preset_emails):
                    with share_cols[i]:
                        if st.checkbox(f"{label} ({email})", value=True,
                                       key=f"soln_share_preset_{email}"):
                            selected_presets.append(email)

                extras_raw = st.text_input(
                    "Other emails (optional, comma-separated)",
                    key="soln_share_extras",
                    placeholder="e.g. cofounder@graas.ai",
                )
                extras = [e.strip() for e in (extras_raw or "").split(",") if e.strip() and "@" in e]

                msg = st.text_area(
                    "Message (optional)",
                    key="soln_share_msg",
                    height=70,
                    placeholder=f"e.g. 'Solution architecture for {st.session_state.get('last_soln_company', '<company>')}. "
                                f"Please review the KPIs and missing-fields list.'",
                )

                share_btn_col, _ = st.columns([2, 5])
                with share_btn_col:
                    if st.button("📨 Send share notification", type="primary",
                                 use_container_width=True, key="soln_share_send_btn"):
                        recipients = list(dict.fromkeys(selected_presets + extras))
                        if not recipients:
                            st.warning("Pick at least one recipient.")
                        else:
                            from services.sheets_client import share_drive_file_with_notification
                            with st.spinner(f"Sharing with {len(recipients)} recipient(s)…"):
                                res = share_drive_file_with_notification(
                                    doc_id=st.session_state["last_soln_doc_id"]
                                            or _extract_doc_id(st.session_state["last_soln_doc_url"]),
                                    emails=recipients,
                                    message=msg.strip(),
                                )
                            if res["sent"]:
                                st.success(f"✅ Notified: {', '.join(res['sent'])}")
                            if res["failed"]:
                                for f in res["failed"]:
                                    st.error(f"❌ {f['email']}: {f['error']}")
