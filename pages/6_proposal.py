"""Build Proposal — Pre-sales proposal builder for All-e deals."""

import re as _re
import streamlit as st
import os
import json
from pathlib import Path
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

_env_path = str(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(_env_path, override=True)

st.set_page_config(page_title="All-e Proposal Builder | Graas", page_icon="📝", layout="wide")

# ── API key ───────────────────────────────────────────────────────────────────
try:
    ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

if not ANTHROPIC_API_KEY:
    st.warning("Add `ANTHROPIC_API_KEY` to `.streamlit/secrets.toml` or `.env` to enable this page.")
    st.stop()


# ── Pre-Sales Proposal Skill — baked in ──────────────────────────────────────

PRE_SALES_PROPOSAL_SKILL = """
You are a Graas pre-sales engineer. Your job is to take discovery inputs (meeting notes, questionnaire answers, prospect research) and produce a customer-ready proposal. You are not a document formatter — you are a solutions architect who thinks commercially.

## THE CARDINAL RULE: SOLUTION FIRST, THEN ASK ABOUT RISK

Never jump straight to risk mitigation. Your instinct should be to solution 2-3 technically distinct approaches, present their trade-offs (commercial impact vs. integration risk vs. timeline), and let the team choose. Only then do you build gates and safeguards around the chosen approach.

The failure mode is: receiving discovery inputs → immediately worrying about what could go wrong → proposing a cautious, low-integration pilot that proves something the customer already believes → losing commercial impact.

The correct mode is: receiving discovery inputs → understanding what the customer actually needs in production → designing 2-3 solution architectures that deliver production value → presenting trade-offs → building the chosen approach into a proposal.

Example of what NOT to do:
- Customer confirms 70-80% fit, has confirmed use cases, has existing WABA, has a DMS vendor willing to co-build APIs
- You propose: "4-6 week POC on static data with no integrations, elaborate 3-gate framework, separate fraud detection as future phase"
- This optimises for risk at the expense of commercial impact

Example of what TO do:
- Same inputs
- Option A: "Go straight to production integration — 6-8 weeks, FSA ordering with embedded fraud signals, orders pushed to DMS via API co-built with vendor. Higher risk, higher commercial impact, $25K one-time."
- Option B: "Paid pilot on static data first, prove the intelligence layer, then integrate. Lower risk, but customer doesn't see production value for 3+ months."
- Option C: "Hybrid — Phase 1 is FSA ordering with integration, Phase 2 is retailer self-serve that builds on Phase 1 infrastructure."
- Then ask: "Which approach fits this customer's risk appetite and urgency?"

## STEP-BY-STEP WORKFLOW

### Step 1: Ingest and Organise Discovery Inputs

Read everything: meeting notes, questionnaire answers, prospect research. Extract and organise:
- Business facts: Revenue, scale, geography, distribution structure, growth rate
- Current tech stack: ERP, DMS, SFA, CRM — vendor names, API availability, who built what
- Confirmed pain points: In the customer's own words, ranked by their stated priority
- Quantifiable metrics: Order volumes, average values, percentages (out-of-route orders, cash collection, fraud rates)
- People: Who attended meetings, who has decision authority, who controls the tech stack
- What's already been committed: Pilot scope, geography, BU, success metrics the customer defined

Data quality check:
- Flag any numbers that seem inconsistent
- Flag any gaps that affect solutioning (e.g., no clarity on API availability)
- Flag anything the customer said that contradicts itself across meetings
- Present these flags to the team before building the proposal

### Step 2: Identify the CFO Metric (Revenue Leakage Analysis)

Every proposal must answer: "What is this costing the customer today?" before describing what Graas will do.

Use the three-lever framework:
- Revenue lever: Orders not captured, basket value left on the table, schemes under-utilised, channels that lose orders
- Cost lever: Fraud exposure, logistics waste, manual processing time, headcount on repetitive tasks
- Experience lever: Relationship loss on rep turnover, no self-serve channel, long order capture TAT

For each leakage category:
1. Calculate from confirmed data where possible (order volume × average value × affected percentage)
2. Where you can't calculate, state what's known and what needs to be confirmed
3. NEVER invent numbers. If you don't have the data, say "baseline TBD" and explain how the engagement establishes the baseline
4. Map each leakage to the product/agent that addresses it and the phase in which it's addressed

### Step 3: Solution — Present 2-3 Technical Approaches

Do not default to the safest option. Present genuinely different approaches with honest trade-offs.

For each approach, define:
- Architecture: What agents, what surfaces (WhatsApp, SFA, portal), what integrations, what data flows
- Phasing: What's Phase 1 vs Phase 2, and why that sequencing
- Integration model: Live APIs from day one vs. static data first vs. hybrid
- What it proves / delivers: What the customer gets at each phase
- Timeline: Realistic build + deployment + measurement time
- Commercial shape: One-time + monthly, pricing anchors from comparable deals
- Risk: What could go wrong, and who bears that risk (Graas, customer, or third party)
- Dependencies: What must the customer provide, and what third parties are involved

Key solutioning principles:
1. Embed intelligence into workflows, don't create standalone agents. Fraud detection should be a property of every order, not a separate dashboard.
2. Sequence personas, not features. Phase 1 = field agents (controlled). Phase 2 = retailers (uncontrolled adoption). This is almost always right for GT/distribution.
3. If a vendor is willing to co-build APIs, go direct to integration. A static-data pilot only makes sense when integration is truly unpredictable.
4. Fraud/anomaly detection belongs inside the ordering flow — embed fraud signals (geo-validation, photo capture, history-based anomaly scoring, duplicate detection, retailer confirmation notifications) directly into the agent's order capture workflow.
5. Use comparable deals to anchor: Agricon (Indonesia, agri-chem, $16K one-time + $4K/month, 300 FAs 6K retailers), Canon (India, industrial printers, lead routing + dealer ordering), Nippon (India, paint, distributor ordering), Sunway SMP (Malaysia, pharmacy, inventory intelligence).

### Step 4: Present Trade-Offs and Get a Decision

After presenting the approaches, explicitly ask:
- "Which approach fits this customer's risk appetite and urgency?"
- "Are there commercial constraints I should know about?"
- "Is there a reason to go cautious here that I'm not seeing?"

Do not build the full proposal until the team has chosen an approach.

### Step 5: Build the Proposal Document

Once the approach is chosen, produce the full proposal in structured markdown. Structure:

1. Executive Summary (half a page max)
   - Size of the problem (revenue leakage numbers)
   - What we're proposing (product, channel, use cases)
   - Phasing and timeline
   - Commercial shape in one sentence

2. Context & Confirmed Understanding
   - Customer background
   - Confirmed facts table — "SDN should confirm that the facts below are correctly stated before proceeding"

3. Revenue Leakage Analysis
   - Quantified problem by lever
   - Summary table: Leakage Category | Estimated Impact | Addressed By | Phase
   - Honest about what's calculated vs. what's TBD

4. Solution (Current vs. Agentic)
   - For each phase/use case: side-by-side table showing current workflow, agentic workflow, expected impact
   - Explain the consumption surface (WhatsApp, SFA, portal) and why
   - If intelligence is embedded inline, explain this clearly

5. Scope of Work (by phase)
   - Objective, channel, persona, categories, languages, core capabilities, integrations, out of scope
   - Pre-conditions: what the customer must provide before each phase starts
   - Timeline: realistic, with the clock starting on data/access receipt, not contract signature

6. Success Metrics / KPIs
   - Concrete, measurable, with targets
   - Gating conditions vs. outcome indicators (match to customer's risk appetite)
   - Who evaluates, what timeline for sign-off, what happens on pass/fail

7. Commercials
   - One-time fees by phase (what's included)
   - Monthly retainer (conversations included, overage rate)
   - Meta/WhatsApp charges (actuals or passthrough with surcharge)
   - Payment schedule: 50% advance, 50% on agent delivery for UAT
   - Always anchor to comparable deals, adjust for customer scale

8. Next Steps
   - Action table: #, Action, Owner, Dependency
   - Make dependencies explicit

9. Proposal Acceptance
   - Signature block for both parties

What NOT to include:
- Elaborate multi-gate frameworks with 9-metric tables when the customer is ready for production
- "What Sets Graas Apart" competitive sections (unless customer is evaluating multiple vendors — ask the team)
- Technical architecture diagrams (save for the joint technical workshop)
- References to "Agent X" — the product is called All-e

## COMMERCIAL BENCHMARKS

| Deal | Geography | Vertical | One-Time | Monthly | Scale |
|------|-----------|----------|----------|---------|-------|
| Agricon | Indonesia | Agri-chem | USD 16K | USD 4K | 300 FAs, 6K retailers |
| SDN (proposed) | Indonesia | Distribution | USD 25K (Ph1) + USD 15K (Ph2) | USD 6K | 400 FSAs, 230K retailers |

Pricing logic:
- One-time fee covers: agent setup, Knowledge Graph build, model fine-tuning, API integration co-build (if applicable), WABA setup, language tuning
- Monthly retainer includes a conversation envelope (e.g., 150K conversations/month); overage at $0.08-0.12/conversation
- Meta WhatsApp charges: either customer pays Meta directly, or Graas manages with 20% admin surcharge
- Payment schedule: 50% advance on signed acceptance, 50% on agent delivery for UAT

Scale adjustments:
- More SKUs = more Knowledge Graph complexity = higher one-time
- More FAs/retailers = higher conversation volume = higher monthly
- More integrations = more one-time (each API surface is work)
- Multi-language = tuning cost in one-time

## ANTI-PATTERNS TO AVOID

1. The risk-first proposal — starting with what could go wrong instead of what value the customer gets
2. Static-data pilot when integration is feasible — if the DMS/ERP vendor will co-build APIs, go to production
3. Separating intelligence from transactions — embed sales intelligence inline within the ordering workflow
4. Deferring fraud to a future phase — fraud signals can be built into the ordering flow from day one
5. Over-engineering gates — match gating complexity to the customer's risk appetite, not to your own
6. Hallucinating numbers — NEVER invent revenue figures, ROAS, GMV percentages, or fraud rates. Only use confirmed data. If implausible, flag for confirmation. Say "baseline TBD" if you can't calculate it.

## TERMINOLOGY

- The product is All-e (not Agent X)
- Use "Pilot" not "POC" unless the customer has used that term
- "Conversations" not "messages" or "queries"
- "Knowledge Graph" is fine — it's the right technical term for the intelligence layer
- "Field agents" / "FSAs" (field sales agents) — clarify which term the customer uses
- Don't use "GAF" (Graas Agent Foundry) with customers
"""


# ── System prompt builder ─────────────────────────────────────────────────────

def build_proposal_system_prompt(context: dict) -> str:
    today = datetime.now().strftime("%B %d, %Y")

    context_section = ""
    if any(context.values()):
        parts = []
        if context.get("company"):
            parts.append(f"Company: {context['company']}")
        if context.get("vertical"):
            parts.append(f"Vertical / Industry: {context['vertical']}")
        if context.get("geography"):
            parts.append(f"Geography: {context['geography']}")
        if context.get("contacts"):
            parts.append(f"Key Contacts: {context['contacts']}")
        if context.get("stage"):
            parts.append(f"Deal Stage: {context['stage']}")
        if context.get("notes"):
            parts.append(f"\nDiscovery inputs:\n{context['notes']}")
        context_section = "\n=== DEAL CONTEXT ===\n" + "\n".join(parts)

    return f"""You are a Graas pre-sales engineer building a commercial proposal for All-e (Graas's agentic retail platform). Today is {today}.

{PRE_SALES_PROPOSAL_SKILL}

{context_section}

YOUR BEHAVIOUR:
- When given discovery inputs: FIRST produce a clean data extraction (business facts, tech stack, pain points, metrics, people), then flag any data quality issues or gaps.
- Then identify the CFO metric — quantify revenue leakage from confirmed data only. Say "baseline TBD" if you can't calculate something.
- Then present 2-3 technically distinct solution approaches with honest trade-offs. Ask the team to choose before building the full proposal.
- Once an approach is chosen: produce the full proposal in clean markdown, following the 9-section structure.
- Format numbers clearly. Format tables in markdown.
- Never invent numbers. If a stat seems implausible, flag it.
- Keep the executive summary tight — half a page.
- Output long proposals in full — don't truncate. The team needs the complete document.
"""


# ── Page UI ───────────────────────────────────────────────────────────────────

st.markdown("## 📝 All-e Proposal Builder")
st.caption("From discovery inputs to a customer-ready commercial proposal — solution first, risk second")

with st.expander("ℹ️ How to use this — read once, then collapse", expanded=False):
    st.markdown("""
### What this does

Turns confirmed discovery findings into a **customer-ready commercial proposal**. Different from the Prospect Brief (that's pre-call research) and the Architect chat (that's brainstorming) — this builds the actual document you'd send to the prospect's CIO/CFO after qualification is done.

### When to use it

| Stage | What's expected | Use this page? |
|---|---|---|
| Pre-call | Just research, no calls yet | No — use **Create Prospect Brief** first |
| During discovery | Open questions, unconfirmed assumptions | No — use **Architect a Soln** to think out loud |
| **Qualification gate met** | Decision-maker known · budget identified · data readiness understood · CFO metric confirmed | **✅ Use this page** |
| Re-proposal | Customer asked for revisions to a previous proposal | ✅ Paste the previous proposal + the asks |

### What to paste in Discovery Inputs

Quality of output is bounded by quality of input. The more concrete the inputs, the more commercial the proposal.

**Strong inputs**
- Confirmed numbers from the customer (revenue, FSAs, retailers, order volumes, current TAT)
- Tech stack with vendor names + who built what (e.g. "DMS = SalesPoint, built by local vendor, API access available")
- Direct quotes on pain in the customer's words ("our reps spend half their day on the phone chasing collections")
- What's already been committed (pilot scope, geography, BU, success metrics they defined)
- Decision authority and budget owner (who signs off, when the budget cycle is)

**Weak inputs that produce vague proposals**
- "Generic FMCG company, wants AI to improve sales" — no numbers, no scope, no metric
- Aggregator estimates without a confirmation pass ("LeadIQ says $50M revenue")
- Internal speculation about what they need ("they probably want WhatsApp ordering")

### The cardinal rule baked into this skill

**Solution first, then ask about risk.** The output will give you **2-3 distinct technical approaches** with trade-offs (commercial impact vs. integration risk vs. timeline) — not a single cautious option. Pick the one that matches the customer's risk appetite, then ask the chat to build it out.

### Iteration loop

1. Fill in Deal Context + Discovery Inputs on the left
2. Click **Build proposal** — gets the first cut on the right
3. **Push back** in the chat: *"Add a Phase 2 for retailer self-serve"*, *"Reframe the commercial as a 60-day paid pilot"*, *"This is too cautious — give me the production-integration option"*
4. **Quantify the CFO metric** — *"What does 5-7 day order TAT actually cost them in working capital? Show the math."*
5. When the proposal feels right, copy it out and send.

### What this won't do (yet)

- It won't save to Drive — copy/paste into a Doc yourself, or use the **Download** action when you see one in the future.
- It won't fetch the latest pricing — pricing logic is in the skill, but if commercial framing has shifted recently, double-check before sending.
""")
    st.markdown("---")

# Two-column layout: inputs on the left, chat on the right
left, right = st.columns([1, 1.8], gap="large")

with left:
    st.markdown("### Deal Context")
    st.caption("Fill in what you have. Everything is optional but more context = better output.")

    company = st.text_input("Company name", placeholder="e.g. SDN Bhd, Agricon Indonesia")
    col_v, col_g = st.columns(2)
    with col_v:
        vertical = st.text_input("Vertical", placeholder="FMCG, Pharma, Agri...")
    with col_g:
        geography = st.text_input("Geography", placeholder="India, Indonesia, MY...")
    contacts = st.text_input("Key contacts", placeholder="e.g. Ravi (CTO), Priya (VP Sales)")
    stage = st.selectbox(
        "Deal stage",
        ["Initial discovery", "Discovery complete", "Proposal requested", "Re-proposal / revision", "Negotiation"],
    )

    st.markdown("### Discovery Inputs")
    st.caption("Paste meeting notes, questionnaire answers, email threads — anything relevant.")
    notes = st.text_area(
        "Discovery notes",
        height=280,
        placeholder=(
            "e.g.\n"
            "- Met Ravi (CTO) and Priya (VP Sales) on 28 Apr\n"
            "- 400 FSAs across 3 regions, visiting ~25 retailers/day\n"
            "- Currently using SAP ERP + custom DMS built by local vendor\n"
            "- Vendor confirmed willing to expose APIs\n"
            "- ~18% of orders still taken on paper, entered manually (5-7 day lag)\n"
            "- Fraud rate estimated at 2-3% of GMV (~USD 2M/month)\n"
            "- They want WhatsApp-first, low-tech retailers can't use apps\n"
        ),
        label_visibility="collapsed",
    )

    deal_context = {
        "company": company,
        "vertical": vertical,
        "geography": geography,
        "contacts": contacts,
        "stage": stage,
        "notes": notes,
    }

    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        start_btn = st.button("🚀 Start Proposal", use_container_width=True, type="primary")
    with btn_col2:
        clear_btn = st.button("🗑 Clear", use_container_width=True)

    if clear_btn:
        st.session_state["proposal_messages"] = []
        st.rerun()

    st.markdown("---")
    st.markdown("**Quick starts:**")
    quick_prompts = [
        "Analyse my discovery inputs and flag any data quality issues",
        "Show me the revenue leakage analysis",
        "Give me 3 solution options with trade-offs",
        "Build the full proposal — I'm going with Option A",
        "What should the commercials look like for this deal?",
    ]
    for qp in quick_prompts:
        if st.button(qp, key=f"qp_{qp[:20]}", use_container_width=True):
            st.session_state["proposal_prefill"] = qp


with right:
    st.markdown("### Proposal Builder")

    # Chat history
    if "proposal_messages" not in st.session_state:
        st.session_state.proposal_messages = []

    # Chat display container
    chat_container = st.container(height=520)
    with chat_container:
        if not st.session_state.proposal_messages:
            st.markdown("""
<div style="color:#9CA3AF;padding:40px 20px;text-align:center;">
<div style="font-size:2rem;margin-bottom:8px;">📝</div>
<div style="font-weight:600;margin-bottom:6px;">Ready to build a proposal</div>
<div style="font-size:0.9rem;">Fill in the deal context and discovery notes on the left,<br>then click <strong>Start Proposal</strong> or ask a question below.</div>
</div>
""", unsafe_allow_html=True)
        else:
            for msg in st.session_state.proposal_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

    # Chat input
    user_input = st.chat_input("Ask anything about this deal — or say 'build the proposal'...")

    # Handle prefill from quick buttons
    if "proposal_prefill" in st.session_state:
        user_input = st.session_state.pop("proposal_prefill")

    # Handle Start Proposal button
    if start_btn:
        if not notes.strip() and not company.strip():
            st.warning("Add at least a company name or some discovery notes before starting.")
        else:
            user_input = (
                f"I've shared the discovery inputs for {company or 'this prospect'}. "
                f"Please analyse them: extract the key business facts, flag any data quality issues or gaps, "
                f"then show me the revenue leakage analysis. "
                f"After that, give me 2-3 solution options with honest trade-offs so we can decide the approach."
            )

    if user_input:
        st.session_state.proposal_messages.append({"role": "user", "content": user_input})

        with st.spinner("Thinking..."):
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                system = build_proposal_system_prompt(deal_context)

                messages = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.proposal_messages[-20:]
                ]

                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,  # Proposals can be long
                    system=system,
                    messages=messages,
                )

                assistant_msg = response.content[0].text
                st.session_state.proposal_messages.append(
                    {"role": "assistant", "content": assistant_msg}
                )
                st.rerun()

            except Exception as e:
                st.error(f"Error: {e}")

    # Download button if there's a substantial output
    if len(st.session_state.proposal_messages) > 1:
        full_convo = "\n\n".join(
            f"{'USER' if m['role']=='user' else 'GRAAS AI'}: {m['content']}"
            for m in st.session_state.proposal_messages
        )
        st.download_button(
            "⬇️ Download conversation",
            data=full_convo,
            file_name=f"proposal_{(company or 'draft').replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.txt",
            mime="text/plain",
            use_container_width=True,
        )
