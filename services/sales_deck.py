"""Read the monthly Sales Update deck (Ankit's) into a deals table.

The deck is a PowerPoint with one "pipeline review" block per salesperson. Each
block has an ACTIVE DEALS table: Account | Product | Stage | Value | Weighted |
Est. close | Next step. This module pulls those tables out, so the All-e Pipeline
page can show live deals by stage and by person from the deck's negotiated
numbers, which move as deals are negotiated.

Rules, all set by Prem:
  • The deck's "Value" is contract value, i.e. revenue. It is shown as it is, with no
    GP conversion (the trackers' proposal amounts are revenue too, so every page
    speaks the same unit).
  • Weighted value = value × the stage probability. The deck's own "Weighted" column
    is not used: it is sometimes blank, "TBC" or a percentage. Where it IS a dollar
    figure that disagrees with value × stage probability, the row is flagged.
  • Stage probabilities are Ankit's: Opportunity 10%, Value validation 30%,
    Commercials aligned 50%, Approvals & contracting 75%.

Which file: SALES_DECK_FOLDER_ID, if the service account can list it, gives the
newest deck in that folder (each month is a new file with the date in its name).
Otherwise SALES_DECK_FILE_ID is read directly. Both resolve env → st.secrets →
the defaults below. Unfilled template rows are skipped.
"""

import io
import os
import re
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

STAGES = [  # (name, probability), lowest stage first
    ("Opportunity", 0.10),
    ("Value validation", 0.30),
    ("Commercials aligned", 0.50),
    ("Approvals & contracting", 0.75),
]
STAGE_PROB = dict(STAGES)
STAGE_ORDER = [s for s, _ in STAGES]

DEFAULT_FILE_ID = "1Bf6oiecIzaJTEkVp4jfLRdifxuwpGBki"      # 2 Nov 2026 deck
DEFAULT_FOLDER_ID = "1vfqOBOphCeTIMppA_KW8k2PQEBS0nMPw"    # the folder it sits in
_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_GSLIDES = "application/vnd.google-apps.presentation"

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_PLACEHOLDERS = {"", "account name", "product", "stage", "$xk", "mmm yyyy", "action, owner, date",
                 "action, date", "tbc", "tbd", "-", "n/a"}
_PERSON_RE = re.compile(r"^\[?\s*([A-Za-z][A-Za-z .'\-]{0,24}?)\s*\]?\s*:\s*deals in active progress", re.I)


def _setting(name: str, default: str) -> str:
    v = os.getenv(name, "")
    if not v:
        try:
            if hasattr(st, "secrets") and name in st.secrets:
                v = st.secrets[name]
        except Exception:
            v = ""
    return str(v or default)


# ── Drive access ──────────────────────────────────────────────────────────────

def _auth_header() -> dict:
    from google.auth.transport.requests import Request
    from services.sheets_client import _get_drive_credentials
    creds = _get_drive_credentials()
    if creds is None:
        raise RuntimeError("No Google service-account credentials are configured.")
    creds.refresh(Request())
    return {"Authorization": f"Bearer {creds.token}"}


def _service_account_email() -> str:
    try:
        from services.sheets_client import _get_drive_credentials
        return getattr(_get_drive_credentials(), "service_account_email", "") or "the app's service account"
    except Exception:
        return "the app's service account"


def _meta(file_id: str, headers: dict) -> dict:
    r = requests.get(f"https://www.googleapis.com/drive/v3/files/{file_id}",
                     params={"fields": "id,name,mimeType,modifiedTime", "supportsAllDrives": "true"},
                     headers=headers, timeout=30)
    if r.status_code in (403, 404):
        raise RuntimeError(
            f"The service account can't open the deck. Share the deck (or its folder) with "
            f"{_service_account_email()} as a viewer.")
    r.raise_for_status()
    return r.json()


def _newest_in_folder(folder_id: str, headers: dict):
    """Newest sales-update deck in the folder, or None when the folder can't be
    listed (no access) or holds no matching file."""
    try:
        r = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            params={"q": f"'{folder_id}' in parents and trashed=false",
                    "fields": "files(id,name,mimeType,modifiedTime)", "pageSize": 100,
                    "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"},
            headers=headers, timeout=30)
        if r.status_code != 200:
            return None
        files = [f for f in r.json().get("files", [])
                 if f.get("mimeType") in (_PPTX, _GSLIDES)
                 and "salesupdate" in f.get("name", "").lower().replace(" ", "").replace("_", "")]
        return max(files, key=lambda f: f["modifiedTime"]) if files else None
    except Exception:
        return None


def _download(meta: dict, headers: dict) -> bytes:
    fid = meta["id"]
    if meta.get("mimeType") == _GSLIDES:
        r = requests.get(f"https://www.googleapis.com/drive/v3/files/{fid}/export",
                         params={"mimeType": _PPTX}, headers=headers, timeout=120)
    else:
        r = requests.get(f"https://www.googleapis.com/drive/v3/files/{fid}",
                         params={"alt": "media", "supportsAllDrives": "true"}, headers=headers, timeout=120)
    r.raise_for_status()
    return r.content


# ── Parsing ───────────────────────────────────────────────────────────────────

def _clean(s) -> str:
    s = str(s or "").strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip()
    return "" if s.lower() in _PLACEHOLDERS else s


def _money(s):
    """'$40K' / '~$75K' / '$55.5K' -> dollars. None for blanks, TBC and percentages."""
    s = _clean(s)
    if not s or "%" in s:
        return None
    m = re.search(r"(\d[\d,]*\.?\d*)\s*([KkMm]?)", s)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower()
    return n * (1_000 if unit == "k" else 1_000_000 if unit == "m" else 1)


def _stage(s):
    t = _clean(s).lower()
    if t.startswith("opportun"):
        return "Opportunity"
    if t.startswith("value"):
        return "Value validation"
    if t.startswith("comm"):
        return "Commercials aligned"
    if t.startswith("approv"):
        return "Approvals & contracting"
    return None


def _close_period(s):
    """'Jan 2027' -> (2027, 1); 'Q1 2027' -> (2027, 3) (quarter end). None if unreadable."""
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(20\d\d)", s, re.I)
    if m:
        return int(m.group(2)), _MONTHS[m.group(1).lower()]
    q = re.search(r"\bQ([1-4])\s*(20\d\d)", s, re.I)
    if q:
        return int(q.group(2)), int(q.group(1)) * 3
    return None


# The Pipeline page is All-e only; the deck also carries Trustana, Extract, Hoppr and
# Turbo deals. A deal counts as All-e when its Product names All-e or one of its
# agents (WhatsApp / LINE / voice). Anything else is left out and listed on the page
# so a misread product name can't make a deal vanish unnoticed.
_ALLE_RE = re.compile(r"\ball[\s\-]?e\b|\bagents?\b|\bvoice\b|\bwhatsapp\b|\bordering\b", re.I)


def is_alle(product: str) -> bool:
    return bool(_ALLE_RE.search(product or ""))


def _shape_texts(slide):
    for sh in slide.shapes:
        if getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip():
            yield sh.text_frame.text.strip()


def parse_deck(data: bytes, ref_date: datetime):
    """Bytes of the .pptx -> (deals DataFrame, people list). `ref_date` is when
    the deck was last edited; close dates before its month are flagged."""
    from pptx import Presentation  # imported here so the page still loads if it is missing
    prs = Presentation(io.BytesIO(data))

    people_seen, rows = [], []
    for sl in prs.slides:
        person = None
        for t in _shape_texts(sl):
            m = _PERSON_RE.match(t.splitlines()[0].strip())
            # An unfilled template slide is headed "[Name]: deals in active progress".
            if m and m.group(1).strip().lower() != "name":
                person = m.group(1).strip()
                break
        if person and person not in people_seen:
            people_seen.append(person)
        for sh in sl.shapes:
            if not getattr(sh, "has_table", False):
                continue
            tbl = sh.table
            hdr = [c.text.strip().lower() for c in tbl.rows[0].cells]
            if hdr[:3] != ["account", "product", "stage"] or not person:
                continue
            for r in list(tbl.rows)[1:]:
                c = [x.text for x in r.cells] + [""] * 7
                account, stage = _clean(c[0]), _stage(c[2])
                if not account:
                    continue
                rows.append({
                    "Person": person, "Account": account, "Product": _clean(c[1]),
                    "_stage_raw": _clean(c[2]), "Stage": stage,
                    "_value": _money(c[3]), "_deck_weighted": _money(c[4]),
                    "Est. close": _clean(c[5]), "Next step": _clean(c[6]),
                })

    out = []
    for r in rows:
        stage = r["Stage"]
        prob = STAGE_PROB.get(stage)
        val = r["_value"]
        flags = []
        if stage is None:
            flags.append(f"stage '{r['_stage_raw'] or 'blank'}' isn't one of the four")
        if val is None:
            flags.append("no value")
        if val is not None and prob is not None and r["_deck_weighted"] is not None:
            exp = val * prob
            if abs(r["_deck_weighted"] - exp) > 0.06 * max(exp, 1):
                flags.append(f"deck weighted ${r['_deck_weighted']/1000:,.1f}K, but {int(prob*100)}% of "
                             f"${val/1000:,.1f}K is ${exp/1000:,.1f}K")
        period = _close_period(r["Est. close"])
        if not r["Est. close"]:
            flags.append("no est. close")
        elif period is None:
            flags.append(f"close date unclear ('{r['Est. close']}')")
        elif period < (ref_date.year, ref_date.month):
            flags.append(f"close date {r['Est. close']} has passed")
        out.append({
            "Person": r["Person"], "Account": r["Account"], "Product": r["Product"],
            "All-e": is_alle(r["Product"]),
            "Stage": stage or r["_stage_raw"] or "?", "Prob": prob,
            "Contract value": val,
            "Weighted value": None if val is None or prob is None else val * prob,
            "Est. close": r["Est. close"], "Next step": r["Next step"],
            "Flags": "; ".join(flags),
        })

    df = pd.DataFrame(out, columns=["Person", "Account", "Product", "All-e", "Stage", "Prob", "Contract value",
                                    "Weighted value", "Est. close", "Next step", "Flags"])
    if not df.empty:
        df = df.drop_duplicates(subset=["Person", "Account", "Product"], keep="first")
        df["_rank"] = df["Stage"].map({s: i for i, s in enumerate(STAGE_ORDER)}).fillna(-1)
        df = df.sort_values(["_rank", "Contract value"], ascending=[False, False]).drop(columns="_rank").reset_index(drop=True)
    return df, people_seen


@st.cache_data(ttl=1800, show_spinner=False)
def load_deals():
    """(deals DataFrame, meta dict). Raises RuntimeError with a plain-English
    message if the deck can't be found or opened. Cached for 30 minutes."""
    headers = _auth_header()
    folder = _setting("SALES_DECK_FOLDER_ID", DEFAULT_FOLDER_ID)
    picked = _newest_in_folder(folder, headers) if folder else None
    how = "newest deck in the folder"
    if picked is None:
        picked = _meta(_setting("SALES_DECK_FILE_ID", DEFAULT_FILE_ID), headers)
        how = "fixed file"
    modified = datetime.fromisoformat(picked["modifiedTime"].replace("Z", "+00:00"))
    df, people = parse_deck(_download(picked, headers), modified)
    meta = {"name": picked["name"], "modified": modified, "how": how, "people": people,
            "people_with_deals": sorted(df["Person"].unique().tolist()) if not df.empty else []}
    return df, meta
