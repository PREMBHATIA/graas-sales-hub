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


_PROMPT = (
    "Use web_search to find UP TO 3 distinct, HIGH-IMPACT commerce-tech "
    "news stories from the LAST 21 DAYS. These will be used as email "
    "talking points to commerce executives — they MUST be substantive "
    "enough to anchor a sales outreach (not blog posts, not minor "
    "feature launches).\n\n"
    "PRIORITY TOPIC = AGENTIC AI in retail/commerce (autonomous shopping "
    "agents, agentic checkout, AI sales reps, agentic search/discovery, "
    "retailer rollouts of agent platforms — e.g. IKEA's agentic AI "
    "journey, Walmart Sparky, Amazon Rufus, Shopify Sidekick). "
    "Secondary topics: major M&A or funding ($50M+), platform-level "
    "announcements from Shopify/Amazon/TikTok Shop, Anthropic/OpenAI "
    "retail moves, quick commerce shifts in India/SEA at scale.\n\n"
    "WHAT 'HIGH IMPACT' MEANS — pick stories that:\n"
    "  • A CMO or Head of Digital at a $100M+ brand would care about\n"
    "  • Make a credible 'have you seen this?' email opener\n"
    "  • Aren't already old news (skip anything that broke before 21 days ago)\n\n"
    "PREFERRED SOURCES (search these first; aim for ≥1 from this list — "
    "but never fabricate to fit, fall back to other credible outlets "
    "if these don't have a fit):\n"
    "  • McKinsey, Bain, BCG newsletters / insights — esp. retail + "
    "agentic AI pieces\n"
    "  • Watson Weekly (watsonweekly.com)\n"
    "  • GeekWire (geekwire.com)\n"
    "  • TechCrunch (techcrunch.com)\n"
    "  • Daman Soni's Substack (damansoni.substack.com) — India D2C\n"
    "  • e27 (e27.co), Tech in Asia, DealStreetAsia — SEA\n"
    "  • The Ken, Entrackr, Inc42 — India ecom\n"
    "  • Modern Retail, Retail Dive, Bloomberg/Reuters retail desk\n\n"
    "Each story MUST cover a DIFFERENT angle/topic from the others.\n\n"
    "Return ONLY a JSON object with key 'stories' whose value is an "
    "array of 1-3 story objects. Each story object has these EXACT keys:\n"
    "  • tag: country flag + short topic, e.g. '🇺🇸 US · agentic "
    "commerce', '🇮🇳 India · quick commerce'\n"
    "  • title: the actual headline (verbatim or close paraphrase)\n"
    "  • body: 2-3 sentences using ONLY facts in the source\n"
    "  • why: 2 sentences on why this matters for a Graas salesperson — "
    "tie it to commerce-AI, retail agents, or vertical AI dynamics\n"
    "  • source_label: publication name\n"
    "  • source_url: the ACTUAL article URL — MUST start with http\n\n"
    "HARD RULES:\n"
    "  1. Every claim in body MUST be in the source you cite.\n"
    "  2. If a story has no verifiable URL, OMIT it.\n"
    "  3. If nothing solid surfaces, return {\"stories\": []}.\n\n"
    "Return ONLY the JSON. No prose, no code fences."
)


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_commerce_tech_stories() -> list:
    """Returns a list of 0-3 story dicts. Cached 24h."""
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
            messages=[{"role": "user", "content": _PROMPT}],
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
        for s in stories_raw[:3]:
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
    except Exception:
        return []


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
