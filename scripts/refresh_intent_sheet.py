#!/usr/bin/env python3
"""Daily refresh of the follow-up sheet, with a report of what moved.

The sheet goes stale the moment engagement changes or a suppression is
added — Martin Lacey sat flagged "do not contact" for two days after being
un-suppressed, and clicks kept arriving for a week after the send while the
tiers stayed frozen at whatever they were when it was last exported.

Sales type into Owner, Followed up? and Notes. services.intent_sheet.refresh
carries those across by email address, so this can run unattended without
anyone losing a morning's work.

Prints a before/after so the run says what actually changed rather than
just "done".

Usage:  python3 scripts/refresh_intent_sheet.py [--dry-run]
Exit:   0 on success, 1 if the sheet could not be read or written.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAMP = ROOT / "content" / "intent_refresh.json"
TIERS = ["1 - Highest intent", "2 - High intent", "3 - Not read",
         "4 - Not reached", "5 - Bounced"]


def _current_tiers() -> dict:
    """Tier counts as the sheet stands, before we touch it."""
    try:
        import pandas as pd
        from services.sheets_client import _get_writer_client
        from services.intent_sheet import INTENT_SHEET_ID
        client = _get_writer_client()
        if client is None:
            return {}
        vals = client.open_by_key(INTENT_SHEET_ID).sheet1.get_all_values()
        if not vals or len(vals) < 2:
            return {}
        df = pd.DataFrame(vals[1:], columns=vals[0])
        if "Intent" not in df.columns:
            return {}
        return df["Intent"].value_counts().to_dict()
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    # local runs read .env; CI sets the environment itself
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    before = _current_tiers()

    try:
        from services.intent_sheet import refresh
        summary = refresh(dry_run=args.dry_run)
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        return 1

    after = summary["tiers"]
    print("Follow-up sheet " + ("(dry run — nothing written)" if args.dry_run
                                else "refreshed"))
    print(f"  rows: {summary['rows']}")
    print(f"  sales edits preserved: {summary['human_cells_preserved']}")
    print(f"  do-not-contact: {summary['do_not_contact']}\n")
    moved = False
    for t in TIERS:
        b, a = int(before.get(t, 0)), int(after.get(t, 0))
        if b != a:
            moved = True
            print(f"  {t:20} {b:4} -> {a:<4}  ({a - b:+d})")
        else:
            print(f"  {t:20} {a:4}")
    if not moved and before:
        print("\n  nothing moved since the last refresh")

    # Stamp the run so the app can say how fresh the sheet is. Without this
    # a salesperson has no way to tell a sheet refreshed an hour ago from one
    # last written a week back, and the whole point of the daily job is that
    # they can trust the tiers.
    if not args.dry_run:
        try:
            STAMP.parent.mkdir(parents=True, exist_ok=True)
            STAMP.write_text(json.dumps({
                "refreshed_utc": datetime.now(timezone.utc)
                                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
                "rows": summary["rows"],
                "tiers": {t: int(after.get(t, 0)) for t in TIERS},
                "moved": {t: int(after.get(t, 0)) - int(before.get(t, 0))
                          for t in TIERS
                          if int(after.get(t, 0)) != int(before.get(t, 0))},
                "do_not_contact": summary["do_not_contact"],
                "sales_edits": summary["human_cells_preserved"],
            }, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"  (could not write the freshness stamp: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
