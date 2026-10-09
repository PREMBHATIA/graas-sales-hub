"""One-time backfill: stamp `brief_market` into each Prospect Brief's Drive
appProperties, read from the brief's own content.

Why: the Recent-briefs tiles label each brief with its country. New briefs get
`brief_market` stamped at save time (from header.market), but the ~44 briefs
saved before that existed have nothing — and the market lives inside the Doc
(the rendered "Market <X>" header line; failing that, the revenue currency,
e.g. THB → Thailand). This reads each Doc once and stamps the value so the
tiles can read it cheaply forever (no per-page-load Doc reads).

Idempotent: skips any brief that already has a non-empty brief_market unless
run with --force. Run from the repo root:

    python3 scripts/backfill_brief_markets.py            # stamp missing only
    python3 scripts/backfill_brief_markets.py --force    # re-stamp all
    python3 scripts/backfill_brief_markets.py --dry      # show, don't write
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(dotenv_path=str(Path(__file__).resolve().parent.parent / ".env"))

from services.sheets_client import (  # noqa: E402
    list_drive_folder_docs, fetch_drive_doc_text, set_drive_app_properties,
)

# Same folder the brief page + Recent-briefs tiles use.
BRIEFS_FOLDER = os.getenv("PROSPECT_BRIEF_DRIVE_FOLDER", "12GtdM6jKWu2QXT8D_6WoGq4wvmkcce7Q")

_CANON = {
    "india": "India", "indonesia": "Indonesia", "vietnam": "Vietnam",
    "thailand": "Thailand", "philippines": "Philippines", "malaysia": "Malaysia",
    "singapore": "Singapore", "uae": "UAE", "united arab emirates": "UAE",
    "dubai": "UAE", "abu dhabi": "UAE", "uk": "UK", "united kingdom": "UK",
    "australia": "Australia", "saudi": "Saudi", "ksa": "Saudi", "sea": "SEA",
    "usa": "USA", "united states": "USA",
}

# Currency / strong tokens → market, used only when the "Market" field is absent.
_CURRENCY = [
    ("Thailand", [r"\bTHB\b", r"฿", r"\bbaht\b"]),
    ("Indonesia", [r"\bIDR\b", r"\bRp\b", r"\brupiah\b", r"\bTbk\b"]),
    ("Vietnam", [r"\bVND\b", r"₫", r"\bdong\b"]),
    ("Philippines", [r"\bPHP\b", r"₱", r"\bpeso\b"]),
    ("Malaysia", [r"\bMYR\b", r"\bringgit\b", r"\bRM\s?\d"]),
    ("Singapore", [r"\bSGD\b", r"S\$"]),
    ("UAE", [r"\bAED\b", r"\bDhs?\b"]),
    ("UK", [r"\bGBP\b", r"£"]),
    ("Australia", [r"\bAUD\b", r"A\$"]),
    ("Saudi", [r"\bSAR\b"]),
    ("India", [r"\bINR\b", r"₹", r"\blakh\b", r"\bcrore\b", r"\brupee"]),
]


def extract_market(text: str) -> tuple:
    """(market, source). Prefer the explicit 'Market <X>' header field; else
    infer from the revenue currency. '' if nothing confident."""
    # 1. Explicit header field — "… · Market Thailand · …". Only trust it if the
    #    captured value is a known country (so 'market share' etc. don't match).
    for m in re.finditer(r"\bMarket\s+([A-Za-z][A-Za-z /&.'-]{1,28})", text):
        low = m.group(1).strip().lower()
        for key, canon in _CANON.items():
            if low.startswith(key):
                return canon, "field"
    # 2. Currency / strong-token scoring.
    scores = {}
    for country, pats in _CURRENCY:
        c = sum(len(re.findall(p, text, re.IGNORECASE)) for p in pats)
        if c:
            scores[country] = c
    if scores:
        best = max(scores, key=scores.get)
        return best, f"currency({scores[best]})"
    return "", "none"


def main():
    force = "--force" in sys.argv
    dry = "--dry" in sys.argv
    docs = list_drive_folder_docs(BRIEFS_FOLDER) or []
    briefs = [d for d in docs if d["name"].lower().startswith("prospect brief")]
    print(f"Found {len(briefs)} briefs in folder {BRIEFS_FOLDER}\n")

    stamped = skipped = failed = blank = 0
    for d in briefs:
        name = d["name"]
        existing = (d.get("app_properties", {}) or {}).get("brief_market", "")
        if existing and not force:
            skipped += 1
            print(f"  ✓ skip (has '{existing}')  {name}")
            continue
        try:
            text = fetch_drive_doc_text(d["id"]) or ""
        except Exception as e:
            failed += 1
            print(f"  ✗ read failed ({type(e).__name__})  {name}")
            continue
        market, source = extract_market(text)
        if not market:
            blank += 1
            print(f"  … no market found  {name}")
            continue
        if dry:
            print(f"  ⟶ would stamp '{market}' [{source}]  {name}")
            continue
        r = set_drive_app_properties(d["id"], {"brief_market": market})
        if r.get("ok"):
            stamped += 1
            print(f"  ⟶ stamped '{market}' [{source}]  {name}")
        else:
            failed += 1
            print(f"  ✗ stamp failed ({r.get('error', '?')[:60]})  {name}")

    print(f"\nDone. stamped={stamped} skipped={skipped} no-market={blank} failed={failed}"
          + ("  (DRY RUN — nothing written)" if dry else ""))


if __name__ == "__main__":
    main()
