#!/usr/bin/env python3
"""Refresh content/news.json — the homepage's "News you can Use" cache.

Run on a schedule, never from the app. The Newsworthy tab was removed on
2026-08-22 because its Claude + web_search fetch ran on EVERY page load and
could block the page for minutes on a cache miss; this script exists so the
homepage only ever reads a small JSON file off disk.

Writes atomically (temp file + replace) so a half-written file can never be
served, and leaves the existing file untouched if the fetch returns nothing —
five stale stories beat an empty section.

Usage:  ANTHROPIC_API_KEY=... python3 scripts/refresh_news.py [--count 5] [--days 30]
Exit:   0 on success or a deliberate no-op, 1 only if the file could not be written.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "content" / "news.json"


def _drop_dead_links(stories: list) -> list:
    """Keep only stories whose source_url actually resolves.

    A 403 or a timeout is kept: big publishers (BCG, McKinsey, Gartner)
    block scrapers, and dropping them would leave only the outlets that
    happen to allow bots. A 404 or 410 is dropped, and so is a 200 whose
    body is a soft "page not found" — status alone is not proof a page
    exists.
    """
    import urllib.error
    import urllib.request

    ua = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120 Safari/537.36"}
    kept = []
    for s in stories:
        url = (s.get("source_url") or "").strip()
        try:
            r = urllib.request.urlopen(
                urllib.request.Request(url, headers=ua), timeout=20)
            body = r.read(80000).decode("utf-8", "replace").lower()
            soft = any(m in body[:6000] for m in
                       ("page not found", "404 error", "page doesn't exist",
                        "page does not exist", "we couldn't find that page"))
            if soft:
                print(f"  DROPPED (soft 404): {str(s.get('title'))[:58]}")
                continue
            kept.append(s)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                print(f"  DROPPED ({e.code}): {str(s.get('title'))[:58]}")
                continue
            kept.append(s)          # 403/429 = bot-blocked, not missing
        except Exception:
            kept.append(s)          # timeout/slow host — assume alive
    return kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — leaving the existing file alone.")
        return 0

    try:
        from services.commerce_news import fetch_stories
        stories = fetch_stories(count=args.count, days=args.days)
    except Exception as e:
        print(f"Fetch failed ({type(e).__name__}: {e}) — existing file kept.")
        return 0

    if not stories:
        print("No stories came back — existing file kept.")
        return 0

    # Verify every link before writing. A story whose URL 404s is worse than
    # no story: it reads as fabricated. The model is told not to cite an
    # unverifiable source, but "told not to" is not a check — an Atlan link
    # it returned on 25 Oct went straight to a 404 and shipped to the
    # homepage because the only verification happened by hand, on a
    # different run's output.
    stories = _drop_dead_links(stories)
    if not stories:
        print("Every story failed link verification — existing file kept.")
        return 0

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": args.days,
        "stories": stories,
    }
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=OUT.parent,
                                         delete=False) as tmp:
            json.dump(payload, tmp, indent=2, ensure_ascii=False)
            tmp_path = Path(tmp.name)
        tmp_path.replace(OUT)
    except Exception as e:
        print(f"Could not write {OUT}: {type(e).__name__}: {e}")
        return 1

    print(f"Wrote {len(stories)} stories to {OUT}")
    for s in stories:
        print(f"  · {s.get('tag','')} — {str(s.get('title',''))[:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
