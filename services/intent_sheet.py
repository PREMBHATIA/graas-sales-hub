"""Rebuild the follow-up sheet without destroying what sales typed into it.

The sheet at INTENT_SHEET_ID is the one salespeople work from. Two kinds of
column live side by side:

  MACHINE  Intent, Do not contact, What they did, Links clicked,
           Last activity, Why reclassified, Level, Title, Segment, Company,
           Who  — all derived, all rewritten on every refresh.

  HUMAN    Owner, Followed up?, Notes — typed by salespeople and NEVER
           written by this module. They are read back by email address and
           carried across, so a refresh can land mid-afternoon without
           anyone losing a morning's work.

That split is the whole point. The sheet went stale within hours the first
time — Martin Lacey sat there flagged "do not contact" after being
un-suppressed — and the obvious fix, regenerating it, would have wiped the
Owner and Notes columns if those were not preserved.
"""

from __future__ import annotations

import os
import re

import pandas as pd

INTENT_SHEET_ID = os.getenv(
    "INTENT_SHEET_ID", "1zGr-Brg_uuHuICDgJJ36ctUnnf7Yluw1Yd0fAy44AaM")

HUMAN_COLS = ["Owner", "Followed up?", "Notes"]

COLUMNS = ["Intent", "Do not contact", "Who", "Level", "Title", "Email",
           "Company", "Segment", "What they did", "Links clicked",
           "Last activity (IST)", "Why reclassified", "Account note",
           "Owner", "Followed up?", "Notes"]

TIER_ORDER = {"1 - Highest intent": 0, "2 - High intent": 1,
              "3 - Not read": 2, "4 - Not reached": 3, "5 - Bounced": 4}


def _abridge(title: str) -> str:
    """Seniority + primary function. Mirrors _abridge_title in the CRM page."""
    s = str(title or "").strip()
    if not s or s.lower() in ("nan", "none", "designation unknown"):
        return ""
    low = s.lower()
    if re.search(r"\b(founder|co-?founder|owner|chairman|proprietor)\b", low):
        lvl = "Founder"
    elif re.search(r"\b(ceo|chief executive|managing director|group ceo|md|"
                   r"president|managing partner)\b", low):
        lvl = "CEO/MD"
    elif re.search(r"\bc[a-z]{1,2}o\b|chief\s+[\w&\s]+officer", low):
        lvl = "C-suite"
    elif re.search(r"\b(vp|vice president|svp|evp)\b", low):
        lvl = "VP"
    elif re.search(r"\b(head|director)\b", low):
        lvl = "Head"
    elif re.search(r"\b(lead|manager|mgr|specialist|executive)\b", low):
        lvl = "Manager"
    else:
        lvl = "Other"
    fns = [("eCom", r"e-?comm?erce|ecom\b|omni-?channel|marketplace|d2c|"
                    r"digital commerce|\bdigital\b"),
           ("Tech", r"\bit\b|\bcio\b|\bcto\b|technolog|technical|\berp\b|"
                    r"transformation|\bdata\b|\bai\b|analytics|information"),
           ("Sales", r"sales|commercial|trade|business development|\bbd\b|revenue"),
           ("Marketing", r"market|brand|growth|\bcmo\b|communication"),
           ("Ops", r"operation|supply|logistic|warehouse|fulfil"),
           ("Finance", r"financ|\bcfo\b|account"),
           ("Customer", r"customer|\bcrm\b|loyalty|service|experience"),
           ("HR", r"\bhr\b|people|talent|human resource")]
    hits = [(m.start(), n) for n, pat in fns for m in [re.search(pat, low)] if m]
    fn = min(hits)[1] if hits else ""
    if lvl in ("Founder", "CEO/MD") and fn in ("", "Sales", "Marketing"):
        return lvl
    return f"{lvl} · {fn}" if fn else lvl


def _name_from_email(em: str) -> str:
    prefix = str(em).split("@")[0]
    parts = [re.sub(r"\d+$", "", p) for p in re.split(r"[._-]", prefix)]
    return " ".join(p.capitalize() for p in parts if p)


def build_rows(campaign_match: str = "gentic") -> pd.DataFrame:
    """The machine columns, freshly derived. No Sheets writing here."""
    from services.email_sender import (recent_sends, fetch_tracking_events,
                                       fetch_suppressions)

    sd = recent_sends(3000)
    tr = fetch_tracking_events()
    if sd is None or tr is None:
        raise RuntimeError("could not read the send log or tracking tab")

    sd = sd.copy()
    sd["tracking_id"] = sd["tracking_id"].astype(str).str.strip()
    sd["_tid"] = sd["tracking_id"]
    sd["_ts"] = pd.to_datetime(sd["timestamp_utc"], errors="coerce", utc=True)
    tr = tr.copy()
    tr["tracking_id"] = tr["tracking_id"].astype(str).str.strip()
    tr["event"] = tr["event"].astype(str).str.strip().str.lower()
    tr["_t"] = pd.to_datetime(tr["ts_utc"], errors="coerce", utc=True)

    camp = sd[sd["subject"].astype(str).str.contains(campaign_match, na=False)
              & (sd["status"] == "sent")].copy()
    camp = camp[~camp["to_email"].astype(str)
                .str.contains("graas.ai|outlook.com", na=False)]
    if camp.empty:
        raise RuntimeError(f"no sends matching {campaign_match!r}")

    import importlib.util
    page = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "views", "3_crm.py")
    src = open(page, encoding="utf-8").read()
    helpers = {"pd": pd, "re": re}
    exec(compile(src[src.index("_OPEN_PREFETCH_SEC = 60"):
                     src.index("tab_contacts,")], "crm_helpers", "exec"), helpers)

    reads = pd.Series(helpers["_human_open_counts"](tr, camp), dtype="int64")
    clicks = helpers["_human_click_rows"](tr, camp)
    human = (clicks[~clicks["_machine"].astype(bool)]
             if clicks is not None and not clicks.empty else pd.DataFrame())
    n_clicks = human.groupby("to_email")["_times"].sum().to_dict() if len(human) else {}
    urls = (human.groupby("to_email")["dest_url"]
            .apply(lambda s: " | ".join(sorted({str(x) for x in s}))).to_dict()
            if len(human) else {})
    video = (set(human[human["dest_url"].astype(str)
                 .str.contains("youtu", case=False, na=False)]["to_email"])
             if len(human) else set())
    beacons = set(tr["tracking_id"])
    last = {t: g["_t"].max() for t, g in tr.groupby("tracking_id")}

    # machine-only clickers get a note explaining why they are not "clicked"
    raw = tr[tr["event"] == "click"].merge(
        camp[["tracking_id", "to_email", "_ts"]], on="tracking_id", how="inner")
    raw["_d"] = (raw["_t"] - raw["_ts"]).dt.total_seconds()
    human_set = set(human["to_email"]) if len(human) else set()
    why = {}
    for em, g in raw.groupby("to_email"):
        if em in human_set:
            continue
        g = g.sort_values("_t")
        delay = int(g["_d"].min())
        span = int((g["_t"].max() - g["_t"].min()).total_seconds())
        reason = (f"fired {delay}s after send" if delay <= 60
                  else f"{g['dest_url'].nunique()} links in {span}s")
        why[str(em).lower()] = (
            f"Machine-scanned click ({reason}) — their mail-security software "
            "opened the links, not a person. Not counted as a click.")

    sup = fetch_suppressions()
    sup_reason = {}
    if sup is not None and not sup.empty:
        sup["email"] = sup["email"].astype(str).str.strip().str.lower()
        sup_reason = dict(zip(sup["email"], sup["reason"].astype(str)))

    # titles come from the pipeline sheet's "(Designation)"
    titles, segs = {}, {}
    try:
        crm = {"__name__": "crm", "__file__": page}
        exec(compile(src[:src.index("contacts = load_crm_data(")],
                     "crm_load", "exec"), crm)
        c = crm["load_crm_data"]()
        c = c[c["email"].astype(str).str.contains("@", na=False)]
        key = c["email"].astype(str).str.lower()
        titles = dict(zip(key, c["designation"].astype(str)))
        segs = dict(zip(key, c["ai_segment"].astype(str)))
    except Exception:
        pass

    def clean_title(t):
        t = str(t or "").strip()
        return "" if t.lower() in ("nan", "none", "designation unknown") else t

    rows = {}
    for _, r in camp.iterrows():
        em = r["to_email"]
        eml = str(em).strip().lower()
        n = int(reads.get(r["_tid"], 0))
        ck = int(n_clicks.get(em, 0))
        supp = sup_reason.get(eml, "")
        bounced = "bounce" in supp.lower()

        if bounced:
            tier, rank = "5 - Bounced", -1
            did = "ADDRESS DOESN'T EXIST — do not send"
        elif ck or n >= 2:
            tier, rank = "1 - Highest intent", 3
            bits = []
            if n >= 2:
                bits.append(f"opened {n}x")
            elif n == 1:
                bits.append("opened")
            if ck:
                bits.append(f"clicked {ck}x" if ck > 1 else "clicked")
            if em in video:
                bits.append("WATCHED VIDEO")
            did = " / ".join(bits)
        elif n == 1:
            tier, rank, did = "2 - High intent", 2, "opened once"
        elif r["_tid"] in beacons:
            tier, rank, did = "3 - Not read", 1, "delivered, never opened"
        else:
            tier, rank, did = "4 - Not reached", 0, "no delivery evidence"

        dnc = ""
        if supp:
            dnc = ("⛔ UNSUBSCRIBED — do not contact"
                   if "unsubscribe" in supp.lower()
                   else "⛔ SUPPRESSED — " + supp[:60])

        lt = last.get(r["_tid"])
        when = ((lt + pd.Timedelta(hours=5, minutes=30)).strftime("%d %b %H:%M")
                if lt is not None and rank > 0 else "")
        title = clean_title(titles.get(eml, ""))

        prev = rows.get(em)
        if prev is None or rank > prev["_rank"]:
            rows[em] = {
                "Intent": tier, "Do not contact": dnc,
                "Who": str(r.get("to_name") or "").strip() or _name_from_email(em),
                "Level": _abridge(title), "Title": title, "Email": em,
                "Company": r.get("company", ""),
                "Segment": str(segs.get(eml, "")).replace("AI ", ""),
                "What they did": did, "Links clicked": urls.get(em, ""),
                "Last activity (IST)": when,
                "Why reclassified": why.get(eml, ""),
                "Account note": "", "_rank": rank}

    df = pd.DataFrame(list(rows.values()))
    bad = df["Intent"] == "5 - Bounced"
    bad_cos = set(df.loc[bad, "Company"].astype(str))
    df.loc[bad, "Account note"] = ("Address doesn't exist — could be a typo in "
                                   "our list or the person has gone. Verify "
                                   "before replacing.")
    df.loc[df["Company"].astype(str).isin(bad_cos) & ~bad, "Account note"] = (
        "A colleague's address at this account bounced — contact data here may "
        "be out of date.")
    df["_o"] = df["Intent"].map(TIER_ORDER).fillna(9)
    return (df.sort_values(["_o", "Company"])
              .drop(columns=["_o", "_rank"]).reset_index(drop=True))


def refresh(dry_run: bool = False) -> dict:
    """Rewrite the machine columns, carry the human ones across.

    Returns a summary dict. Raises rather than writing a partial sheet.
    """
    from services.sheets_client import _get_writer_client

    fresh = build_rows()

    client = _get_writer_client()
    if client is None:
        raise RuntimeError("no Sheets credentials")
    ws = client.open_by_key(INTENT_SHEET_ID).sheet1
    existing = ws.get_all_values()

    kept = 0
    if existing and len(existing) > 1:
        old = pd.DataFrame(existing[1:], columns=existing[0])
        if "Email" in old.columns:
            old_key = old["Email"].astype(str).str.strip().str.lower()
            for col in HUMAN_COLS:
                if col not in old.columns:
                    continue
                carry = dict(zip(old_key, old[col].astype(str)))
                vals = (fresh["Email"].astype(str).str.strip().str.lower()
                        .map(carry).fillna(""))
                # Drop anything this module wrote into a human column before
                # "Why reclassified" existed — the machine-scan explanation
                # used to live in Notes, and carrying it forward would both
                # duplicate the new column and masquerade as sales input.
                vals = vals.mask(vals.str.startswith("Machine-scanned click"), "")
                kept += int((vals.str.strip() != "").sum())
                fresh[col] = vals
    for col in HUMAN_COLS:
        if col not in fresh.columns:
            fresh[col] = ""

    cols = [c for c in COLUMNS if c in fresh.columns]
    fresh = fresh[cols]
    summary = {
        "rows": len(fresh),
        "human_cells_preserved": kept,
        "tiers": fresh["Intent"].value_counts().to_dict(),
        "do_not_contact": int((fresh["Do not contact"].str.strip() != "").sum()),
    }
    if dry_run:
        return summary

    ws.clear()
    ws.update([cols] + fresh.astype(str).values.tolist(),
              value_input_option="RAW")
    last_col = chr(ord("A") + len(cols) - 1)
    ws.freeze(rows=1)
    ws.format(f"A1:{last_col}1",
              {"textFormat": {"bold": True,
                              "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
               "backgroundColor": {"red": 0.12, "green": 0.12, "blue": 0.14}})
    n1 = int((fresh["Intent"] == "1 - Highest intent").sum())
    n2 = int((fresh["Intent"] == "2 - High intent").sum())
    nb = int((fresh["Intent"] == "5 - Bounced").sum())
    if n1:
        ws.format(f"A2:{last_col}{1 + n1}",
                  {"backgroundColor": {"red": 1.0, "green": 0.90, "blue": 0.76}})
    if n2:
        ws.format(f"A{2 + n1}:{last_col}{1 + n1 + n2}",
                  {"backgroundColor": {"red": 1.0, "green": 0.97, "blue": 0.86}})
    if nb:
        ws.format(f"A{len(fresh) + 2 - nb}:{last_col}{len(fresh) + 1}",
                  {"backgroundColor": {"red": 0.98, "green": 0.84, "blue": 0.84}})
    ws.set_basic_filter(f"A1:{last_col}{len(fresh) + 1}")
    return summary
