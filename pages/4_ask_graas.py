"""Ask Graas — AI Chat for Sales Hub (Pipeline, All-e, CRM)."""

import re as _re
import streamlit as st
import pandas as pd
import json
import os
from pathlib import Path
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

_env_path = str(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(_env_path, override=True)

st.set_page_config(page_title="Ask Graas | Sales Hub", page_icon="💬", layout="wide")

# Style citations in dark blue
st.markdown("""<style>
.citation { color: #1e40af; font-size: 0.85em; font-style: italic; }
</style>""", unsafe_allow_html=True)


def _style_citations(text: str) -> str:
    """Replace *(citation text)* with dark blue styled HTML spans."""
    return _re.sub(
        r'\*\(([^)]+)\)\*',
        r'<span class="citation">(\1)</span>',
        text,
    )


st.markdown("## 💬 Ask Graas")
st.caption("Ask anything about Pipeline, All-e Presales, or CRM contacts")

# ── Check API Key ────────────────────────────────────────────────────────────

# Prefer Streamlit secrets (works on Streamlit Cloud + local secrets.toml)
try:
    ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

if not ANTHROPIC_API_KEY:
    st.warning("Add `ANTHROPIC_API_KEY` to `.streamlit/secrets.toml` or `.env` to enable AI chat.")
    st.stop()

# ── Data Loaders ─────────────────────────────────────────────────────────────

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CURRENT_MONTH = MONTH_NAMES[datetime.now().month - 1]


@st.cache_data(ttl=1800)
def load_sales_data():
    """Load and summarise all sales data for AI context."""
    summaries = {}

    # ── Proposals ────────────────────────────────────────────────
    try:
        from services.sheets_client import fetch_sheet_tab
        sheet_id = os.getenv("REVENUE_SHEET_ID", "")
        if sheet_id:
            df = fetch_sheet_tab(sheet_id, "Proposals")
            if not df.empty:
                # Clean up column names
                cols = [c.strip().lower() for c in df.columns]
                df.columns = [c.strip() for c in df.columns]

                summaries["proposals"] = {
                    "total": len(df),
                    "columns": list(df.columns)[:15],
                    "all_rows": df.head(50).to_dict("records"),
                }

                # Try to extract status breakdown
                status_col = None
                for c in df.columns:
                    if "status" in c.lower():
                        status_col = c
                        break
                if status_col:
                    status_counts = df[status_col].value_counts().to_dict()
                    summaries["proposals"]["status_breakdown"] = status_counts

                # Try to extract product/month breakdown
                month_col = None
                for c in df.columns:
                    if "month" in c.lower():
                        month_col = c
                        break
                if month_col:
                    month_counts = df[month_col].value_counts().to_dict()
                    summaries["proposals"]["by_month"] = month_counts

    except Exception as e:
        summaries["proposals"] = f"Error: {e}"

    # ── Meetings Summary ────────────────────────────────────────
    try:
        from services.sheets_client import fetch_sheet_tab
        sheet_id = os.getenv("ALLE_SHEET_ID", "")
        if sheet_id:
            df = fetch_sheet_tab(sheet_id, "Revised - Summary of Meetings")
            if not df.empty:
                # Send raw data for AI to interpret
                summaries["meetings_summary"] = {
                    "rows": len(df),
                    "raw_data": df.head(30).to_dict("records"),
                    "note": "This is the 'Revised - Summary of Meetings' tab. It has 4 source blocks: Partner India, Partner SEA, Graas Network India, Graas Network SEA. Each block tracks meetings completed, positive interest, POCs, pilots, production by month (Jan-Apr). Rows 18+ have Overall India and Overall SEA with Actual vs Target.",
                }
    except Exception as e:
        summaries["meetings_summary"] = f"Error: {e}"

    # ── All-e Active Presales ───────────────────────────────────
    try:
        from services.sheets_client import fetch_alle_active_presales
        df = fetch_alle_active_presales()
        if not df.empty:
            summaries["alle_active"] = {
                "total_leads": len(df),
                "columns": list(df.columns)[:20],
                "all_rows": df.head(40).to_dict("records"),
            }
    except Exception as e:
        summaries["alle_active"] = f"Error: {e}"

    # ── All-e Dropped Leads ─────────────────────────────────────
    try:
        from services.sheets_client import fetch_alle_dropped_leads
        df = fetch_alle_dropped_leads()
        if not df.empty:
            summaries["alle_dropped"] = {
                "total": len(df),
                "columns": list(df.columns)[:15],
                "sample": df.head(15).to_dict("records"),
            }
    except Exception as e:
        summaries["alle_dropped"] = f"Error: {e}"

    # ── Current Pipeline (Kanban) ───────────────────────────────
    try:
        from services.sheets_client import fetch_sheet_tab
        sheet_id = os.getenv("ALLE_SHEET_ID", "")
        if sheet_id:
            tab_name = f"All-e Pipeline (IN) - {CURRENT_MONTH}"
            df = fetch_sheet_tab(sheet_id, tab_name)
            if not df.empty:
                summaries["current_pipeline"] = {
                    "month": CURRENT_MONTH,
                    "rows": len(df),
                    "raw_data": df.head(40).to_dict("records"),
                    "note": f"This is the {CURRENT_MONTH} pipeline with sections: Meetings Already Set, Meetings In Process, MOF (Met, No Proposal), BOF (Proposal Sent).",
                }
    except Exception as e:
        summaries["current_pipeline"] = f"Error: {e}"

    # ── CRM Overlay ─────────────────────────────────────────────
    try:
        overlay_path = Path(__file__).parent.parent / "content" / "crm_overlay.json"
        if overlay_path.exists():
            with open(overlay_path) as f:
                overlay = json.load(f)
            summaries["crm_overlay"] = {
                "contacts": len(overlay.get("contacts", [])),
                "data": overlay.get("contacts", []),
            }
    except Exception as e:
        summaries["crm_overlay"] = f"Error: {e}"

    # ── Meeting Notes (from Slack / Granola) ─────────────────────
    try:
        from services.notes_store import get_all_notes
        notes = get_all_notes()
        if notes:
            summaries["meeting_notes"] = [
                {
                    "client": n.get("client", ""),
                    "date": n.get("date", ""),
                    "author": n.get("author", ""),
                    "channel": n.get("channel", ""),
                    "summary": n.get("summary", ""),
                    "takeaways": n.get("takeaways", []),
                    "has_granola": bool(n.get("granola")),
                    "missing_granola": n.get("missing_granola", False),
                    "source": n.get("source", ""),
                }
                for n in notes[:30]
            ]
    except Exception:
        pass

    # ── Slack live notes (if no stored notes) ────────────────────
    if "meeting_notes" not in summaries:
        try:
            from services.slack_notes import fetch_meeting_notes
            slack_notes = fetch_meeting_notes(lookback_days=30)
            if slack_notes:
                summaries["meeting_notes"] = [
                    {
                        "client": n.get("client", ""),
                        "date": n.get("date", ""),
                        "author": n.get("author", ""),
                        "channel": n.get("channel", ""),
                        "summary": n.get("summary", ""),
                        "takeaways": n.get("takeaways", []),
                        "has_granola": bool(n.get("granola")),
                        "missing_granola": n.get("missing_granola", False),
                        "source": "slack",
                    }
                    for n in slack_notes[:30]
                ]
        except Exception:
            pass

    # ── Hardcoded snapshot fallback (last pulled ~10 Apr 2026) ───────
    if "meeting_notes" not in summaries:
        summaries["meeting_notes"] = [
            {
                "client": "Orient Bell", "date": "10 Apr", "author": "Gaurav Girotra",
                "channel": "#ebu-offerings-gtm", "has_granola": True, "missing_granola": False,
                "source": "snapshot", "summary": "",
                "takeaways": [
                    "POC kicked off for floor tiles as a category",
                    "To be delivered by end of next week (assuming catalogue & details received)",
                    "GG to set up f2f meeting for POC walkthrough and Pilot next steps",
                ],
            },
            {
                "client": "Unicharm", "date": "10 Apr", "author": "Ashwin Puri",
                "channel": "#ebu-offerings-gtm", "has_granola": True, "missing_granola": False,
                "source": "snapshot", "summary": "",
                "takeaways": [
                    "Existing MP customer expanding markets — SGD $45M MYR/month MY business",
                    "Enablement: extend SG DKSH model to MY for Lazada/Shopee",
                    "All-e: discovery call to be set up in KL with IT team (Ashwin to arrange)",
                    "Offline AI agent for 126 merchandising + 170 sales team — $10M USD/month MY business",
                ],
            },
            {
                "client": "RSPL Group", "date": "9 Apr", "author": "Gaurav Girotra",
                "channel": "#ebu-offerings-gtm", "has_granola": True, "missing_granola": False,
                "source": "snapshot", "summary": "",
                "takeaways": [
                    "Sales use case not a need — dealer ordering is not an issue for them",
                    "Possible use case: factory OCR (30 factories) for handwritten/typed info routing",
                    "They will come back after discussing internally",
                ],
            },
            {
                "client": "Tata 1mg", "date": "9 Apr", "author": "Gaurav Girotra",
                "channel": "#ebu-offerings-gtm", "has_granola": True, "missing_granola": False,
                "source": "snapshot", "summary": "",
                "takeaways": [
                    "Prem to work with Nikhil on closing out commercials",
                    "Amruta to test accuracy improvements with new cleanly labelled prescriptions",
                ],
            },
            {
                "client": "Dalmia Cement", "date": "8 Apr", "author": "Gaurav Girotra",
                "channel": "#ebu-offerings-gtm", "has_granola": True, "missing_granola": False,
                "source": "snapshot", "summary": "",
                "takeaways": [
                    "Very low SKUs (5 active), weekly ordering, 50K dealers — no opportunity",
                    "They already have an AI agent deployed for dealer ordering",
                    "Cement may not be a good fit — low SKU density, infrequent orders",
                ],
            },
            {
                "client": "Sunway", "date": "6 Apr", "author": "Sahil Tyagi",
                "channel": "#my-gtm-alle", "has_granola": True, "missing_granola": False,
                "source": "snapshot", "summary": "", "takeaways": [],
            },
            {
                "client": "Decathlon", "date": "2 Apr", "author": "Prem Bhatia",
                "channel": "#my-gtm-alle", "has_granola": True, "missing_granola": False,
                "source": "snapshot", "summary": "", "takeaways": [],
            },
            {
                "client": "Beacon Mart", "date": "1 Apr", "author": "Sahil Tyagi",
                "channel": "#my-gtm-alle", "has_granola": True, "missing_granola": False,
                "source": "snapshot", "summary": "",
                "takeaways": [
                    "Cindy to send Thomas Hoppr login for e-commerce team (5 users)",
                    "Send Thomas videos on offline agent (Ollie) for IT team",
                    "Follow up with proposal for f2f meeting in KL once IT is looped in",
                    "Thomas to share Graas videos with Beacon Mart IT team",
                ],
            },
        ]

    # ── Knowledge Base (All-e Sales Doc) ─────────────────────────
    try:
        from services.sheets_client import fetch_google_doc_text
        kb_text = fetch_google_doc_text("11-lE1Pfwf4XR_hWNwORuJund25wbKWxhOOFlZz7uX7c")
        if kb_text and len(kb_text.strip()) > 100:
            summaries["knowledge_base"] = kb_text.strip()
    except Exception:
        pass

    return summaries


def build_system_prompt(data):
    """Build sales-focused system prompt with live data."""
    today = datetime.now().strftime("%B %d, %Y")

    context_parts = []

    if "proposals" in data and isinstance(data["proposals"], dict):
        p = data["proposals"]
        context_parts.append("=== PROPOSALS === [Source: Revenue Call Sheet — Proposals tab]")
        context_parts.append(f"Total proposals: {p['total']}")
        if "status_breakdown" in p:
            context_parts.append(f"Status: {json.dumps(p['status_breakdown'])}")
        if "by_month" in p:
            context_parts.append(f"By month: {json.dumps(p['by_month'])}")
        context_parts.append(f"Columns: {p['columns']}")
        context_parts.append(f"Data: {json.dumps(p['all_rows'][:30], default=str)}")

    if "meetings_summary" in data and isinstance(data["meetings_summary"], dict):
        ms = data["meetings_summary"]
        context_parts.append("\n=== MEETINGS SUMMARY === [Source: All-e Sheet — Revised Summary of Meetings tab]")
        context_parts.append(ms["note"])
        context_parts.append(f"Raw data: {json.dumps(ms['raw_data'], default=str)}")

    if "alle_active" in data and isinstance(data["alle_active"], dict):
        a = data["alle_active"]
        context_parts.append(f"\n=== ALL-E ACTIVE PRESALES ({a['total_leads']} leads) === [Source: Presales Tracker Sheet]")
        context_parts.append(f"Columns: {a['columns']}")
        context_parts.append(f"Data: {json.dumps(a['all_rows'][:25], default=str)}")

    if "alle_dropped" in data and isinstance(data["alle_dropped"], dict):
        d = data["alle_dropped"]
        context_parts.append(f"\n=== ALL-E DROPPED LEADS ({d['total']}) === [Source: Presales Tracker Sheet — Dropped Leads tab]")
        context_parts.append(f"Columns: {d['columns']}")
        context_parts.append(f"Sample: {json.dumps(d['sample'][:10], default=str)}")

    if "current_pipeline" in data and isinstance(data["current_pipeline"], dict):
        cp = data["current_pipeline"]
        context_parts.append(f"\n=== {cp['month'].upper()} PIPELINE (KANBAN) === [Source: All-e Sheet — {cp['month']} Pipeline tab]")
        context_parts.append(cp["note"])
        context_parts.append(f"Data: {json.dumps(cp['raw_data'][:25], default=str)}")

    if "crm_overlay" in data and isinstance(data["crm_overlay"], dict):
        co = data["crm_overlay"]
        context_parts.append(f"\n=== CRM OVERLAY ({co['contacts']} contacts) === [Source: Local CRM file]")
        context_parts.append(f"Data: {json.dumps(co['data'][:15], default=str)}")

    if "meeting_notes" in data and isinstance(data["meeting_notes"], list):
        context_parts.append(f"\n=== MEETING NOTES ({len(data['meeting_notes'])} recent) === [Source: Slack GTM channels / Granola]")
        for note in data["meeting_notes"]:
            source_tag = "Granola notes via Slack" if note.get("has_granola") else "Slack message only (no Granola notes)"
            parts = [f"  Client: {note['client']} | Date: {note['date']} | By: {note['author']} | Channel: {note['channel']} | Source: {source_tag}"]
            if note.get("summary"):
                parts.append(f"    Summary: {note['summary'][:300]}")
            if note.get("takeaways"):
                parts.append(f"    Takeaways: {'; '.join(note['takeaways'][:5])}")
            context_parts.append("\n".join(parts))

    # KB injected in full — it's the primary sales reference material
    if "knowledge_base" in data and isinstance(data["knowledge_base"], str):
        context_parts.append(
            f"\n=== ALL-E SALES KNOWLEDGE BASE === [Source: Graas KB Doc]\n"
            f"This is the official product orientation, customer archetypes, discovery guidance, "
            f"use cases, proposals, and discovery questionnaires for All-e pre-sales.\n\n"
            f"{data['knowledge_base']}"
        )

    data_context = "\n".join(context_parts)

    return f"""You are the Graas Sales Hub AI assistant. Today is {today}.
You help the sales team with two things:
1. Pipeline intelligence — meetings vs target, deal stages, follow-up priorities, proposals won/lost
2. Sales preparation — discovery questions, All-e use cases, customer archetypes, objection handling, what NOT to say

You have access to live pipeline data AND the All-e Sales Knowledge Base (proposals, discovery questionnaires, product orientation):

{data_context}

RULES:
- Be concise and direct. Use bullet points and bold for readability.
- When discussing meetings: they are tracked by source channel (Partner India, Partner SEA, Graas Network India, Graas Network SEA). Meetings are product-agnostic. Proposals are by product.
- Products/verticals: All-e (AI agents for enterprise), Hoppr (analytics), Extract, Marketplace BU.
- Key pipeline stages: Meeting Being Set → MOF (Met, No Proposal) → BOF (Proposal Sent) → Won/Lost.
- India targets and SEA targets are tracked separately.
- For proposals: track Won, Lost, Open, and GP (Gross Profit) values.
- If asked for a "pipeline summary" or "sales brief", structure as: Meetings (Q1+current month, actual vs target), Pipeline Funnel (MOF/BOF counts), Proposals (by product, won/lost/open), Key accounts to watch.
- If data is missing for a question, say so clearly.
- GP is more important than Revenue.
- **ALWAYS cite your source** for every claim. Use the [Source: ...] tags from the data sections above.
- When referencing meeting notes, mention the date, who posted them, and whether Granola notes exist or are missing.

FOR SALES PREP QUESTIONS:
- Draw on the All-e Sales Knowledge Base for product descriptions, customer archetypes, and positioning.
- When asked for discovery questions, tailor them to the specific industry/vertical and geography mentioned.
- When asked about use cases, cite actual customers (Schneider, Canon, Nippon Paint, PI Industries, Tata 1mg, Orient Bell) where relevant.
- Flag what NOT to say (e.g. don't lead with GAF/knowledge graphs in early conversations).
- If asked to prep for a specific company, cross-reference the Presales Tracker for their current status and last conversation notes.
"""


# ── Chat Interface ───────────────────────────────────────────────────────────

all_data = load_sales_data()

# Data status
with st.expander("Data Sources", expanded=False):
    for source, data in all_data.items():
        if isinstance(data, str) and data.startswith("Error"):
            st.error(f"**{source}**: {data}")
        elif source == "knowledge_base" and isinstance(data, str):
            st.success(f"**{source}** ({len(data):,} chars): Loaded")
        elif isinstance(data, dict):
            detail = ""
            if "total" in data:
                detail = f" ({data['total']} records)"
            elif "total_leads" in data:
                detail = f" ({data['total_leads']} leads)"
            elif "contacts" in data:
                detail = f" ({data['contacts']} contacts)"
            elif "rows" in data:
                detail = f" ({data['rows']} rows)"
            st.success(f"**{source}**{detail}: Loaded")
        elif isinstance(data, list):
            st.success(f"**{source}** ({len(data)} notes): Loaded")
        else:
            st.warning(f"**{source}**: No data")

# Example prompts
st.markdown("**Try asking:**")
prompt_cols = st.columns(4)
example_prompts = [
    "Give me a pipeline summary for Q1",
    "Which All-e deals are closest to closing?",
    "How are meetings tracking vs target?",
    "Who should we follow up with this week?",
]

for i, prompt in enumerate(example_prompts):
    with prompt_cols[i]:
        if st.button(prompt, key=f"example_{i}", use_container_width=True):
            st.session_state["prefill_prompt"] = prompt

st.markdown("---")

# Chat history
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []

for msg in st.session_state.chat_messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            st.markdown(_style_citations(msg["content"]), unsafe_allow_html=True)
        else:
            st.markdown(msg["content"])

# Chat input
user_input = st.chat_input("Ask about pipeline, meetings, proposals, CRM...")

if "prefill_prompt" in st.session_state:
    user_input = st.session_state.pop("prefill_prompt")

if user_input:
    st.session_state.chat_messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                import anthropic

                client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                system_prompt = build_system_prompt(all_data)

                messages = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.chat_messages[-20:]
                ]

                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2048,
                    system=system_prompt,
                    messages=messages,
                )

                assistant_msg = response.content[0].text
                st.markdown(_style_citations(assistant_msg), unsafe_allow_html=True)

                st.session_state.chat_messages.append(
                    {"role": "assistant", "content": assistant_msg}
                )

            except Exception as e:
                st.error(f"Error: {e}")

# Sidebar
with st.sidebar:
    if st.button("Clear Chat"):
        st.session_state.chat_messages = []
        st.rerun()
    if st.button("Refresh Data"):
        st.cache_data.clear()
        st.rerun()
