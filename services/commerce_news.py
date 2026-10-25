"""Shared commerce-tech news fetcher.

Used by:
  - pages/9_prospect_brief.py — surfaces 1 story per session in the
    "While you wait" card during brief generation
  - pages/3_crm.py            — surfaces all 3 stories on the
    "📰 Newsworthy" tab as email talking points for Dhanashree

Uses Claude + web_search to fetch up to 3 distinct, high-impact stories
from the last 21 days. Cached 24h via Streamlit's cache_data so both
pages share one fetch per day per instance.

HARD RULE — NO HALLUCINATION: every claim in `body` must trace to the
cited source. Stories without a verifiable URL are dropped.
"""

from __future__ import annotations

import os
import streamlit as st


ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


_PROMPT_TMPL = (
    "Use web_search to find UP TO {count} distinct, HIGH-IMPACT news items "
    "from the LAST {days} DAYS for an enterprise retail-AI sales team.\n\n"

    "WHAT WE WANT — in priority order:\n"
    "  1. ENTERPRISE AI ARCHITECTURE: context layers, knowledge graphs, "
    "ontologies, semantic layers, agent infrastructure, the data foundation "
    "enterprises need before agents work. Vendor launches AND critiques.\n"
    "  2. ANALYST / CONSULTING RESEARCH: McKinsey, BCG, Bain, Gartner, "
    "Forrester, Deloitte, Accenture — on agentic AI, retail transformation, "
    "AI adoption rates, why pilots stall. A named report beats a news item.\n"
    "  3. NAMED ENTERPRISE DEPLOYMENTS: a large retailer, CPG or distributor "
    "putting agents into a real workflow — ordering, service, supply chain — "
    "with outcomes attached.\n"
    "  4. AGENT VENDORS we compete with or sit beside - Sierra, Decagon, "
    "Intercom Fin, Cresta, Parloa, Forethought, Ada, Observe.AI. Funding, "
    "customer wins, product launches, pricing moves, published outcome "
    "numbers, or a customer saying it did not work. Name the company in "
    "the title.\n"
    "  5. The economics: AI spend, build-vs-buy, what CIOs are cutting.\n\n"

    "WHAT WE DO NOT WANT — these crowd out the above and are not useful "
    "to us:\n"
    "  • Marketplace and platform feature launches (Amazon, TikTok Shop, "
    "Shopify, Walmart adding a shopping assistant, checkout or seller tool). "
    "At most ONE such item, and only if it genuinely changes enterprise "
    "strategy.\n"
    "  • Consumer shopping-app news, Black Friday campaigns, promotions.\n"
    "  • Funding rounds, unless the company sells enterprise AI "
    "infrastructure or is one of the agent vendors named above.\n"
    "  • Model releases with no enterprise retail angle.\n\n"

    "SOURCES to search first (never fabricate to fit; fall back to other "
    "credible outlets):\n"
    "  • McKinsey, BCG, Bain, Gartner, Forrester insights and newsletters\n"
    "  • MIT Sloan Review, HBR — on AI operating models\n"
    "  • The Information, Bloomberg/Reuters enterprise-tech desks\n"
    "  • VentureBeat, TechCrunch Enterprise, The New Stack — data/AI "
    "infrastructure\n"
    "  • Modern Retail, Retail Dive, Grocery Dive — enterprise retail ops\n"
    "  • The Ken, Entrackr, Inc42 (India) · e27, Tech in Asia, "
    "DealStreetAsia (SEA)\n\n"

    "Each item MUST cover a DIFFERENT angle from the others. Aim for at "
    "least 2 from categories 1-2, and at least 1 from category 4 when "
    "anything real has happened there.\n\n"

    "ORDER THE ARRAY BY IMPORTANCE, most important first - the first item "
    "is shown as the lead story. Rank by how much it changes what a seller "
    "says on a call:\n"
    "  - A major vendor making an architecture commitment (e.g. shipping "
    "agents grounded in a knowledge graph) or a named enterprise deployment "
    "with outcomes ranks HIGHEST - that is proof, not opinion.\n"
    "  - Analyst survey findings rank next.\n"
    "  - Market and budget commentary ranks last.\n\n"

    "Return ONLY a JSON object with key 'stories' whose value is an array "
    "of 1-{count} story objects. Each story object has these EXACT keys:\n"
    "  - tag: country/region flag + short topic, e.g. "
    "'US - context layer', 'India - enterprise AI'\n"
    "  - title: the actual headline (verbatim or close paraphrase)\n"
    "  - body: 2-3 sentences using ONLY facts in the source\n"
    "  - why: 2 sentences on why a Graas salesperson should care - tie it "
    "to context layers, retail agents, or why AI pilots stall\n"
    "  - source_label: publication name\n"
    "  - source_url: the ACTUAL article URL - MUST start with http\n\n"

    "HARD RULES:\n"
    "  1. Every claim in body MUST be in the source you cite.\n"
    "  2. If a story has no verifiable URL, OMIT it.\n"
    "  3. If nothing solid surfaces, return an empty stories array.\n\n"

    "Return ONLY the JSON. No prose, no code fences."
)


def fetch_stories(count: int = 3, days: int = 21) -> list:
    """Uncached core. Returns 0..count story dicts.

    Separated from the cached wrapper so a scheduled job can call it
    without Streamlit's cache in the way — the homepage must never trigger
    a web_search on page load, which is why the Newsworthy tab was removed
    on 2026-08-22.
    """
    if not ANTHROPIC_API_KEY:
        return []
    try:
        import anthropic
        import json as _j
        import re as _re
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            # Plain replace, NOT .format(): the prompt contains a literal
            # {"stories": []} example, which str.format reads as a field and
            # dies on — KeyError: '"stories"', swallowed by the except below
            # as "no stories came back".
            messages=[{"role": "user", "content":
                       _PROMPT_TMPL.replace("{count}", str(count))
                                   .replace("{days}", str(days))}],
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 8,
            }],
        )
        text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        raw = "\n".join(text_parts).strip()
        if not raw:
            return []
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if not m:
            return []
        try:
            parsed = _j.loads(m.group(0))
        except Exception:
            return []
        stories_raw = parsed.get("stories", []) if isinstance(parsed, dict) else []
        out = []
        for s in stories_raw[:count]:
            if not isinstance(s, dict):
                continue
            url = (s.get("source_url") or "").strip()
            if not url.startswith("http"):
                continue
            if not s.get("title") or not s.get("body") or not s.get("why"):
                continue
            out.append({
                "tag": s.get("tag", "📰 News"),
                "title": s.get("title"),
                "body": s.get("body"),
                "why": s.get("why"),
                "source_label": s.get("source_label", "Read more"),
                "source_url": url,
            })
        return out
    except Exception as e:
        # Say why. A bare `return []` here is indistinguishable from "the
        # search found nothing", and that cost two CI runs chasing a
        # KeyError the log never showed.
        import sys as _sys
        import traceback as _tb
        print(f"commerce_news: fetch failed — {type(e).__name__}: {e}",
              file=_sys.stderr)
        _tb.print_exc(file=_sys.stderr)
        return []


@st.cache_data(
    ttl=86400,
    show_spinner="🔍 Searching the last 21 days of commerce-tech news…",
)
def fetch_commerce_tech_stories() -> list:
    """Returns a list of 0-3 story dicts. Cached 24h. Prospect Brief uses this."""
    return fetch_stories(count=3, days=21)


def pick_story_for_session(stories: list | None) -> dict | None:
    """Pick one story per Streamlit session — stable within a session,
    randomised across sessions so users see variety across the day."""
    stories = stories or []
    if not stories:
        return None
    if "_news_session_idx" not in st.session_state:
        import random as _r
        st.session_state["_news_session_idx"] = _r.randint(0, 9999)
    idx = st.session_state["_news_session_idx"] % len(stories)
    return stories[idx]
