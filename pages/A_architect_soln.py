"""Architect a Soln — All-e solutions architect chat.

Uses the all-e-solutions-architect SKILL.md as the system prompt foundation,
augmented with live pipeline + meeting-notes context (same data load as
Ask Graas). Distinct from Ask Graas, which is now cross-product pipeline
Q&A only.

Sit-down workflow: pick a prospect/scenario → ask discovery, scoping,
positioning, objection-handling, pricing-framing questions → chat
streams answers grounded in the All-e three-lever framework, System of
Intelligence model, journey × lever matrix, and the customer-specific
plays in the skill.
"""

import os
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
st.caption("All-e solutions architect — discovery prep, use-case scoping, industry plays, "
           "objection handling, pricing framing. Grounded in the three-lever framework + "
           "real customer references.")

# ── Anthropic key ─────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
try:
    if hasattr(st, "secrets") and "ANTHROPIC_API_KEY" in st.secrets:
        ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass

if not ANTHROPIC_API_KEY:
    st.warning("Add `ANTHROPIC_API_KEY` to `.streamlit/secrets.toml` or `.env` to enable the architect chat.")
    st.stop()


# ── Load the All-e Solutions Architect skill ─────────────────────────────────
@st.cache_data(ttl=86400)
def load_skill_prompt() -> str:
    """Read the all-e-solutions-architect SKILL.md from disk (cached for the day)."""
    skill_path = Path(__file__).parent.parent / "content" / "skills" / "all-e-solutions-architect" / "SKILL.md"
    if not skill_path.exists():
        return ""
    return skill_path.read_text(encoding="utf-8")


SKILL_CONTENT = load_skill_prompt()
if not SKILL_CONTENT:
    st.error("Could not load all-e-solutions-architect SKILL.md from "
             "`content/skills/all-e-solutions-architect/`. "
             "Check the file exists in the repo.")
    st.stop()


# ── Load lightweight pipeline + meeting-notes context (reused from Ask Graas pattern) ──
@st.cache_data(ttl=900)
def load_live_context() -> dict:
    """Pull just enough live data to ground architect answers in real prospects.

    Smaller surface than Ask Graas's load_sales_data — we don't need revenue,
    AR, finance for architecting solutions; we DO need:
      - Active pipeline (which prospects we're talking to + their status)
      - Recent meeting notes (what's actually been said)
    """
    ctx = {}
    sheet_id = os.getenv("ALLE_SHEET_ID", "")
    if not sheet_id:
        return ctx
    try:
        from services.sheets_client import fetch_sheet_tab
        df = fetch_sheet_tab(sheet_id, "Overall Pipeline for IN and SEA")
        if not df.empty:
            if "Active / Dropped" in df.columns:
                df = df[df["Active / Dropped"].astype(str).str.strip().str.lower() == "active"]
            ctx["active_pipeline"] = {
                "rows": len(df),
                "data": df.head(50).to_dict("records"),
                "schema_note": "Columns: Lead name, Vertical, Source of lead, Region (India/SEA), "
                               "Active / Dropped, Lead status (4-TOF / 3-Proposal sent / 2-POC / 1-Pilot), "
                               "First/Latest conv date, Latest Conv details, POC/Proposal/Pilot/Production dates.",
            }
    except Exception as e:
        ctx["active_pipeline"] = f"Error loading pipeline: {e}"

    # Meeting notes from Slack (if configured)
    try:
        from services.slack_notes import load_meeting_notes
        notes = load_meeting_notes(limit=20)
        if notes:
            ctx["recent_meeting_notes"] = notes
    except Exception:
        pass

    return ctx


# ── Build system prompt ───────────────────────────────────────────────────────
def build_system_prompt(live_ctx: dict, reference_docs: list = None) -> str:
    today = datetime.now().strftime("%B %d, %Y")

    # Format live context compactly
    ctx_lines = []
    if "active_pipeline" in live_ctx and isinstance(live_ctx["active_pipeline"], dict):
        ap = live_ctx["active_pipeline"]
        ctx_lines.append(f"\n=== ACTIVE PIPELINE ({ap['rows']} leads) ===")
        ctx_lines.append(ap.get("schema_note", ""))
        ctx_lines.append(f"Data (first 50): {json.dumps(ap['data'][:50], default=str)[:8000]}")

    if "recent_meeting_notes" in live_ctx and isinstance(live_ctx["recent_meeting_notes"], list):
        ctx_lines.append(f"\n=== RECENT MEETING NOTES ({len(live_ctx['recent_meeting_notes'])}) ===")
        for n in live_ctx["recent_meeting_notes"][:15]:
            ctx_lines.append(f"- {n.get('client', '?')} ({n.get('date', '?')}): "
                             f"{(n.get('summary') or '')[:300]}")

    live_block = "\n".join(ctx_lines) if ctx_lines else "(no live pipeline data loaded)"

    # Reference proposals — actual Graas docs the team has shipped. Inject as
    # patterns the architect should draw on (commercial framing, capability
    # bundles, integration scope, voice positioning, etc).
    ref_block = ""
    if reference_docs:
        chunks = ["\n\n============================================================",
                  f"REFERENCE PROPOSALS ({len(reference_docs)} loaded)",
                  "============================================================",
                  "These are real Graas proposals you should draw patterns from when answering.",
                  "Cite them by name when an approach in them maps to the question being asked.",
                  ""]
        for d in reference_docs:
            chunks.append(f"\n--- BEGIN: {d['name']} ---\n{d['text']}\n--- END: {d['name']} ---\n")
        ref_block = "\n".join(chunks)

    return f"""You are the Graas All-e Solutions Architect. Today is {today}.

Your job is to help the team scope, position, and sell All-e — drawing on the
authoritative skill below for the framework, and on the live pipeline + recent
meeting notes for grounding answers in real, current prospects.

When a question is about a specific company, cross-reference the live pipeline
data: their current stage, last conversation, vertical, region — and weave those
specifics into your answer. Don't give generic advice when you have real data to
cite.

============================================================
SKILL: all-e-solutions-architect
============================================================
{SKILL_CONTENT}
============================================================
END SKILL
============================================================

=== LIVE GRAAS CONTEXT (active pipeline + recent meeting notes) ===
{live_block}
=== END LIVE CONTEXT ===
{ref_block}

OUTPUT STYLE:
- Specific, not generic. Quote numbers, name customer references, cite which
  lever and journey stage.
- When asked about a specific prospect: cross-reference the pipeline. Include
  their current Lead status, last conv date, and what's been discussed.
- For discovery prep: give 5-8 tailored questions, 2-3 use cases that map to
  their motion (B2B/GT vs B2C), and one thing to AVOID saying.
- For positioning/pitches: lead with the business pain, show current-vs-agentic
  workflow with real numbers (5-7 days → 3-5 minutes), close with a next step.
- For commercial framing: never lead with pricing. Quantify current cost first,
  then frame ROI.
- Don't say "AI can help with that" without specifying which agent, which
  surface (WhatsApp/LINE/Zalo/web), and which integration (ERP/CRM/DMS).
"""


# ── Reference proposals — pulled from the SalesHub Shared Drive ──────────────
# Folder ID set via env so it's overridable per environment. Default points to
# the 'Reference Proposals / Knowledge Base' folder inside the SalesHub
# Shared Drive that the service account already has access to.
REFERENCE_PROPOSALS_FOLDER = os.getenv(
    "REFERENCE_PROPOSALS_FOLDER",
    "1tBMrcpiIDVhg5e0-N1ytjuzbDexQyheX",
)


@st.cache_data(ttl=3600)
def list_reference_proposals() -> list:
    from services.sheets_client import list_drive_folder_docs
    return list_drive_folder_docs(REFERENCE_PROPOSALS_FOLDER)


@st.cache_data(ttl=3600)
def fetch_reference_text(doc_id: str) -> str:
    from services.sheets_client import fetch_drive_doc_text
    return fetch_drive_doc_text(doc_id)


def _clean_proposal_name(raw: str) -> str:
    """Strip the noise from filenames so the multiselect reads cleanly."""
    s = raw
    for prefix in ("Copy of ", "Copy of"):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
            break
    return s


# ── Load live context (used in system prompt) ────────────────────────────────
live_ctx = load_live_context()

# ── Session-state init ────────────────────────────────────────────────────────
HIST = "arch_chat_history"
if HIST not in st.session_state:
    st.session_state[HIST] = []

PROSPECT = "arch_scoped_prospect"
if PROSPECT not in st.session_state:
    st.session_state[PROSPECT] = ""

# ── Reference proposal picker ────────────────────────────────────────────────
# Sits at the top, persists across the whole chat. Picking a proposal injects
# its full text into the system prompt so the architect can cite specific
# patterns from real deals (Castrol's voice positioning, Nippon's dealer
# automation phasing, 1mg's pricing structure, etc).
ref_options = list_reference_proposals()
with st.container(border=True):
    rc1, rc2 = st.columns([5, 1])
    with rc1:
        if ref_options:
            picked_ref_names = st.multiselect(
                "📚 Reference proposals to draw from (pick 1–3 most relevant)",
                options=[_clean_proposal_name(r["name"]) for r in ref_options],
                key="arch_picked_refs",
                help="Selected proposals get loaded into the system prompt so the architect "
                     "can reference their actual commercial framing, capability bundles, and "
                     "integration approach. Leave empty to rely on the playbook alone.",
            )
        else:
            picked_ref_names = []
            st.caption("⚠️ No reference proposals found in the Drive folder. "
                       "Drop some in `Reference Proposals / Knowledge Base` to use them here.")
    with rc2:
        if st.button("🔄", help="Re-scan the proposals folder", use_container_width=True):
            list_reference_proposals.clear()
            st.rerun()

# Resolve selected names → full texts (cached per doc id)
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
    if reference_docs:
        st.caption(f"📚 Loaded **{len(reference_docs)}** proposal(s) — totalling "
                   f"~{sum(len(d['text']) for d in reference_docs) // 1000}K characters.")

# ── Empty-state guidance (only when no chat yet) ─────────────────────────────
if not st.session_state[HIST]:
    st.markdown("""
### How to use this

This is your **All-e solutioning copilot**. Open it before any prospect meeting and ask it to prep you. It already knows the playbook (3 levers, System of Intelligence, journey × lever matrix, real customer references) and it can see the live Graas pipeline, so when you mention a company by name, it cross-references where they sit and what's been said.

**What it's good at**

| You need… | Ask it… |
|---|---|
| To prep for a discovery call | *"Prep me for the next Nerolac discovery call — what should I probe on?"* |
| To pick the right use cases for a vertical | *"What use cases should I pitch to a multi-brand FMCG distributor?"* |
| To position vs a competitor or in-house | *"How do I position All-e vs an in-house build for an OEM?"* |
| To draft an opening line | *"Draft the opening for a strategic note to the CIO at a paint major"* |
| To handle a specific objection | *"They said the chatbot they tried didn't work — how do I respond?"* |
| To frame the commercial / ROI | *"Quantify the ROI for a distributor doing 1000 invoices/day"* |

**Tips**

- **Mention the company name** — it cross-references the live pipeline (vertical, region, stage, last conversation notes) automatically.
- **Be specific about what you want** — "give me 5 discovery questions" beats "tell me about Nerolac."
- **Iterate** — push back, ask follow-ups, request alternatives. Treat it like a senior SA you're brainstorming with.

---
""")

    # Example prompt chips
    st.markdown("**Quick start — click any:**")
    examples = [
        "Prep me for the next Nerolac discovery call — what should I probe on?",
        "What use cases should I pitch to a multi-brand FMCG distributor?",
        "How do I position All-e vs an in-house build for an OEM?",
        "Draft the opening for a strategic note to a CIO at a paint major",
    ]
    ex_cols = st.columns(2)
    for i, prompt in enumerate(examples):
        with ex_cols[i % 2]:
            if st.button(prompt, key=f"arch_ex_{i}", use_container_width=True):
                st.session_state["arch_prefill"] = prompt
                st.rerun()

# ── Render chat history ──────────────────────────────────────────────────────
for msg in st.session_state[HIST]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"], unsafe_allow_html=True)

# ── Input ────────────────────────────────────────────────────────────────────
user_input = st.chat_input(
    "Ask about discovery, use cases, positioning, pricing framing, objection handling…",
    key="arch_input",
)
if "arch_prefill" in st.session_state:
    user_input = st.session_state.pop("arch_prefill")

if user_input:
    st.session_state[HIST].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                system_prompt = build_system_prompt(live_ctx, reference_docs=reference_docs)
                messages = [{"role": m["role"], "content": m["content"]}
                            for m in st.session_state[HIST][-20:]]
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=2500,
                    system=system_prompt,
                    messages=messages,
                )
                assistant_msg = response.content[0].text
                st.markdown(assistant_msg, unsafe_allow_html=True)
                st.session_state[HIST].append(
                    {"role": "assistant", "content": assistant_msg}
                )
            except Exception as e:
                st.error(f"Error: {e}")


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    if st.session_state[HIST]:
        st.markdown(f"**{len(st.session_state[HIST])} messages in this thread**")
        if st.button("🆕 Start fresh", use_container_width=True):
            st.session_state[HIST] = []
            st.rerun()
    if st.button("🔄 Refresh pipeline data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
