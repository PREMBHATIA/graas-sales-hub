"""Ask Graas — AI Solutions Architect for Sales Hub (Pipeline, All-e, CRM)."""

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

# ── Check API Key ────────────────────────────────────────────────────────────

# Prefer Streamlit secrets (works on Streamlit Cloud + local secrets.toml)
try:
    ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

if not ANTHROPIC_API_KEY:
    st.warning("Add `ANTHROPIC_API_KEY` to `.streamlit/secrets.toml` or `.env` to enable AI chat.")
    st.stop()


# ── Solutions Architect Framework (baked-in) ─────────────────────────────────

SOLUTIONS_ARCHITECT_FRAMEWORK = """
=== GRAAS / ALL-E SOLUTIONS ARCHITECT FRAMEWORK ===

## WHAT IS GRAAS / ALL-E

### The Core Positioning: System of Intelligence
Every large brand runs on two sets of software that have never been connected:
1. Systems of Record (back-end) — SAP, ERPs, CRMs, DMS, OMS, inventory systems, pricing engines, credit limit databases
2. Systems of Engagement (front-end) — WhatsApp, Messenger, LINE, Zalo, websites, email, voice calls

The problem: a sales rep has to manually check the ERP, then WhatsApp the answer to the retailer. A consumer asks about stock availability and gets no answer from a static product page.

Graas sits in the middle as the System of Intelligence — connecting engagement surfaces to back-end systems in real time, without a human in the loop.

### What all-e Actually Does
all-e is a retail agentic solution built on the Graas Agent Foundry. It deploys AI agents (called "Agent X") across customer touchpoints.

B2C capabilities:
- Product discovery and guided selling
- Add to cart, improve conversion, checkout assistance
- Variant/availability/delivery slot queries answered in real time
- Personalized recommendations based on purchase history
- Order tracking, returns, warranty checks

B2B capabilities (everything B2C can do PLUS):
- Access the customer's CRM and ERP directly
- Credit checks and eligibility verification
- Invoice generation and sending
- Scheme/promotion eligibility and progress tracking
- Transportation/shipping details
- Secondary sales capture (invoice photo → digitization → ERP update)
- Conversational ordering via WhatsApp

Intelligence as an API:
- Customers can deploy Graas's retrieval API on their existing agents/chatbots
- Blends intelligence across: product catalog, customer purchase history, inventory systems
- Powered by a proprietary Knowledge Graph

## THE THREE BUSINESS LEVERS

Every use case maps to one or more of these three levers. Use this in every discovery conversation and every proposal.

Lever 1: Customer Experience (CX)
- Why it matters: Why customers stay — trust, ease, speed, reliability
- North star metric: Customer Effort Score (CES)
- Key outcome: Move from "Passive Connection" to "Active Conversation" intent

Lever 2: Cost Efficiency
- Why it matters: Why the business is profitable — efficiency, automation, waste reduction
- North star metric: Average Handling Time (AHT)
- Key outcome: Lower cost per interaction

Lever 3: Revenue Growth
- Why it matters: Why the business scales — conversion, margin, market share
- North star metric: Revenue per interaction / conversion rate
- Key outcome: No monetization leaks; convert latent trade demand into booked revenue

Important: Sustainable growth comes from balancing trade-offs between all three levers, not optimizing one in isolation.

## CUSTOMER JOURNEY & AGENT ROLES

Journey Stages × Levers Matrix:

                      Discovery & Sales          | Transaction                  | Retention & Ops
Experience:           Instant answers, deep      | Check inventory, delivery    | Order status, outstanding
                      product knowledge          | slots                        | balance queries
Revenue:              Lead classification        | Reduce abandonments,         | Personalized reordering,
                                                 | upsells & cross-sells        | loyalty updates
Cost:                 Deflecting noise / FAQ     | Automate manual orders,      | Reducing call center
                      automation                 | reconcile with ERP           | volume

Agent Types:
- Discovery & Sales Agent — covers Discovery & Sales + Transaction stages
- Support Agent — covers Transaction + Retention & Ops stages

## USE CASE DEEP DIVES

### Solving for Customer Experience (Discovery & Sales)

B2B example: Retailer asks on WhatsApp "What's my current credit limit? And where is my order from 2-3 days back?" → Agent checks ERP, responds with credit availability (e.g., INR 6,32,000) and order status (OD-1273, in transit, arriving tomorrow).

B2C example: Consumer asks "Help me find a good power bank for treks" → Agent recommends 10K mAh (lighter, best for treks) vs 20K mAh (more juice, heavier), adds social proof, generates cart link.

Result: Increase Customer Effort Score (CES)

### Solving for Cost (Efficiency)

B2B/GT secondary sales today: FA field visit → invoice photos → manual entry → back-office review → ERP. Takes 5-7 days.
B2C support today: calls → tickets → manual checks → ERP actions → manual updates. Takes 1-4 hours.

Agentic mode:
- Secondary sales: FAs share invoice on WhatsApp → AI extracts data → FA validates → ERP auto-updated. Minutes instead of days.
- Customer support: Agent resolves end-to-end → ERP updated → customer notified. No human involvement for routine queries.

The 70/20/10 Automation Pyramid:
- 70% Only AI: Handle repetitive work — answer FAQs, variant availability, WISMO, copy/paste to ERP, send invoices, check warranty, schedule visits
- 20% Human + AI: Complaints, complex responses (AI drafts, human reviews)
- 10% Human Only: Crisis management, high-stakes VIP sales

Result: Reduction in Average Handling Time (AHT).

### Solving for Revenue — B2B

The Problem:
- Revenue tied to sales-rep availability (rep on leave = no orders)
- Reorders missed, baskets under-sized, schemes under-utilized
- Stock-outs with no alternate inventory visibility

The Solution:
- 24×7 agent-led ordering (retailer WhatsApps "I need 20 units urgently" → order placed instantly)
- Intelligent reordering, upsell & cross-sell using purchase history and catalog intelligence
- Scheme-led buying nudges with progress tracking ("Order 100 units by June 30 to win a Thailand trip. You're just 40 units away — want to order now?")
- Alternate inventory discovery in real time ("Sold out in your warehouse, but 100 units available in a nearby store. Shall I confirm?")

Result: No monetization leaks. Agents convert latent trade demand into booked revenue.

### Solving for Revenue — B2C

The Problem:
- High-volume marketing clicks → noisy signal, low engagement
- Static catalogs don't answer use-case-specific questions
- Choice overload without guidance → abandonment

The Solution:
- Qualify intent through high-engagement conversations
- Use-case-led consultative guidance (not just "here are 50 products")
- Simplified, expert-guided product comparison

Result: Higher revenue against marketing spends. Higher conversions from existing traffic.

## CURRENT VS AGENTIC WORKFLOWS (Key timing numbers to use in pitches)

Distributors:
- Current mode: Communication over personal WhatsApp/phone calls. 1-4 days, multiple humans involved.
- Agentic mode: OEM-owned single WhatsApp number powered by Agent X, integrated with ERP or DMS. 10-15 minutes with minimal human intervention.

Field Agents (Secondary Sales Capture):
- Current mode: Photos of invoices/POs, manual data entry and verification. 5-6 days, human effort intensive, error prone.
- Agentic mode: SFA app or WhatsApp number powered by Agent X, integrated with ERP. 3-5 minutes with minimal human intervention.

Retailers:
- Current mode: Communication over personal WhatsApp/phone calls. 1-2 days, manual, multiple humans involved.
- Agentic mode: OEM-owned single WhatsApp for retailers to place orders with distributors, integrated with OMS. 3-5 minutes with minimal human intervention.

## DISCOVERY PLAYBOOK

Step 1: Understand the Business Model
- Are they B2B, B2C, or both?
- Who are their key personas? (Distributors, field agents, retailers, consumers)
- What's their distribution structure? (Direct, GT/general trade, modern trade, e-commerce)
- What geographies? (India, SEA, GCC — this affects channel: WhatsApp in India, LINE in Thailand, Zalo in Vietnam)

Step 2: Map Their Current Systems
- Systems of Record: What ERP? (SAP, Oracle, Tally, custom?) What CRM? What DMS/OMS?
- Systems of Engagement: What channels do they use today? (WhatsApp, website, call center, field app, email)
- Key question: Are these two sides connected today? (Almost always: no)

Step 3: Identify Pain Points Using the Three Levers
- CX: "How do your retailers/consumers get answers today? How long does it take? What can't they self-serve?"
- Cost: "What's your current AHT? How many people handle order entry / support? What's the manual step that takes the longest?"
- Revenue: "Are you losing orders because reps aren't available? Are your schemes being fully utilized? What's your cart abandonment rate?"

Step 4: Prioritize Use Cases
- Map each pain point to a journey stage (Discovery & Sales / Transaction / Retention & Ops)
- Identify which agent type covers it (Discovery & Sales Agent / Support Agent)
- Rank by: (a) business impact, (b) integration complexity, (c) time to deploy

Step 5: Scope the Solution
For each use case, define:
- The persona it serves
- The channel it runs on
- The back-end systems it needs to connect to
- The current workflow vs. the agentic workflow
- The expected metric impact (AHT reduction, CES improvement, revenue uplift)

Step 6: Commercial Framing
- Start with 1-2 high-impact use cases, not a full platform pitch
- Show the current-vs-agentic comparison for their specific workflow
- Quantify the value: "If your field agents spend 5 days on secondary sales capture and we bring it to 5 minutes, what does that save you per month?"
- Land-and-expand: prove value on the first use case, then expand across journey stages

## INDUSTRY-SPECIFIC GUIDANCE

FMCG / CPG:
- Strongest fit: B2B (distributor/retailer ordering, secondary sales capture, scheme nudges)
- Key pain: Manual secondary sales capture, scheme under-utilization, field agent productivity
- Lead with: Cost (AHT reduction on secondary sales) + Revenue (scheme utilization, 24×7 ordering)
- Integration: SAP/ERP + DMS + WhatsApp
- Reference customers: PI Industries (agri), Nippon Paint (B2B dealer ordering)

Pharma / Healthcare:
- Strongest fit: B2B (distributor ordering, regulatory compliance, batch/expiry tracking)
- Key pain: Compliance requirements on ordering, expiry-date-aware inventory, controlled substance tracking
- Lead with: Experience (instant availability with batch-level visibility) + Cost (automated compliance checks)
- Integration: ERP + DMS + regulatory databases
- Reference: Tata 1mg (prescription digitization + ordering)

Consumer Electronics:
- Strongest fit: B2C (product discovery, guided selling) + B2B (dealer/retailer ordering)
- Key pain: Complex product catalogs, high return rates due to wrong purchases, warranty management
- Lead with: Revenue (guided discovery → higher conversion, fewer returns) + Experience (warranty/support automation)
- Integration: PIM/catalog system + ERP + CRM
- Reference customers: Canon (camera discovery + dealer ordering), Schneider Electric (B2B ordering)

Building Materials / Industrial:
- Strongest fit: B2B (dealer ordering, credit management)
- Key pain: Large SKU catalogs, complex pricing/credit structures, long order cycles
- Lead with: Revenue (24×7 ordering, cross-sell) + Cost (automated credit checks, invoice generation)
- Reference: SRMB Steel, Dalmia Cement (low SKU density — flag as potential misfit)

Agriculture Inputs:
- Strongest fit: B2B (retailer ordering, field agent productivity)
- Key pain: Seasonal demand spikes, remote/rural distribution, low-tech retailers
- Lead with: Experience (WhatsApp-first ordering for low-tech users) + Cost (field agent efficiency)
- Must work on low-bandwidth / low-tech devices
- Reference: Agricon, PI Industries

Fashion & Apparel:
- Strongest fit: B2C (discovery, styling guidance, size recommendations) + B2B (wholesale ordering)
- Key pain: High return rates, size/fit uncertainty, seasonal inventory management
- Lead with: Revenue (guided discovery → conversion, reduce returns) + Experience (personalized recommendations)

Southeast Asia specifics:
- Thailand: LINE is the primary messaging channel (not WhatsApp)
- Vietnam: Zalo OA is primary
- Philippines / Indonesia: WhatsApp + Messenger
- Malaysia/Singapore: WhatsApp is fine
- Always verify channel preference before scoping integration
- Reference: Sunway (Malaysia), Beacon Mart (Malaysia), Unicharm (expanding SG→MY)

## INTEGRATION ARCHITECTURE

Required integrations by use case:
- Conversational ordering: ERP or OMS (order creation) + inventory system + pricing engine
- Credit checks: ERP (accounts receivable module) or CRM
- Invoice generation: ERP (billing module) + WhatsApp Business API
- Secondary sales capture: ERP + OCR/extraction pipeline + WhatsApp
- Product discovery: Product catalog / PIM + inventory system + Knowledge Graph
- Order tracking: OMS or ERP (logistics module)
- Scheme management: ERP (promotions module) or custom scheme engine

Deployment timelines:
- WhatsApp-based FAQ + product discovery: 2-4 weeks
- Full ERP-integrated ordering with credit checks: 6-8 weeks
- Secondary sales capture with OCR: 4-6 weeks

Channel integration options:
- WhatsApp Business API (primary for India, SEA)
- LINE Official Account (Thailand)
- Zalo OA (Vietnam)
- Messenger (Philippines, general)
- Web widget / SDK (brand websites and apps)
- Voice (via partner voice AI platforms)

## COMMERCIAL / PRICING MODEL

Engagement tiers (reference only — don't lead with pricing in early discovery):
- POC: Free, ~14 days. Limited scope, prove the concept.
- Pilot: $15,000–$25,000, 2-3 months. Defined use case, real integration, measurable outcomes.
- Production: $2,000–$6,000/month MRR. Full deployment, ongoing support and optimization.

Framing for pricing conversations:
- Never lead with price — quantify their current cost first
- "How much do you spend on call center agents per month?" → show ROI from AHT reduction
- "How many field agents do you have? How long does secondary sales capture take?" → show cost of 5 days vs 5 minutes
- Land-and-expand: start with one use case (POC/Pilot), prove value, expand

Agent Scorecard Metrics (what we measure in production):
- CES (Customer Effort Score) — experience lever
- CVR (Conversion Rate) — revenue lever
- CPI (Cost Per Interaction) — cost lever
- AHT (Average Handling Time) — cost lever

## COMMON OBJECTIONS & ANSWERS

"How is this different from a chatbot?"
A chatbot answers FAQs from a static knowledge base. Agent X connects to live back-end systems — it can check real-time inventory, place orders, verify credit, generate invoices. It's not a chatbot, it's an autonomous agent that acts on the customer's behalf.

"What if the agent gets it wrong?"
The 70/20/10 model. 70% fully automated. 20% human-assisted. 10% human-only. The agent knows when to escalate.

"Why WhatsApp?"
In India and SEA, WhatsApp is the default business communication channel. Retailers, distributors, and field agents already use it. No new app to download, no behavior change required.

"What about data security / our ERP vendor?"
Graas connects via standard APIs — we don't replace the ERP, we layer on top of it. Data stays in the customer's systems. We use read/write API access scoped to specific modules.

"We already have a chatbot"
Ask: "What back-end systems does it connect to? Can it place orders or check credit in real time?" If the answer is no, that's the gap we fill.

## WHAT NOT TO SAY (EARLY CONVERSATIONS)

- Don't lead with "Knowledge Graph" or "GAF (Graas Agent Foundry)" — too technical, sounds like jargon
- Don't lead with Turbo, Hoppr, or Marketplace — different products, keep the conversation focused on all-e
- Don't promise exact pricing before use cases are scoped
- Don't position as a chatbot — we are an autonomous agent, not a rule-based bot
- Don't use "AI" as the main selling point — sell the business outcome (time saved, orders captured, cost reduced)
- For Pharma: don't imply the agent handles regulated decisions autonomously

## REFERENCE CUSTOMERS

- Schneider Electric — B2B ordering for dealers/distributors
- Canon — Camera discovery (B2C) + dealer ordering (B2B)
- Nippon Paint — B2B dealer ordering, scheme nudges
- PI Industries (agriculture inputs) — B2B retailer ordering
- Tata 1mg — Prescription digitization + pharmacy ordering
- Orient Bell — POC for floor tiles discovery (B2C)
- Unicharm — B2B distributor expansion (SG → MY market)
- Sunway — SEA / Malaysia
- SRMB Steel — Building materials B2B
- Agricon — Agriculture inputs
- Decathlon — Retail (Malaysia)
- Beacon Mart — Retail (Malaysia), exploring AI agent
"""


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
                df.columns = [c.strip() for c in df.columns]
                summaries["proposals"] = {
                    "total": len(df),
                    "columns": list(df.columns)[:15],
                    "all_rows": df.head(50).to_dict("records"),
                }
                status_col = next((c for c in df.columns if "status" in c.lower()), None)
                if status_col:
                    summaries["proposals"]["status_breakdown"] = df[status_col].value_counts().to_dict()
                month_col = next((c for c in df.columns if "month" in c.lower()), None)
                if month_col:
                    summaries["proposals"]["by_month"] = df[month_col].value_counts().to_dict()
    except Exception as e:
        summaries["proposals"] = f"Error: {e}"

    # ── Meetings Summary ────────────────────────────────────────
    try:
        from services.sheets_client import fetch_sheet_tab
        sheet_id = os.getenv("ALLE_SHEET_ID", "")
        if sheet_id:
            df = fetch_sheet_tab(sheet_id, "Revised - Summary of Meetings")
            if not df.empty:
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

    # ── Hardcoded snapshot fallback ───────────────────────────────
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


def _build_data_context(data: dict) -> str:
    """Build the live data context string for injection into system prompts."""
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

    if "knowledge_base" in data and isinstance(data["knowledge_base"], str):
        context_parts.append(
            f"\n=== ALL-E SALES KNOWLEDGE BASE (Google Doc) === [Source: Graas KB Doc]\n"
            f"{data['knowledge_base']}"
        )

    return "\n".join(context_parts)


def build_pipeline_prompt(data: dict) -> str:
    """System prompt focused on pipeline analytics and deal tracking."""
    today = datetime.now().strftime("%B %d, %Y")
    data_context = _build_data_context(data)

    return f"""You are the Graas Pipeline AI. Today is {today}.
You help the sales team track pipeline health, meetings vs target, deal stages, proposals won/lost, and follow-up priorities.

{data_context}

RULES:
- Be concise and direct. Use bullet points and bold for readability.
- Meetings are tracked by source channel: Partner India, Partner SEA, Graas Network India, Graas Network SEA. Meetings are product-agnostic.
- Products/verticals: All-e (AI agents), Hoppr (analytics), Extract, Marketplace BU.
- Pipeline stages: Meeting Being Set → MOF (Met, No Proposal) → BOF (Proposal Sent) → Won / Lost.
- India targets and SEA targets are tracked separately.
- For proposals: track Won, Lost, Open, and GP (Gross Profit) values. GP is more important than Revenue.
- For a "pipeline summary" or "sales brief": structure as Meetings (actual vs target), Pipeline Funnel (MOF/BOF counts), Proposals (by product, won/lost/open), Key accounts to watch.
- ALWAYS cite your source for every claim using the [Source: ...] tags in the data above.
- When referencing meeting notes, mention the date, who posted them, and whether Granola notes exist.
- If data is missing for a question, say so clearly rather than guessing.
"""


def build_solutions_architect_prompt(data: dict) -> str:
    """System prompt focused on presales scoping and solutions architecture."""
    today = datetime.now().strftime("%B %d, %Y")
    data_context = _build_data_context(data)

    return f"""You are the Graas AI Solutions Architect. Today is {today}.
You help the sales team prepare for customer meetings — scoping use cases, structuring discovery conversations, identifying the right all-e pitch for a specific industry or persona, handling objections, and suggesting exactly what to say and what NOT to say.

You are deeply embedded in Graas's sales methodology. You never give generic AI answers. Everything is grounded in the framework below.

{SOLUTIONS_ARCHITECT_FRAMEWORK}

=== LIVE PIPELINE DATA (for cross-referencing active leads) ===
{data_context}

SOLUTIONS ARCHITECT RULES:
- When asked to prep for a discovery call: identify the industry, map to the relevant lever(s), suggest 5-8 tailored discovery questions, recommend the 2-3 use cases most likely to resonate, and flag what to avoid saying.
- When asked for a pitch or value prop: lead with the business pain, show the current-vs-agentic workflow comparison with real numbers (e.g., 5-7 days → 3-5 minutes), map to the three levers, close with a suggested next step (POC scope).
- When asked about a specific company in the pipeline: cross-reference the Presales Tracker for their current status, last conversation notes, and any known blockers.
- When asked about integration: specify which back-end systems are needed and typical deployment timeline.
- Always use specific numbers and examples. Never say "AI can help with that" without explaining exactly how.
- Reference real customers (Canon, Schneider, Nippon Paint, PI Industries, Tata 1mg, Orient Bell, Unicharm, etc.) when relevant to the industry being discussed.
- For SEA customers: always clarify the messaging channel (WhatsApp/LINE/Zalo) before scoping.
- Don't lead with pricing — quantify their current cost first, then frame the ROI.
- ALWAYS cite your source for pipeline data using [Source: ...] tags.
"""


# ── Load Data ────────────────────────────────────────────────────────────────

all_data = load_sales_data()

# Data status expander
with st.expander("📂 Data Sources", expanded=False):
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

st.markdown("---")


# ── Tabs ─────────────────────────────────────────────────────────────────────

tab_pipeline, tab_architect = st.tabs(["📊 Pipeline Analytics", "🏗️ Solutions Architect"])


def _render_chat(
    tab_key: str,
    system_prompt_fn,
    example_prompts: list[str],
    placeholder: str,
):
    """Shared chat renderer for both tabs."""
    history_key = f"chat_{tab_key}"
    prefill_key = f"prefill_{tab_key}"

    if history_key not in st.session_state:
        st.session_state[history_key] = []

    # Example prompt buttons
    st.markdown("**Try asking:**")
    cols = st.columns(len(example_prompts))
    for i, prompt in enumerate(example_prompts):
        with cols[i]:
            if st.button(prompt, key=f"{tab_key}_ex_{i}", use_container_width=True):
                st.session_state[prefill_key] = prompt

    st.markdown("")

    # Render chat history
    for msg in st.session_state[history_key]:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                st.markdown(_style_citations(msg["content"]), unsafe_allow_html=True)
            else:
                st.markdown(msg["content"])

    # Chat input
    user_input = st.chat_input(placeholder, key=f"input_{tab_key}")

    if prefill_key in st.session_state:
        user_input = st.session_state.pop(prefill_key)

    if user_input:
        st.session_state[history_key].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    import anthropic
                    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                    system_prompt = system_prompt_fn(all_data)

                    messages = [
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state[history_key][-20:]
                    ]

                    response = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=2048,
                        system=system_prompt,
                        messages=messages,
                    )

                    assistant_msg = response.content[0].text
                    st.markdown(_style_citations(assistant_msg), unsafe_allow_html=True)
                    st.session_state[history_key].append(
                        {"role": "assistant", "content": assistant_msg}
                    )

                except Exception as e:
                    st.error(f"Error: {e}")


with tab_pipeline:
    st.caption("Track meetings vs target, deal stages, proposals won/lost, and follow-up priorities.")
    _render_chat(
        tab_key="pipeline",
        system_prompt_fn=build_pipeline_prompt,
        example_prompts=[
            "Give me a pipeline summary for Q1",
            "Which All-e deals are closest to closing?",
            "How are meetings tracking vs target?",
            "Who should we follow up with this week?",
        ],
        placeholder="Ask about pipeline, meetings, proposals, deal stages...",
    )

with tab_architect:
    st.caption("Discovery frameworks, use case scoping, industry guidance, objection handling, pitch prep.")
    _render_chat(
        tab_key="architect",
        system_prompt_fn=build_solutions_architect_prompt,
        example_prompts=[
            "Prep me for a pharma distributor discovery call in Malaysia",
            "What use cases should I pitch to an FMCG brand with field agents?",
            "Draft a value prop for a B2B consumer electronics company",
            "What's our engagement model and how do I frame the pilot?",
        ],
        placeholder="Ask about discovery, use cases, pitch framing, objection handling...",
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    if st.button("Clear Pipeline Chat"):
        st.session_state["chat_pipeline"] = []
        st.rerun()
    if st.button("Clear Architect Chat"):
        st.session_state["chat_architect"] = []
        st.rerun()
    if st.button("Refresh Data"):
        st.cache_data.clear()
        st.rerun()
