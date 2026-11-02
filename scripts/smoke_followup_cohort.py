#!/usr/bin/env python3
"""Execute the composer's follow-up-cohort branch against live data.

The four existing gates all reach the composer in "Everyone" mode, because
the stubbed st.radio returns its first option — so the cohort branch added on
2 Nov shipped untested by them. It is the riskiest kind of code in this file:
it reshapes _pool, maps across two different sheets, and builds labels in a
comprehension over .iterrows(), which is exactly where October's dtype and
empty-frame failures lived.

Rather than re-stub the whole page, this lifts the branch's real source text
out of views/3_crm.py and runs it against the real follow-up sheet and the
real contact book. If someone edits that block and breaks it, this fails.

Usage:  python3 scripts/smoke_followup_cohort.py
Exit:   0 on success, 1 if the block fails or the shapes are wrong.
"""

import os
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class _Stop(Exception):
    pass


class _Col:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _St:
    """Only the calls the extracted blocks make."""

    def error(self, *a, **k):
        self.last_error = a[0] if a else ""

    def warning(self, *a, **k):
        self.last_warning = a[0] if a else ""

    def caption(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [_Col() for _ in range(n)]

    def multiselect(self, label, options, **k):
        return k.get("default", options)

    def stop(self):
        raise _Stop()


def main() -> int:
    sys.path.insert(0, str(ROOT))
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    src = (ROOT / "views" / "3_crm.py").read_text(encoding="utf-8")

    # Lift the label-building branch: from "if _use_cohort:" (the second one,
    # which builds the options) up to the "else:" that handles Everyone.
    m = re.search(r"\n        if _use_cohort:\n(.*?)\n        else:\n"
                  r"            _pool\['_label'\]", src, re.S)
    if not m:
        print("FAIL — could not find the cohort branch in views/3_crm.py. "
              "If it was deliberately renamed or removed, update this gate.")
        return 1
    block = textwrap.dedent(m.group(1))

    # Real data on both sides — the whole point is that these two sheets agree.
    import pandas as pd
    from services.intent_sheet import follow_up_cohort

    coh = follow_up_cohort()
    if coh.empty:
        print("FAIL — the follow-up cohort came back empty; nothing to test "
              "against. Refresh the follow-up sheet and retry.")
        return 1

    # load_crm_data lives in the page module, so read the contact sheets the
    # way it does rather than importing a module whose name starts with a digit.
    from services.sheets_client import fetch_log_rows
    rows = fetch_log_rows(os.getenv("EMAIL_LOG_SHEET_ID", ""), "Sends")
    if rows is None:
        print("FAIL — could not read the outreach log.")
        return 1

    # A _pool shaped exactly like the composer's: one row per contact with an
    # address, drawn from the cohort itself so every row is a genuine match.
    pool = pd.DataFrame({
        "email": coh["Email"],
        "company": coh["Company"] if "Company" in coh.columns else "",
        "person_name": coh["Who"] if "Who" in coh.columns else coh["Email"],
    })

    ns = {"st": _St(), "pd": pd, "_coh_df": coh, "_pool": pool,
          "_use_cohort": True, "set": set, "zip": zip, "sum": sum,
          "enumerate": enumerate, "dict": dict, "str": str, "i": 0}
    try:
        exec(compile(block, "3_crm.py:cohort-branch", "exec"), ns)
    except _Stop:
        print("FAIL — the block called st.stop() on live data: "
              f"{getattr(ns['st'], 'last_warning', '')}")
        return 1
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"FAIL — the cohort branch raised {type(e).__name__}: {e}")
        return 1

    opts = ns.get("_opts")
    if not opts:
        print("FAIL — the branch produced no options from a non-empty cohort.")
        return 1
    if len(set(opts)) != len(opts):
        # A duplicate label makes the _pool[_label == pick] lookup return two
        # rows, and the composer would then send to the wrong person.
        print(f"FAIL — {len(opts) - len(set(opts))} duplicate label(s); the "
              "contact lookup would be ambiguous.")
        return 1

    pool2 = ns["_pool"]
    hit = pool2[pool2["_label"] == opts[0]]
    if len(hit) != 1:
        print(f"FAIL — selecting the first option matched {len(hit)} rows.")
        return 1

    n_done = ns.get("_n_done", 0)
    tiers = sorted({o.split(" · ")[0] for o in opts})

    # ── Laggards must never be in the cohort at all ──────────────────────────
    # Not a default, not a filter — an exclusion (Prem, 2 Nov). Enforced in
    # follow_up_cohort() so the 1:1 picker and the bulk audience both inherit
    # it; checked here because a filter nobody tests is a filter that comes
    # back on.
    if "Segment" in coh.columns:
        _lag = int((coh["Segment"].astype(str).str.strip().str.lower()
                    == "laggard").sum())
        if _lag:
            print(f"FAIL — {_lag} Laggard contact(s) in the follow-up cohort. "
                  "They must never receive a follow-up.")
            return 1

    # ── The bulk audience branch ─────────────────────────────────────────────
    # Higher stakes than the picker above: this one selects everybody a single
    # run sends to. The stubbed multiselect returns each widget's default, so
    # this asserts what the composer does when you touch nothing.
    mb = re.search(r"\n        if _bulk_cohort:\n(.*?)\n        else:\n"
                   r"            _sc1, _sc2 = st\.columns", src, re.S)
    if not mb:
        print("FAIL — could not find the bulk cohort branch in views/3_crm.py.")
        return 1
    bblock = textwrap.dedent(mb.group(1))

    labels = re.search(r"\nFOLLOW_UP_TIER_LABELS = \{(.*?)\n\}", src, re.S)
    if not labels:
        print("FAIL — could not find FOLLOW_UP_TIER_LABELS.")
        return 1
    lns = {}
    exec(compile("FOLLOW_UP_TIER_LABELS = {" + labels.group(1) + "\n}",
                 "3_crm.py:labels", "exec"), lns)
    tier_labels = lns["FOLLOW_UP_TIER_LABELS"]

    bns = {"st": _St(), "pd": pd, "_pool": pool, "_bulk_cohort": True,
           "_follow_up_cohort_page": lambda: (coh, ""),
           "FOLLOW_UP_TIER_LABELS": tier_labels,
           "FOLLOW_UP_TIERS_UI": list(tier_labels.keys()),
           "set": set, "zip": zip, "sum": sum, "sorted": sorted,
           "dict": dict, "str": str, "len": len, "enumerate": enumerate}
    try:
        exec(compile(bblock, "3_crm.py:bulk-cohort", "exec"), bns)
    except _Stop:
        print("FAIL — the bulk branch called st.stop() on live data.")
        return 1
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"FAIL — the bulk branch raised {type(e).__name__}: {e}")
        return 1

    rcp = bns.get("recipients")
    if rcp is None or rcp.empty:
        print("FAIL — the bulk branch selected nobody on its defaults.")
        return 1
    # THE invariant: touching nothing must never produce the whole cohort.
    if len(rcp) > 60:
        print(f"FAIL — the bulk defaults select {len(rcp)} recipients. The "
              "defaults must be one tier and one segment, so a large send is "
              "always deliberate.")
        return 1
    if str(bns.get("comp_ai_seg", "")) != "Follow-up cohort":
        print("FAIL — comp_ai_seg must label this round for the send log; "
              f"got {bns.get('comp_ai_seg')!r}.")
        return 1

    print(f"COHORT SMOKE OK — 1:1 picker: {len(opts)} options, labels unique, "
          f"{n_done} chased, tiers {tiers}. Bulk defaults: {len(rcp)} "
          f"recipients, no Laggards in a cohort of {len(coh)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
