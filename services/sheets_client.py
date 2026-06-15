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

# Writer scopes — used only by the email log (append-only). Kept separate from
# the read-only client so existing read paths are unaffected.
WRITER_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Drive-only scope for creating Google Docs (Prospect Brief). Kept separate from
# the spreadsheet writer so the create-file capability is opt-in and obvious.
DRIVE_FILE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",     # create/manage files this app creates
    "https://www.googleapis.com/auth/drive",          # for moving into parent folders the SA already accesses
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


def _get_writer_client() -> Optional[gspread.Client]:
    """Get gspread client with read+write scopes. Used only by email log."""
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
            creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=WRITER_SCOPES
            )
            return gspread.authorize(creds)
    except Exception:
        pass

    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/service_account.json")
    full_path = Path(__file__).parent.parent / creds_path
    if not full_path.exists():
        return None
    creds = Credentials.from_service_account_file(str(full_path), scopes=WRITER_SCOPES)
    return gspread.authorize(creds)


def append_log_row(sheet_id: str, tab_name: str, row: list, headers: Optional[list] = None) -> bool:
    """Append a single row to a sheet tab. Creates the tab + headers if missing.

    Returns True on success, False on failure (caller decides how to react).
    """
    client = _get_writer_client()
    if client is None:
        return False
    try:
        spreadsheet = client.open_by_key(sheet_id)
    except Exception:
        return False
    try:
        worksheet = spreadsheet.worksheet(tab_name)
    except Exception:
        # Tab doesn't exist — create it with headers
        try:
            worksheet = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=max(len(row), 20))
            if headers:
                worksheet.append_row(headers, value_input_option="USER_ENTERED")
        except Exception:
            return False
    try:
        # If sheet is empty and headers provided, write headers first
        if headers:
            existing = worksheet.row_values(1)
            if not existing:
                worksheet.append_row(headers, value_input_option="USER_ENTERED")
        worksheet.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception:
        return False


def fetch_log_rows(sheet_id: str, tab_name: str) -> pd.DataFrame:
    """Read all rows from a log sheet (no caching — always fresh for cap counting)."""
    client = _get_writer_client()
    if client is None:
        return pd.DataFrame()
    try:
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.worksheet(tab_name)
        data = worksheet.get_all_values()
        if not data or len(data) < 2:
            return pd.DataFrame()
        headers = data[0]
        return pd.DataFrame(data[1:], columns=headers)
    except Exception:
        return pd.DataFrame()


def _get_drive_credentials() -> Optional[Credentials]:
    """Get service account credentials with Drive-file scope for creating Docs."""
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
            return Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=DRIVE_FILE_SCOPES
            )
    except Exception:
        pass
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/service_account.json")
    full_path = Path(__file__).parent.parent / creds_path
    if not full_path.exists():
        return None
    return Credentials.from_service_account_file(str(full_path), scopes=DRIVE_FILE_SCOPES)


def create_google_doc_from_html(
    html_body: str,
    title: str,
    parent_folder_id: Optional[str] = None,
    share_with: Optional[list] = None,
) -> dict:
    """Create a native Google Doc from HTML content.

    Posts the HTML to Drive with conversion=True so it imports as a Google Doc
    (real tables preserved). Verifies the resulting mimeType.

    Args:
        html_body: the HTML content (self-contained, with tables).
        title: file title — e.g. "Prospect Brief — Nerolac — 2026-05-29".
        parent_folder_id: Drive folder ID to place the file in. None = SA's root.
        share_with: list of email addresses to grant editor access (so humans
                    can open it without needing folder access).

    Returns:
        {
            "ok": bool,
            "doc_id": str | None,
            "doc_url": str | None,
            "mime_type": str | None,
            "error": str | None,
        }
    """
    creds = _get_drive_credentials()
    if creds is None:
        return {"ok": False, "doc_id": None, "doc_url": None,
                "mime_type": None, "error": "Drive credentials unavailable"}

    try:
        session = greq.AuthorizedSession(creds)

        # Build metadata
        metadata = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",  # target type after conversion
        }
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]

        # Multipart upload — Drive's REST API expects boundary-delimited body.
        # Using the v3 uploads endpoint with uploadType=multipart.
        import json as _json
        import io
        boundary = "graas-prospect-brief-boundary"
        body = io.BytesIO()
        body.write(f"--{boundary}\r\n".encode())
        body.write(b"Content-Type: application/json; charset=UTF-8\r\n\r\n")
        body.write(_json.dumps(metadata).encode("utf-8"))
        body.write(b"\r\n")
        body.write(f"--{boundary}\r\n".encode())
        body.write(b"Content-Type: text/html; charset=UTF-8\r\n\r\n")
        body.write(html_body.encode("utf-8"))
        body.write(f"\r\n--{boundary}--\r\n".encode())

        upload_url = ("https://www.googleapis.com/upload/drive/v3/files"
                      "?uploadType=multipart&supportsAllDrives=true&fields=id,mimeType,webViewLink")
        resp = session.post(
            upload_url,
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            data=body.getvalue(),
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            return {"ok": False, "doc_id": None, "doc_url": None,
                    "mime_type": None,
                    "error": f"Drive create failed: HTTP {resp.status_code} — {resp.text[:300]}"}

        data = resp.json()
        doc_id = data.get("id")
        mime_type = data.get("mimeType", "")
        doc_url = data.get("webViewLink") or (f"https://docs.google.com/document/d/{doc_id}/edit" if doc_id else None)

        # Share with humans if requested (so they don't need folder access)
        if share_with:
            for email in share_with:
                try:
                    session.post(
                        f"https://www.googleapis.com/drive/v3/files/{doc_id}/permissions"
                        f"?sendNotificationEmail=false&supportsAllDrives=true",
                        json={"type": "user", "role": "writer", "emailAddress": email},
                        timeout=15,
                    )
                except Exception:
                    pass  # don't fail the whole operation if one share fails

        # Verify conversion happened (mimeType should be application/vnd.google-apps.document)
        if mime_type != "application/vnd.google-apps.document":
            return {"ok": False, "doc_id": doc_id, "doc_url": doc_url,
                    "mime_type": mime_type,
                    "error": f"Conversion didn't take — mimeType is '{mime_type}'. Tables likely won't render."}

        return {"ok": True, "doc_id": doc_id, "doc_url": doc_url,
                "mime_type": mime_type, "error": None}

    except Exception as e:
        return {"ok": False, "doc_id": None, "doc_url": None,
                "mime_type": None, "error": f"{type(e).__name__}: {e}"}


def list_drive_folder_docs(folder_id: str) -> list:
    """List Google Docs inside a Drive folder (Shared Drive supported).

    Returns [{id, name, modified_time}] sorted newest-first. Filters out
    non-Doc files (PDFs, slides etc.) so callers can assume export-as-text
    will work on every returned id.
    """
    creds = _get_drive_credentials()
    if creds is None:
        return []
    try:
        import urllib.parse
        session = greq.AuthorizedSession(creds)
        q = urllib.parse.quote(
            f"'{folder_id}' in parents "
            f"and mimeType='application/vnd.google-apps.document' "
            f"and trashed=false"
        )
        url = (
            f"https://www.googleapis.com/drive/v3/files"
            f"?q={q}&supportsAllDrives=true&includeItemsFromAllDrives=true"
            f"&pageSize=100&orderBy=modifiedTime desc"
            f"&fields=files(id,name,modifiedTime)"
        )
        r = session.get(url, timeout=15)
        if r.status_code == 200:
            files = r.json().get("files", [])
            return [
                {"id": f["id"], "name": f["name"], "modified_time": f.get("modifiedTime", "")}
                for f in files
            ]
    except Exception:
        pass
    return []


def fetch_drive_doc_text(doc_id: str) -> str:
    """Export a Google Doc as plain text — for injecting into LLM prompts.

    Plain text strips formatting (and the token noise that comes with it) so
    reference proposals fit more cleanly into a system prompt. For round-trip
    editing (post-call brief updates), use fetch_drive_doc_html instead.
    """
    creds = _get_drive_credentials()
    if creds is None:
        return ""
    try:
        session = greq.AuthorizedSession(creds)
        url = (
            f"https://www.googleapis.com/drive/v3/files/{doc_id}/export"
            f"?mimeType=text/plain&supportsAllDrives=true"
        )
        r = session.get(url, timeout=30)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""


def fetch_drive_doc_html(doc_id: str) -> Optional[str]:
    """Export an existing Google Doc as HTML — used to load a brief for editing."""
    creds = _get_drive_credentials()
    if creds is None:
        return None
    try:
        session = greq.AuthorizedSession(creds)
        url = f"https://www.googleapis.com/drive/v3/files/{doc_id}/export?mimeType=text/html"
        resp = session.get(url, timeout=20)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass
    return None


def update_google_doc_html(doc_id: str, new_html: str) -> dict:
    """Replace the contents of an existing Google Doc with new HTML (re-uploads + converts).

    Drive's v3 update endpoint supports media uploads; combined with mimeType target
    of vnd.google-apps.document it re-converts the content. Preserves the file ID
    and URL — keeps the team's edit history.
    """
    creds = _get_drive_credentials()
    if creds is None:
        return {"ok": False, "error": "Drive credentials unavailable"}
    try:
        session = greq.AuthorizedSession(creds)
        # PATCH endpoint with media upload + conversion
        update_url = (f"https://www.googleapis.com/upload/drive/v3/files/{doc_id}"
                      f"?uploadType=media&supportsAllDrives=true")
        resp = session.patch(
            update_url,
            headers={"Content-Type": "text/html; charset=UTF-8"},
            data=new_html.encode("utf-8"),
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            return {"ok": False, "error": f"Drive update failed: HTTP {resp.status_code} — {resp.text[:300]}"}
        return {"ok": True, "error": None}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def create_google_doc_from_docx(
    docx_bytes: bytes,
    title: str,
    parent_folder_id: Optional[str] = None,
    share_with: Optional[list] = None,
) -> dict:
    """Create a native Google Doc from a DOCX byte stream.

    DOCX → Google Doc conversion preserves font sizes, table column widths, cell
    padding, and margins far better than HTML → Doc. Same multipart-upload pattern
    as create_google_doc_from_html, just a different inner Content-Type.
    """
    creds = _get_drive_credentials()
    if creds is None:
        return {"ok": False, "doc_id": None, "doc_url": None,
                "mime_type": None, "error": "Drive credentials unavailable"}
    try:
        session = greq.AuthorizedSession(creds)
        metadata = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",  # target type after conversion
        }
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]

        import json as _json
        import io
        boundary = "graas-prospect-brief-docx-boundary"
        body = io.BytesIO()
        body.write(f"--{boundary}\r\n".encode())
        body.write(b"Content-Type: application/json; charset=UTF-8\r\n\r\n")
        body.write(_json.dumps(metadata).encode("utf-8"))
        body.write(b"\r\n")
        body.write(f"--{boundary}\r\n".encode())
        body.write(f"Content-Type: {_DOCX_MIME}\r\n\r\n".encode())
        body.write(docx_bytes)
        body.write(f"\r\n--{boundary}--\r\n".encode())

        upload_url = ("https://www.googleapis.com/upload/drive/v3/files"
                      "?uploadType=multipart&supportsAllDrives=true&fields=id,mimeType,webViewLink")
        resp = session.post(
            upload_url,
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            data=body.getvalue(),
            timeout=60,
        )
        if resp.status_code not in (200, 201):
            return {"ok": False, "doc_id": None, "doc_url": None,
                    "mime_type": None,
                    "error": f"Drive create failed: HTTP {resp.status_code} — {resp.text[:300]}"}

        data = resp.json()
        doc_id = data.get("id")
        mime_type = data.get("mimeType", "")
        doc_url = data.get("webViewLink") or (f"https://docs.google.com/document/d/{doc_id}/edit" if doc_id else None)

        if share_with:
            for email in share_with:
                try:
                    session.post(
                        f"https://www.googleapis.com/drive/v3/files/{doc_id}/permissions"
                        f"?sendNotificationEmail=false&supportsAllDrives=true",
                        json={"type": "user", "role": "writer", "emailAddress": email},
                        timeout=15,
                    )
                except Exception:
                    pass

        if mime_type != "application/vnd.google-apps.document":
            return {"ok": False, "doc_id": doc_id, "doc_url": doc_url,
                    "mime_type": mime_type,
                    "error": f"Conversion didn't take — mimeType is '{mime_type}'."}

        return {"ok": True, "doc_id": doc_id, "doc_url": doc_url,
                "mime_type": mime_type, "error": None}

    except Exception as e:
        return {"ok": False, "doc_id": None, "doc_url": None,
                "mime_type": None, "error": f"{type(e).__name__}: {e}"}


def update_google_doc_docx(doc_id: str, docx_bytes: bytes) -> dict:
    """Replace the contents of an existing Google Doc by uploading new DOCX.

    Keeps the file ID + URL + sharing intact; only the content is replaced.
    """
    creds = _get_drive_credentials()
    if creds is None:
        return {"ok": False, "error": "Drive credentials unavailable"}
    try:
        session = greq.AuthorizedSession(creds)
        update_url = (f"https://www.googleapis.com/upload/drive/v3/files/{doc_id}"
                      f"?uploadType=media&supportsAllDrives=true")
        resp = session.patch(
            update_url,
            headers={"Content-Type": _DOCX_MIME},
            data=docx_bytes,
            timeout=60,
        )
        if resp.status_code not in (200, 201):
            return {"ok": False, "error": f"Drive update failed: HTTP {resp.status_code} — {resp.text[:300]}"}
        return {"ok": True, "error": None}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


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


def clear_disk_cache() -> int:
    """Delete every parquet/meta file under data/cache/ so the next sheet read
    goes back to Google. Returns the number of files removed. Safe to call when
    the cache directory is empty.
    """
    removed = 0
    if not CACHE_DIR.exists():
        return 0
    for p in CACHE_DIR.iterdir():
        if p.is_file() and p.suffix in (".parquet", ".json"):
            try:
                p.unlink()
                removed += 1
            except Exception:
                pass
    return removed


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


def fetch_alle_pipeline(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch unified All-e pipeline (IN + SEA).

    Source of truth as of May 2026. Replaces the per-segment 'Active presales'
    and 'Dropped leads' tabs which are being archived. The 'Active / Dropped'
    column on each row tells you which segment a lead is in.
    """
    sheet_id = os.getenv("ALLE_SHEET_ID", "")
    return fetch_sheet_tab(sheet_id, "Overall Pipeline for IN and SEA", force_refresh)


def _split_pipeline(df: pd.DataFrame, segment: str) -> pd.DataFrame:
    """Filter the unified pipeline by the 'Active / Dropped' column."""
    if df.empty or "Active / Dropped" not in df.columns:
        return df
    target = segment.strip().lower()
    return df[df["Active / Dropped"].astype(str).str.strip().str.lower() == target].copy()


def fetch_alle_active_presales(force_refresh: bool = False) -> pd.DataFrame:
    """Active leads from the unified pipeline.

    Shim — was its own tab pre-May 2026. Returns the same shape as before
    so callers (CRM, Ask Graas) don't need to change.
    """
    return _split_pipeline(fetch_alle_pipeline(force_refresh), "active")


def fetch_alle_dropped_leads(force_refresh: bool = False) -> pd.DataFrame:
    """Dropped leads from the unified pipeline.

    Shim — was its own tab pre-May 2026. Returns the same shape as before
    so callers (CRM, Ask Graas) don't need to change.
    """
    return _split_pipeline(fetch_alle_pipeline(force_refresh), "dropped")


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
