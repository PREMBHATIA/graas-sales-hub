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

## NON-NEGOTIABLE: EVERY PROPOSAL OPENS WITH A FRONT-PAGE SUMMARY

Every full proposal you produce MUST start with a self-contained front-page summary that a CIO or CFO can read in 60 seconds and walk away knowing:

1. **The headline value proposition** — one line, in their language, naming the business outcome (not "AI-powered insights" — "shift 30% of dealer ordering from phone calls to WhatsApp self-serve, freeing field reps to focus on net-new acquisition").
2. **The big numbers** — 3-4 at-a-glance stats from the deal: scale (e.g. "40K rural retailers"), current state pain (e.g. "92 full-time tele-callers at scale"), expected outcome (e.g. "8K additional orders/month"), and the commercial ask (e.g. "INR 6L Paid POC"). Format these as a horizontal stat band, not buried in prose.
3. **What we're delivering** — 2-4 concrete capabilities (not categories). "Voice-based agentic ordering on WhatsApp" beats "AI-powered customer engagement."
4. **The CFO metric** — the single number this moves for them, named explicitly with the decision-maker's role: "The metric this moves for [CFO name] is [DSO reduction / cost-per-order / orders captured / revenue per rep]."
5. **Timeline** — total duration and phases in one line (e.g. "12 weeks: 4-week Discovery → 6-week Build → 2-week Production handover").
6. **Commercial** — the ask, framed as investment (not cost): "INR 6L one-time + INR X/month from Production onwards."
7. **The decision you're asking for** — explicit: "We're asking you to approve the Paid POC and align on the [region/BU] for Phase 1 by [date]."

This front-page summary IS the proposal for everyone except the buyer. The buyer will read the body; their CFO, board, and procurement will only read the front page. If the front page doesn't sell, the deal dies in their internal review even if the body is brilliant.

**Format the front page distinctly** so it's visually separate from the body — H1 with the company name and proposal type, a stat band, then the 7 elements above in tight bulleted form. Refer to the Castrol and Nippon reference proposals (when loaded) for the visual rhythm.

Never produce a proposal body without producing this front page first. If discovery inputs are too thin to fill the front page honestly, STOP and tell the team which 2-3 facts are missing — don't dilute the summary with vague language to fill the gaps.

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

Once the approach is chosen, produce the full proposal in structured markdown. **Every full proposal must contain every section below, in this order. Do not omit a section — if a section truly doesn't apply, write one line saying so and why.**

**HEADER** (top of doc, before the front-page summary)
   - Company name + parent/group (e.g. "Prepared for Nippon Paints India (Wuthelam Group)")
   - Use case title + subtitle (one line that names the play, e.g. "All-e for Dealer Ordering & Collections — Paid POC scope")
   - Date prepared · **Valid Until** (default: 14 days from today)
   - Prepared by GraasAI · Prepared for [Company]

1. **Front-page Summary** (the CFO-readable opener — see the NON-NEGOTIABLE section above; mandatory)

2. **Executive Summary** (half a page max — expands the front page into prose)
   - Who the client is, what is being proposed, why it matters
   - Size of the problem (revenue leakage numbers)
   - Phasing and timeline
   - Commercial shape in one sentence

3. **What Sets GraasAI Apart** (3-4 differentiation pillars, *tailored to this client* — don't copy boilerplate)
   - Pick from: **Voice-Native Intelligence** (agents that work over voice + WhatsApp, not just text bots), **Distribution-Grade Execution** (built for GT/distribution-network scale, not white-collar pilots), **App-Agnostic / Channel-Agnostic** (works on the customer's existing WABA, SFA, or web — no rip-and-replace), **Enterprise-Ready Architecture with Governance** (audit trails, role-based access, data residency), **Shared Knowledge Graph / Model Tuning** (the KG that powers the agent is itself an asset the customer owns or co-owns)
   - Each pillar = one bolded label + 2-3 lines explaining what it means *for this customer's situation*
   - If the customer is evaluating multiple vendors, lean harder on the pillar that breaks the tie

4. **Context & Confirmed Understanding**
   - Customer background (one paragraph)
   - Confirmed facts table — "Please confirm the facts below before we proceed"

5. **Current State → Future State** [MANDATORY — one before/after row per use case]
   - For each use case, a structured before/after that quantifies the baseline:
   - Table columns: Use case | Current flow (with TAT, headcount, or volume baseline) | Future flow with All-e | Target metric (TAT reduction / cost saving / orders captured / DSO)
   - If a baseline is genuinely unknown, write "baseline TBD — to be established in Phase 1" — never invent one
   - This is the single picture of why this proposal exists; do not skip it even for a single-use-case POC

6. **Revenue Leakage Analysis**
   - Quantified problem by lever (revenue / cost / experience)
   - Summary table: Leakage Category | Estimated Impact | Addressed By | Phase
   - Honest about what's calculated vs. what's TBD

7. **Scope of Work**
   - 7.1 **Use Case(s) and Parameters** — use case name, pilot size (retailers/distributors/FSAs in scope), geography, language(s), modality (voice/text/both)
   - 7.2 **Integration Scope** — systems to integrate (name them), depth (read/write, real-time/batch, API or file drop), what's explicitly out of scope
   - 7.3 **What Graas Delivers** — concrete bullet list (the agent, the KG build, the integration, the dashboards, the tuning)
   - 7.4 **What Client Provides** — data, API access, named contacts, approvals needed, WABA/telephony setup, sandbox environment — be specific, no ambiguity
   - 7.5 **Pre-conditions** — what must be true before the phase clock starts (data delivered, API stubs available, decision-maker aligned)

8. **Success Metrics / KPIs**
   - **Minimum two KPIs**, each with **a target AND a baseline** (baseline TBD is allowed if it's calibrated in Phase 1)
   - Must include the **primary CFO-lens metric** (cost efficiency / revenue uplift / TAT reduction)
   - Mark each KPI as **directional** (an indicator we track) or a **hard gating condition** (failing it kills the next phase)
   - Who evaluates, on what timeline, what happens on pass/fail

9. **Technical & Commercial**
   - 9.1 **Architecture Overview** — deployment model (cloud / customer cloud / on-prem), integration path, governance/audit, monitoring
   - 9.2 **Commercials — three tiers, clearly separated**: **POC/Demo** | **Pilot** | **Production**. For each: one-time fee, monthly retainer, conversation volume included, overage rate. Plus Meta/telephony charge model (customer pays direct, or passthrough with admin surcharge). Anchor to comparable deals.
   - 9.3 **Timelines** — phase-wise with key milestones (kickoff, integration cut, UAT, go-live, end-of-POC review). The clock starts on data/access receipt, not contract signature.
   - 9.4 **Payment Schedule** — standard: 50% advance + 50% on delivery for one-time fees; monthly retainer billed by the 7th of each month

10. **Post-POC — Path to Production** [MANDATORY for any POC or Pilot proposal]
    - What carries forward from the POC (the agent, the KG, the integration, the tuned models) — and what doesn't
    - What the production proposal will cover (full scale, additional use cases, ongoing monthly)
    - Expected timeline from POC sign-off to production go-live

11. **Next Steps**
    - Numbered, action-owner tagged: # | Action | Owner | Dependency | Target date
    - Dependencies must be explicit (e.g. "Owner: Customer IT. Dependency: SAP sandbox credentials.")

12. **Contracting Note** [include ONLY if there's a known constraint]
    - Vendor onboarding freeze, parent-company procurement process, NDA prerequisite, SPV / special-entity structure, regulatory pre-approval — name the constraint and the path through it
    - Omit the section entirely if none of these apply

13. **Proposal Acceptance**
    - Acceptance method (countersigned PDF, PO reference, signed email)
    - Validity reminder ("This proposal is valid until [Valid Until date]")
    - Confidentiality note (one line)
    - Signature block for both parties

What NOT to include:
- Elaborate multi-gate frameworks with 9-metric tables when the customer is ready for production
- Technical architecture diagrams (save for the joint technical workshop)
- References to "Agent X" — the product is called All-e
- Boilerplate differentiation pillars — every *What Sets Apart* pillar must connect to a fact from this customer's discovery

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
- Frame commercials as **investment**, not cost

## PRE-SEND QUALITY CHECKLIST — RUN BEFORE EVERY PROPOSAL GOES OUT

Before finalising any proposal, confirm every line below. If any item fails, fix it or surface the gap to the team — do not send a proposal with red flags.

- [ ] **Front-page summary** present, with all 7 elements (headline value prop, big numbers stat band, what we deliver, CFO metric named, timeline, commercial-as-investment, decision asked for)
- [ ] **What Sets GraasAI Apart** has 3-4 pillars, each tailored to a specific fact from this customer's discovery — no boilerplate
- [ ] **Current → Future** table present for every use case, with quantified baselines (or honest "baseline TBD")
- [ ] **KPIs** have both **target AND baseline** (or "baseline TBD" calibrated in Phase 1); the primary CFO-lens metric is one of them
- [ ] **Commercials cover all three tiers**: POC/Demo · Pilot · Production — each with one-time + monthly + conversation volume + overage
- [ ] **Timelines** included for each phase (kickoff → integration → UAT → go-live → review), with the clock starting on data/access receipt
- [ ] **What Client Provides** is unambiguous — every data feed, API, contact, approval, and dependency is named
- [ ] **Post-POC — Path to Production** section is present (mandatory for any POC/Pilot)
- [ ] **Valid Until** date set (default: 14 days from send date)
- [ ] **Payment Schedule** stated (50% advance + 50% on delivery for one-time; by 7th of month for monthly)
- [ ] **Contracting Note** included only if there's a real constraint (omit otherwise)
- [ ] **Tone check** — factual, outcome-led, customer-language, no AI buzzwords ("seamless", "enterprise-grade", "AI-powered", "moment of intent")
- [ ] **Numbers check** — every revenue / volume / percentage figure traces back to discovery or is marked TBD; no invented baselines
- [ ] **Casing** — All-e (not Agent X), hoppr, Turbo, Extract, Graas
"""


# ── System prompt builder ─────────────────────────────────────────────────────

def build_proposal_system_prompt(context: dict, reference_docs: list = None) -> str:
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

    # Reference proposals — actual Graas docs to draw patterns from.
    # The proposal-writing skill teaches the *approach*; these show the
    # *shape* (commercial framing, capability bundles, integration scope,
    # voice positioning where applicable).
    ref_section = ""
    if reference_docs:
        chunks = [
            "\n\n============================================================",
            f"REFERENCE PROPOSALS — {len(reference_docs)} loaded",
            "============================================================",
            "Below are real Graas proposals (full text). Use them as PATTERNS:",
            "  - Commercial framing (pricing structure, phases, milestones)",
            "  - Capability bundles (which agents/use cases go together)",
            "  - Integration scope language",
            "  - Voice / new-capability positioning when relevant",
            "  - How risk gates are framed without losing commercial impact",
            "Cite them by name when an approach maps to the deal at hand.",
            "Do NOT copy text verbatim — adapt to this deal's specifics.",
            "",
        ]
        for d in reference_docs:
            chunks.append(f"\n--- BEGIN: {d['name']} ---\n{d['text']}\n--- END: {d['name']} ---\n")
        ref_section = "\n".join(chunks)

    return f"""You are a Graas pre-sales engineer building a commercial proposal for All-e (Graas's agentic retail platform). Today is {today}.

{PRE_SALES_PROPOSAL_SKILL}

{context_section}

{ref_section}

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
    st.markdown("#### What this does")
    st.markdown(
        "Turns confirmed discovery findings into a **customer-ready commercial "
        "proposal**. Different from the **Prospect Brief** (that's pre-call research) "
        "and the **Architect** chat (that's brainstorming) — this builds the actual "
        "document you'd send to the prospect's CIO/CFO after qualification is done."
    )

    st.markdown("#### When to use it (vs. the other All-e pages)")
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.markdown("##### Pre-call")
        st.caption("Just research, no calls yet")
        st.warning("Use **Create Prospect Brief** first.")
    with s2:
        st.markdown("##### Discovery in flight")
        st.caption("Open questions, unconfirmed assumptions")
        st.warning("Use **Architect a Soln** to think out loud.")
    with s3:
        st.markdown("##### Qualification met ✅")
        st.caption(
            "Decision-maker known · budget identified · data readiness "
            "understood · CFO metric confirmed by the customer"
        )
        st.success("Use this page.")
    with s4:
        st.markdown("##### Re-proposal")
        st.caption("Customer asked for revisions")
        st.success("Use this page. Paste the prior proposal + the asks.")

    st.markdown("#### What to paste in Discovery Inputs")
    st.markdown(
        "Quality of output is bounded by quality of input. "
        "The more concrete the inputs, the more commercial the proposal."
    )
    in1, in2 = st.columns(2)
    with in1:
        st.markdown("##### ✅ Strong inputs")
        st.markdown(
            "- **Confirmed numbers** from the customer (revenue, FSAs, retailers, "
            "order volumes, current TAT)\n"
            "- **Tech stack with vendor names** + who built what "
            "(*\"DMS = SalesPoint, built by local vendor, API access available\"*)\n"
            "- **Direct quotes on pain** in the customer's words "
            "(*\"our reps spend half their day chasing collections\"*)\n"
            "- **What's already committed** (pilot scope, geography, BU, "
            "success metrics they defined)\n"
            "- **Decision authority + budget cycle**"
        )
    with in2:
        st.markdown("##### ❌ Weak inputs that produce vague proposals")
        st.markdown(
            "- *\"Generic FMCG company, wants AI to improve sales\"* "
            "— no numbers, no scope, no metric\n"
            "- Aggregator estimates without a confirmation pass "
            "(*\"LeadIQ says $50M revenue\"*)\n"
            "- Internal speculation about what they need "
            "(*\"they probably want WhatsApp ordering\"*)"
        )

    st.markdown("#### What every full proposal MUST open with")
    st.success(
        "**A front-page summary the CFO/board can read in 60 seconds.** "
        "Big numbers, the CFO metric named with the decision-maker, "
        "what we're delivering (concrete capabilities), timeline, commercial as investment, "
        "and the decision being asked for.\n\n"
        "The body sells the buyer; the **front page** sells everyone else "
        "(CFO, board, procurement) who only reads page 1. If the front page is weak, "
        "push back in the chat: *\"Tighten the front page — the big numbers don't land\"* "
        "or *\"Add a Castrol-style stat band\"*."
    )

    st.markdown("#### The cardinal rule baked into this skill")
    st.info(
        "**Solution first, then ask about risk.** "
        "The output gives you **2–3 distinct technical approaches** with trade-offs "
        "(commercial impact vs. integration risk vs. timeline) — not a single cautious "
        "option. Pick the one that matches the customer's risk appetite, then ask the "
        "chat to build it out."
    )

    st.markdown("#### Iteration loop")
    st.markdown(
        "1. Fill in **Deal Context + Discovery Inputs** on the left\n"
        "2. Click **Build proposal** — first cut renders on the right\n"
        "3. **Push back in chat:** *\"Add a Phase 2 for retailer self-serve\"*, "
        "*\"Reframe the commercial as a 60-day paid pilot\"*, *\"Too cautious — "
        "give me the production-integration option\"*\n"
        "4. **Quantify the CFO metric:** *\"What does 5–7 day order TAT cost them "
        "in working capital? Show the math.\"*\n"
        "5. When the proposal feels right, copy it out and send."
    )

    st.markdown("#### Known limitations")
    st.markdown(
        "- **No Drive save yet** — copy/paste into a Doc yourself for now.\n"
        "- **No live pricing fetch** — pricing logic is baked into the skill; "
        "if commercial framing has shifted recently, double-check before sending."
    )
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

    # ── Reference proposals ──────────────────────────────────────────────────
    # Real Graas proposals injected into the system prompt as patterns to
    # draw from. Folder ID configurable via REFERENCE_PROPOSALS_FOLDER env
    # var; defaults to the SalesHub Shared Drive's 'Reference Proposals /
    # Knowledge Base' folder.
    st.markdown("### Reference Proposals")
    st.caption("Pick 1–3 real Graas proposals for this deal's pattern (commercial framing, "
               "capability bundles, integration scope). Leave empty to rely on the playbook alone.")

    REFERENCE_PROPOSALS_FOLDER = os.getenv(
        "REFERENCE_PROPOSALS_FOLDER",
        "1tBMrcpiIDVhg5e0-N1ytjuzbDexQyheX",
    )

    @st.cache_data(ttl=3600)
    def _list_refs():
        from services.sheets_client import list_drive_folder_docs
        return list_drive_folder_docs(REFERENCE_PROPOSALS_FOLDER)

    @st.cache_data(ttl=3600)
    def _fetch_ref_text(doc_id: str) -> str:
        from services.sheets_client import fetch_drive_doc_text
        return fetch_drive_doc_text(doc_id)

    def _clean_ref_name(raw: str) -> str:
        s = raw
        for prefix in ("Copy of ", "Copy of"):
            if s.startswith(prefix):
                s = s[len(prefix):].strip()
                break
        return s

    ref_options = _list_refs()
    if ref_options:
        picked_ref_names = st.multiselect(
            "📚 Reference proposals",
            options=[_clean_ref_name(r["name"]) for r in ref_options],
            key="proposal_picked_refs",
            label_visibility="collapsed",
        )
    else:
        picked_ref_names = []
        st.caption("⚠️ No proposals found in the reference folder. Drop some Google Docs in "
                   "the `Reference Proposals / Knowledge Base` folder to use them here.")

    reference_docs = []
    if picked_ref_names:
        name_to_doc = {_clean_ref_name(r["name"]): r for r in ref_options}
        for name in picked_ref_names:
            meta = name_to_doc.get(name)
            if not meta:
                continue
            text = _fetch_ref_text(meta["id"])
            if text:
                reference_docs.append({"name": name, "text": text})
        if reference_docs:
            st.caption(f"📚 Loaded **{len(reference_docs)}** proposal(s) "
                       f"(~{sum(len(d['text']) for d in reference_docs) // 1000}K chars).")

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
                system = build_proposal_system_prompt(deal_context, reference_docs=reference_docs)

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
