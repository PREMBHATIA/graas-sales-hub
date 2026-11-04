"""Recent conversations for the SalesHub homepage.

Good conversations from the last 30 days that have not reached a proposal yet.
Two sources, merged by account:

  • the presales tracker ("Overall Pipeline"): leads that are Active, still at
    4-TOF / TOF (no proposal, POC or pilot), with a conversation in the last
    30 days;
  • the monthly Sales Update deck's "Qualified opportunities" tables: accounts a
    salesperson has qualified (need, budget and decision-maker confirmed), All-e
    products only. Some of these (Boon Rawd, Yum) are not in the tracker at all.

An account in both takes the deck's value, next step, owner and country, and the
later of the two dates.

"Good" is not a field anywhere, so it means: active, spoken to recently, and not
yet a proposal. Mark a lead Dropped to take it off. Kept in its own module,
imported lazily by the homepage; the deck reading is best-effort, and any failure
leaves the tracker half standing so the landing page never breaks.
"""

import io
import re
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from services import sales_deck as sd

WINDOW_DAYS = 30
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_COUNTRY = {"id": "Indonesia", "th": "Thailand", "vn": "Vietnam", "my": "Malaysia", "sg": "Singapore",
            "ph": "Philippines", "au": "Australia", "nz": "New Zealand", "in": "India", "ae": "UAE",
            "gcc": "GCC"}
_QUALIFIED_RE = re.compile(
    r"^\[?\s*([A-Za-z][A-Za-z .'\-]{0,24}?)\s*\]?\s*:\s*[A-Za-z]+ first meetings and qualified opportunities", re.I)


def _date(s):
    """'27 Oct' / 'Oct 27' / '21/10/26' / '26 October 2026' -> datetime (this year if no
    year given). None if unreadable or in the future."""
    s = str(s or "").strip().strip("[]")
    now = datetime.now()
    d = None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", s)
    try:
        if m:
            y = int(m.group(3))
            d = datetime(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))
        else:
            m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?(?:\s+(\d{4}))?", s)
            if m and m.group(2)[:3].lower() in _MONTHS:
                d = datetime(min(int(m.group(3) or now.year), now.year), _MONTHS[m.group(2)[:3].lower()],
                             int(m.group(1)))
            else:
                m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", s)
                if m and m.group(1)[:3].lower() in _MONTHS:
                    d = datetime(min(int(m.group(3) or now.year), now.year), _MONTHS[m.group(1)[:3].lower()],
                                 int(m.group(2)))
    except ValueError:
        return None
    return d if d and d <= now + timedelta(days=2) else None


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())[:6]


def _note(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    t = re.sub(r"^[-•\s]*\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\.?(?:\s+\d{4})?\s*[-:–—]*\s*", "", t)
    return (t[:110] + "…") if len(t) > 110 else t


def _tracker(cutoff):
    from services.sheets_client import fetch_sheet_tab
    a = fetch_sheet_tab(sd._setting("ALLE_SHEET_ID", ""), "Overall Pipeline for IN and SEA",
                       force_refresh=True)   # not the 4-hour saved copy; load_recent caches 15 min
    a.columns = [str(c).strip() for c in a.columns]
    a = a[a["Lead name"].astype(str).str.strip().ne("")]
    out = []
    for _, r in a.iterrows():
        if str(r.get("Active / Dropped", "")).strip() != "Active":
            continue
        if str(r.get("Lead status", "")).strip() not in ("4-TOF", "TOF"):
            continue
        d = _date(r.get("Latest conv date"))
        if d is None or d < cutoff:
            continue
        owner = str(r.get("Owner", "")).strip() or str(r.get("Source of lead", "")).strip()
        out.append({"name": str(r["Lead name"]).strip(), "owner": owner, "where": str(r.get("Region", "")).strip(),
                    "date": d, "value": None, "step": _note(r.get("Latest Conv details"))})
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def _deck_rows(cutoff_iso: str):
    """All-e qualified opportunities from the newest Sales Update deck. [] on any failure."""
    from pptx import Presentation
    cutoff = datetime.fromisoformat(cutoff_iso)
    headers = sd._auth_header()
    picked = sd._newest_in_folder(sd._setting("SALES_DECK_FOLDER_ID", sd.DEFAULT_FOLDER_ID), headers) \
        or sd._meta(sd._setting("SALES_DECK_FILE_ID", sd.DEFAULT_FILE_ID), headers)
    prs = Presentation(io.BytesIO(sd._download(picked, headers)))
    out = []
    for sl in prs.slides:
        person = None
        for sh in sl.shapes:
            if getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip():
                m = _QUALIFIED_RE.match(sh.text_frame.text.strip().splitlines()[0].strip())
                if m and m.group(1).strip().lower() != "name":
                    person = m.group(1).strip()
                    break
        if not person:
            continue
        for sh in sl.shapes:
            if not getattr(sh, "has_table", False):
                continue
            rows = list(sh.table.rows)
            if [c.text.strip().lower() for c in rows[0].cells][:3] != ["account", "country", "product"]:
                continue
            for r in rows[1:]:
                c = [x.text for x in r.cells] + [""] * 6
                name, product = sd._clean(c[0]), sd._clean(c[2])
                d = _date(sd._clean(c[4]))
                if not name or not sd.is_alle(product) or d is None or d < cutoff:
                    continue
                country = sd._clean(c[1])
                out.append({"name": name, "owner": person, "where": _COUNTRY.get(country.lower(), country),
                            "date": d, "value": sd._money(c[3]), "step": sd._clean(c[5]).strip("[] ")})
    return out


@st.cache_data(ttl=900, show_spinner=False)
def load_recent() -> list:
    """Newest first. Each item: name, owner, where, date, value (or None), step."""
    cutoff = datetime.now() - timedelta(days=WINDOW_DAYS)
    items = {_key(x["name"]): x for x in _tracker(cutoff)}
    try:
        deck = _deck_rows(cutoff.isoformat())
    except Exception:
        deck = []   # best-effort: the tracker half still shows
    for x in deck:
        k = _key(x["name"])
        if k in items:
            old = items[k]
            x = {**x, "date": max(x["date"], old["date"]), "name": old["name"],
                 "step": x["step"] or old["step"], "where": x["where"] or old["where"]}
        items[k] = x
    return sorted(items.values(), key=lambda x: x["date"], reverse=True)
