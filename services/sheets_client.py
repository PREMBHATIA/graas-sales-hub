"""Google Sheets data client for Graas Command Center."""

import os
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from google.auth.transport import requests as greq
from dotenv import load_dotenv

load_dotenv()

# On Streamlit Cloud there's no .env file — sync st.secrets into env vars
try:
    import streamlit as st
    if hasattr(st, "secrets"):
        for _k, _v in st.secrets.items():
            if isinstance(_v, str) and _k not in ("gcp_service_account",):
                os.environ.setdefault(_k, _v)
except Exception:
    pass

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _get_client() -> Optional[gspread.Client]:
    """Get authenticated gspread client. Returns None if no credentials."""
    # Try Streamlit secrets first (for Streamlit Cloud deployment)
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
            creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=SCOPES
            )
            return gspread.authorize(creds)
    except Exception:
        pass

    # Try local credentials file
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/service_account.json")
    full_path = Path(__file__).parent.parent / creds_path
    if not full_path.exists():
        return None
    creds = Credentials.from_service_account_file(str(full_path), scopes=SCOPES)
    return gspread.authorize(creds)


def _get_credentials() -> Optional[Credentials]:
    """Get raw service account credentials (for Drive API / doc export)."""
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
            return Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=SCOPES
            )
    except Exception:
        pass
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/service_account.json")
    full_path = Path(__file__).parent.parent / creds_path
    if not full_path.exists():
        return None
    return Credentials.from_service_account_file(str(full_path), scopes=SCOPES)


def fetch_google_doc_text(doc_id: str, force_refresh: bool = False) -> str:
    """Fetch a Google Doc as plain text via the Drive export API, with caching."""
    cache_key = f"gdoc_{doc_id}"
    cache_file = CACHE_DIR / f"{cache_key}.parquet"
    meta_file  = CACHE_DIR / f"{cache_key}.meta.json"

    if not force_refresh and cache_file.exists() and meta_file.exists():
        with open(meta_file) as f:
            meta = json.load(f)
        cached_at = datetime.fromisoformat(meta["cached_at"])
        if datetime.now() - cached_at < timedelta(hours=4):
            df = pd.read_parquet(cache_file)
            return df.iloc[0, 0] if not df.empty else ""

    creds = _get_credentials()
    if creds is None:
        return ""

    try:
        session = greq.AuthorizedSession(creds)
        url = (
            f"https://docs.google.com/feeds/download/documents/export/Export"
            f"?id={doc_id}&exportFormat=txt"
        )
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            return ""
        text = resp.text
        df = pd.DataFrame({"text": [text]})
        df.to_parquet(cache_file, index=False)
        with open(meta_file, "w") as f:
            json.dump({"cached_at": datetime.now().isoformat()}, f)
        return text
    except Exception:
        return ""


def _cache_key(sheet_id: str, tab_name: str) -> str:
    return hashlib.md5(f"{sheet_id}:{tab_name}".encode()).hexdigest()


def _read_cache(sheet_id: str, tab_name: str, max_age_hours: int = 4) -> Optional[pd.DataFrame]:
    """Read cached data if fresh enough."""
    key = _cache_key(sheet_id, tab_name)
    cache_file = CACHE_DIR / f"{key}.parquet"
    meta_file = CACHE_DIR / f"{key}.meta.json"

    if cache_file.exists() and meta_file.exists():
        with open(meta_file) as f:
            meta = json.load(f)
        cached_at = datetime.fromisoformat(meta["cached_at"])
        if datetime.now() - cached_at < timedelta(hours=max_age_hours):
            return pd.read_parquet(cache_file)
    return None


def _write_cache(sheet_id: str, tab_name: str, df: pd.DataFrame):
    """Write data to cache."""
    key = _cache_key(sheet_id, tab_name)
    cache_file = CACHE_DIR / f"{key}.parquet"
    meta_file = CACHE_DIR / f"{key}.meta.json"

    df.to_parquet(cache_file, index=False)
    with open(meta_file, "w") as f:
        json.dump({
            "sheet_id": sheet_id,
            "tab_name": tab_name,
            "cached_at": datetime.now().isoformat(),
            "rows": len(df),
        }, f)


def fetch_sheet_tab(sheet_id: str, tab_name: str, force_refresh: bool = False) -> pd.DataFrame:
    """Fetch a specific tab from a Google Sheet, with caching."""
    if not force_refresh:
        cached = _read_cache(sheet_id, tab_name)
        if cached is not None:
            return cached

    client = _get_client()
    if client is None:
        # Fall back to cache even if stale
        cached = _read_cache(sheet_id, tab_name, max_age_hours=99999)
        if cached is not None:
            return cached
        return pd.DataFrame()

    try:
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.worksheet(tab_name)
    except Exception:
        # Tab doesn't exist (e.g. new month tab not yet created) — return empty
        return pd.DataFrame()

    data = worksheet.get_all_values()

    if not data:
        return pd.DataFrame()

    # Handle duplicate column names by appending suffix
    headers = data[0]
    seen = {}
    unique_headers = []
    for h in headers:
        if h in seen:
            seen[h] += 1
            unique_headers.append(f"{h}_{seen[h]}")
        else:
            seen[h] = 0
            unique_headers.append(h)

    df = pd.DataFrame(data[1:], columns=unique_headers)

    # Try to cache, but don't fail if it doesn't work
    try:
        _write_cache(sheet_id, tab_name, df)
    except Exception:
        pass

    return df


def fetch_hoppr_analysis(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch Hoppr analysis data."""
    sheet_id = os.getenv("HOPPR_SHEET_ID", "")
    return fetch_sheet_tab(sheet_id, "Hoppr__Anaysis", force_refresh)


def fetch_turbo_health_scores(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch Turbo usage health scores."""
    sheet_id = os.getenv("TURBO_SHEET_ID", "")
    return fetch_sheet_tab(sheet_id, "Usage Health Score", force_refresh)


def fetch_revenue_aop(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch AOP revenue data."""
    sheet_id = os.getenv("REVENUE_SHEET_ID", "")
    return fetch_sheet_tab(sheet_id, "AOP -2026", force_refresh)


def fetch_revenue_proposals(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch proposals data."""
    sheet_id = os.getenv("REVENUE_SHEET_ID", "")
    return fetch_sheet_tab(sheet_id, "Proposals", force_refresh)


def fetch_alle_active_presales(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch All-e Active Presales data."""
    sheet_id = os.getenv("ALLE_SHEET_ID", "")
    return fetch_sheet_tab(sheet_id, "Active presales", force_refresh)


def fetch_alle_dropped_leads(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch All-e Dropped Leads data."""
    sheet_id = os.getenv("ALLE_SHEET_ID", "")
    return fetch_sheet_tab(sheet_id, "Dropped leads", force_refresh)


def fetch_alle_gtm_india(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch All-e 2026 GTM India targets."""
    sheet_id = os.getenv("ALLE_SHEET_ID", "")
    return fetch_sheet_tab(sheet_id, "2026 - GTM India", force_refresh)


def fetch_ar_by_bu(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch Group AR by BU — latest weekly tab from the AR sheet.

    The sheet has weekly tabs named like '28th Mar 2026', '21st Mar 2026', etc.
    We find the latest dated tab automatically.
    """
    sheet_id = os.getenv("AR_SHEET_ID", "")
    if not sheet_id:
        return pd.DataFrame()

    client = _get_client()
    if client is None:
        return pd.DataFrame()

    try:
        spreadsheet = client.open_by_key(sheet_id)
        worksheets = spreadsheet.worksheets()

        # Find tabs that look like dates (contain month names)
        import re
        from datetime import datetime as dt
        month_pattern = re.compile(
            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', re.IGNORECASE
        )
        date_tabs = []
        for ws in worksheets:
            title = ws.title
            if month_pattern.search(title) and any(c.isdigit() for c in title):
                # Try parsing the date
                for fmt in [
                    "%dst %b %Y", "%dnd %b %Y", "%drd %b %Y", "%dth %b %Y",
                    "%d %b %Y", "%d %B %Y",
                    "%dst %B %Y", "%dnd %B %Y", "%drd %B %Y", "%dth %B %Y",
                    "%B %Y",
                ]:
                    try:
                        # Clean up the title for parsing
                        clean = title.strip()
                        parsed = dt.strptime(clean, fmt)
                        date_tabs.append((parsed, ws))
                        break
                    except ValueError:
                        continue

        if not date_tabs:
            return pd.DataFrame()

        # Sort by date descending, pick the latest
        date_tabs.sort(key=lambda x: x[0], reverse=True)
        latest_ws = date_tabs[0][1]
        latest_tab_name = latest_ws.title

        # Check cache first
        if not force_refresh:
            cached = _read_cache(sheet_id, latest_tab_name)
            if cached is not None:
                return cached

        data = latest_ws.get_all_values()
        if not data:
            return pd.DataFrame()

        # Return raw data as DataFrame (no header processing — the page will handle it)
        df = pd.DataFrame(data)

        try:
            _write_cache(sheet_id, latest_tab_name, df)
        except Exception:
            pass

        return df
    except Exception:
        return pd.DataFrame()


def fetch_ar_monthly_snapshots(force_refresh: bool = False) -> dict:
    """Fetch AR data from end-of-month tabs for monthly comparison.

    Returns dict like {'Jan': DataFrame, 'Feb': DataFrame, 'Mar': DataFrame}
    Each DataFrame is raw (same format as fetch_ar_by_bu).
    """
    sheet_id = os.getenv("AR_SHEET_ID", "")
    if not sheet_id:
        return {}

    # Known end-of-month tab names
    monthly_tabs = {
        "Jan": "31st Jan 2026",
        "Feb": "27th Feb 2026",
        "Mar": "28th Mar 2026",
    }

    result = {}
    client = None

    for month, tab_name in monthly_tabs.items():
        # Check cache first
        cache_key = f"ar_monthly_{tab_name}"
        if not force_refresh:
            cached = _read_cache(sheet_id, cache_key)
            if cached is not None:
                result[month] = cached
                continue

        # Lazy-init client
        if client is None:
            client = _get_client()
            if client is None:
                return result

        try:
            spreadsheet = client.open_by_key(sheet_id)
            ws = spreadsheet.worksheet(tab_name)
            data = ws.get_all_values()
            if data:
                df = pd.DataFrame(data)
                try:
                    _write_cache(sheet_id, cache_key, df)
                except Exception:
                    pass
                result[month] = df
        except Exception:
            continue

    return result


def load_from_csv(csv_path: str) -> pd.DataFrame:
    """Load data from a local CSV file (fallback when no API credentials)."""
    return pd.read_csv(csv_path)


def load_from_excel(file) -> pd.DataFrame:
    """Load data from an uploaded Excel file."""
    return pd.read_excel(file, engine="openpyxl")


def get_last_refresh_time(sheet_id: str, tab_name: str) -> Optional[str]:
    """Get the last time data was cached."""
    key = _cache_key(sheet_id, tab_name)
    meta_file = CACHE_DIR / f"{key}.meta.json"
    if meta_file.exists():
        with open(meta_file) as f:
            meta = json.load(f)
        return meta.get("cached_at", "Unknown")
    return None
