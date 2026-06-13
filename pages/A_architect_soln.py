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
def build_system_prompt(live_ctx: dict) -> str:
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


# ── Chat surface ──────────────────────────────────────────────────────────────
live_ctx = load_live_context()

# Status strip
status_cols = st.columns([1, 1, 1, 1])
with status_cols[0]:
    if isinstance(live_ctx.get("active_pipeline"), dict):
        st.metric("Active pipeline", live_ctx["active_pipeline"]["rows"])
    else:
        st.metric("Active pipeline", "—")
with status_cols[1]:
    notes = live_ctx.get("recent_meeting_notes", [])
    st.metric("Meeting notes", len(notes) if isinstance(notes, list) else "—")
with status_cols[2]:
    st.metric("Skill version", "all-e SA v1")
with status_cols[3]:
    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.markdown("---")

# Example prompts
st.markdown("**Try asking:**")
examples = [
    "Prep me for the next Nerolac discovery call — what should I probe on?",
    "What use cases should I pitch to a multi-brand FMCG distributor?",
    "How do I position All-e vs an in-house build for an OEM?",
    "Draft the opening for a strategic note to a CIO at a paint major",
]
ex_cols = st.columns(len(examples))
for i, prompt in enumerate(examples):
    with ex_cols[i]:
        if st.button(prompt, key=f"arch_ex_{i}", use_container_width=True):
            st.session_state["arch_prefill"] = prompt

# Render chat history
HIST = "arch_chat_history"
if HIST not in st.session_state:
    st.session_state[HIST] = []

for msg in st.session_state[HIST]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"], unsafe_allow_html=True)

# Input
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
                system_prompt = build_system_prompt(live_ctx)
                messages = [{"role": m["role"], "content": m["content"]}
                            for m in st.session_state[HIST][-20:]]
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
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
    if st.button("Clear Architect chat"):
        st.session_state[HIST] = []
        st.rerun()
