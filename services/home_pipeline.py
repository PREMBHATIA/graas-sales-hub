"""Headline All-e pipeline for the SalesHub homepage.

Numbers come from two sheets that are both live:
  • the revenue sheet "Proposals" tab → proposals out, their value (First Year GP),
    won / lost / in discussion, and the list of won deals;
  • the presales tracker "Overall Pipeline" (+ the old "Dropped leads") tab → net-new
    leads this year, and the region and owner of each won deal.

All-e ONLY: the revenue sheet also carries MP Enablement, Extract, Hoppr and others,
which are filtered out on Product.

Amounts are REVENUE: the sheet's "First Year GP" column holds proposal revenue
(Prem, 4 Nov: "the pre-sales and revenue trackers are the proposal amounts, which is
revenue"; e.g. Propan's $78K is its quoted ACV). They are shown as they are, with no
GP conversion.

Two hard-coded overrides (Prem), because the sheets lag the deals:
  • LK is WON (signed by email; the sheet still says "In Discussion").
  • PI is WON but is on neither sheet, so it is added here: Jan 2026, ACV $35K,
    owner Prem, at its $35K ACV.
Delete these the day the sheets are updated.

Kept in its own module, imported lazily by the homepage, so a failure here can
never break the landing page.
"""

import os
import re
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

# ── Overrides ────────────────────────────────────────────────────────────────
STATUS_OVERRIDES = {"lk": "Won"}   # client-name prefix (lower case) → status
# PI: WhatsApp distributor ordering, won Jan 2026, ACV $35K (Prem, 4 Nov).
EXTRA_WON = [{"name": "PI", "rev": 35_000, "region": "India", "owner": "Prem", "month": 1}]
# Short names, as the team says them. Also keeps the tracker lookup (by first word of
# the name) off "PT", which matches half the leads.
DISPLAY_NAME = {"castrol voice agent pilot": "Castrol Voice", "lk all-e": "LK",
                "sinarmas sdn id": "Sinarmas", "pt propan raya": "Propan",
                "pt wings group": "Wings", "sunway my": "Sunway"}
# Region / owner the tracker lacks or gets wrong, by lower-case display name (Prem, 4 Nov).
DEAL_FIXES = {
    "sinarmas": {"region": "Indonesia", "owner": "Ashwin"},
    "hindware": {"region": "India", "owner": "Amruta"},
}

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _cfg(name: str) -> str:
    v = os.getenv(name, "")
    if not v:
        try:
            if hasattr(st, "secrets") and name in st.secrets:
                v = st.secrets[name]
        except Exception:
            v = ""
    return str(v or "")


def _date(s):
    """'21 April 2026' / '10 Sept 2026' -> datetime. A year past 2026 is a typo
    (the tracker has '8 July 2028') and is read as 2026."""
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", str(s or ""))
    if not m or m.group(2)[:3].lower() not in _MONTHS:
        return None
    try:
        return datetime(min(int(m.group(3)), 2026), _MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    except ValueError:
        return None


def _month(s):
    """'May'26' / 'March '26' -> 5. None if unreadable."""
    return _MONTHS.get(re.sub(r"[^a-z]", "", str(s or "").lower())[:3])


def _bucket(month) -> str:
    """Same cut as the Cross-Product Pipeline page: a proposal is '<60' if its
    sent month's 15th is within 60 days of today, else '>60'."""
    if month is None or pd.isna(month):
        return ">60"
    return "<60" if datetime(2026, int(month), 15) >= datetime.now() - timedelta(days=60) else ">60"


def _amount(v):
    s = re.sub(r"[^0-9.]", "", str(v or ""))
    return float(s) if s else None


def _norm(n) -> str:
    return re.sub(r"\s+", " ", str(n or "").strip().lower())


def _tracker():
    from services.sheets_client import fetch_sheet_tab
    sid = _cfg("ALLE_SHEET_ID")
    a = fetch_sheet_tab(sid, "Overall Pipeline for IN and SEA")
    b = fetch_sheet_tab(sid, "Dropped leads")
    for df in (a, b):
        df.columns = [str(c).strip() for c in df.columns]
    a = a[a["Lead name"].astype(str).str.strip().ne("")].copy()
    b = b[b["Lead name"].astype(str).str.strip().ne("")].copy()
    a["_k"], b["_k"] = a["Lead name"].map(_norm), b["Lead name"].map(_norm)
    a, b = a.drop_duplicates("_k"), b.drop_duplicates("_k")
    return a, b[~b["_k"].isin(set(a["_k"]))]


@st.cache_data(ttl=900, show_spinner=False)
def load_headline() -> dict:
    """The homepage numbers. Raises if a sheet can't be read (the caller catches)."""
    from services.sheets_client import fetch_sheet_tab

    # Proposals — All-e rows only
    rev = fetch_sheet_tab(_cfg("REVENUE_SHEET_ID"), "Proposals")
    rev.columns = [str(c).strip() for c in rev.columns]
    rev = rev[rev["Client Name"].astype(str).str.strip().ne("")].copy()
    rev = rev[rev["Product"].astype(str).str.contains(r"\ball[\s\-]?e\b", case=False, regex=True, na=False)]

    tracker_a, tracker_b = _tracker()
    tracker = pd.concat([tracker_a, tracker_b], ignore_index=True, sort=False)
    has_owner = "Owner" in tracker.columns

    def _lookup(display: str):
        """(region, owner) for a client from the tracker, by first word of its name."""
        key = _norm(display).split(" ")[0]
        m = tracker[tracker["Lead name"].astype(str).str.lower().str.contains(re.escape(key), na=False)]
        m = m[~m["Lead name"].astype(str).str.lower().str.contains("large")]
        if m.empty:
            return "", ""
        clean = lambda v: "" if str(v).strip().lower() in ("nan", "none") else str(v).strip()
        return clean(m["Region"].iloc[0]), clean(m["Owner"].iloc[0]) if has_owner else ""

    rows = []
    for _, r in rev.iterrows():
        raw = str(r["Client Name"]).strip()
        low = _norm(raw)
        status = str(r["Status"]).strip().lower()
        status = "Won" if status.startswith("won") else "Lost" if status.startswith("lost") else "In discussion"
        for prefix, forced in STATUS_OVERRIDES.items():
            if low.startswith(prefix):
                status = forced
        rows.append({"name": DISPLAY_NAME.get(low, raw), "status": status,
                     "rev": _amount(r.get("First Year GP")),   # labelled GP on the sheet; it is revenue
                     "pic": str(r.get("PIC", "")).strip(), "month": _month(r.get("Date sent"))})
    for x in EXTRA_WON:
        rows.append({"name": x["name"], "status": "Won", "rev": x["rev"], "pic": "",
                     "month": x["month"], "_region": x["region"], "_owner": x["owner"]})
    df = pd.DataFrame(rows)

    def _card(r):
        if "_region" in r and isinstance(r.get("_region"), str):
            region, owner = r["_region"], r.get("_owner", "")
        else:
            region, owner = _lookup(r["name"])
            owner = owner or r["pic"]          # tracker owner, else the sheet's PIC
        fix = DEAL_FIXES.get(_norm(r["name"]), {})
        region, owner = fix.get("region", region), fix.get("owner", owner)
        rev = None if pd.isna(r["rev"]) else float(r["rev"])
        mon = [k for k, v in _MONTHS.items() if v == r["month"]]
        return {"name": r["name"], "rev": rev, "region": region or "", "owner": owner or "",
                "month": mon[0].title() if mon else ""}

    # Proposals the customer has parked ("we'll revisit"): the tracker marks the lead
    # Active / Dropped = "Revisit". Matched to a proposal by the first word of its name.
    status_col = tracker["Active / Dropped"] if "Active / Dropped" in tracker.columns else pd.Series(dtype=str)
    revisit_words = {_norm(n).split(" ")[0] for n, s in zip(tracker["Lead name"], status_col)
                     if str(s).strip().lower() == "revisit"}

    stages = {"<60": [], ">60": [], "Revisit": [], "Won": [], "Lost": []}
    for _, r in df.iterrows():
        key = r["status"] if r["status"] in ("Won", "Lost") else _bucket(r["month"])
        if key in ("<60", ">60") and _norm(r["name"]).split(" ")[0] in revisit_words:
            key = "Revisit"
        stages[key].append(_card(r))
    for k in stages:   # biggest first, deals with no value last
        stages[k].sort(key=lambda c: -(c["rev"] or 0))

    # Net-new leads this year
    first = tracker["First conv date"].map(_date)
    leads = int((first.map(lambda d: d is not None and d.year == 2026)).sum())

    count = df["status"].value_counts()
    return {
        "leads": leads,
        "proposals": len(df),
        "won": int(count.get("Won", 0)),
        "lost": int(count.get("Lost", 0)),
        "discussion": int(count.get("In discussion", 0)),
        "stages": stages,
        "rev_missing": [c["name"] for c in stages["Won"] if c["rev"] is None],
    }
