"""Email sender — Option A (quick & dirty).

Sends via SMTP from insights@graas.ai using a Gmail App Password.
Visible "From" is always insights@; the chosen sender's address goes in Reply-To
so replies route to the right inbox.

Logs every send (success or failure) to a Google Sheet for auditability and
weekly-cap enforcement.

Required env vars:
    SMTP_USER            insights@graas.ai
    SMTP_PASS            16-char Gmail App Password (NOT the login password)
    EMAIL_LOG_SHEET_ID   Google Sheet ID for "Graas Outreach Log"
    WEEKLY_SEND_CAP      Optional, default 50

The log sheet must be shared with the service account email
(commandcenter@prefab... or whichever is in credentials/service_account.json)
with EDITOR permission, otherwise sends will be blocked.
"""

import os
import re
import smtplib
import uuid
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from typing import Optional

from .sheets_client import append_log_row, fetch_log_rows


# ── Configuration ────────────────────────────────────────────────────────────

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# Display name + email for each sender option in the UI.
SENDERS = {
    "Prem":           ("Prem Bhatia",    "prem@graas.ai"),
    "Amruta":         ("Amruta",         "amruta@graas.ai"),
    "Gaurav (GG)":    ("Gaurav",         "gaurav@graas.ai"),
    "Insights":       ("Graas Insights", "insights@graas.ai"),
}

LOG_TAB_NAME = "Sends"
LOG_HEADERS = [
    "timestamp_utc", "sender_label", "from_email", "reply_to",
    "to_email", "to_name", "company", "bucket", "template",
    "subject", "body", "status", "error_msg", "tracking_id",
]

SUPPRESSION_TAB_NAME = "Suppressions"
SUPPRESSION_HEADERS = ["email", "reason", "added_at_utc", "added_by"]

# ── Open / click tracking ────────────────────────────────────────────────────
# PIXEL_BASE_URL = the deployed Apps Script web-app URL that logs hits into the
# "Tracking" tab of the same Outreach Log sheet. If it's unset, every helper
# below degrades to a no-op and mail sends exactly as before — so this is safe
# to ship before the endpoint exists.
#
# Caveat worth remembering when reading the numbers: Apple Mail Privacy
# Protection pre-fetches images whether or not a human opened the mail, and
# Gmail proxies/caches them. Treat OPEN rate as directional only — compare
# variants against each other, never quote the absolute number. CLICKS are a
# deliberate human action and are the metric to trust.

_URL_RE = re.compile(r'(https?://[^\s<>"]+)')


def _tracking_base() -> str:
    return (os.getenv("PIXEL_BASE_URL") or "").strip()


def _tracking_pixel_html(tracking_id: str) -> str:
    """1x1 hidden beacon appended to the HTML part."""
    base = _tracking_base()
    if not base or not tracking_id:
        return ""
    return (
        f'<img src="{base}?t={tracking_id}&e=open" width="1" height="1" '
        f'style="display:none;max-height:0;overflow:hidden" alt="">'
    )


def _linkify_with_tracking(html: str, tracking_id: str) -> str:
    """Turn bare URLs in the (already HTML-escaped) body into anchors.

    The composer body is plain text that we escape into HTML, so there are no
    <a> tags to rewrite — we create them. When tracking is configured the href
    goes through the endpoint, which logs the click and redirects on.
    """
    base = _tracking_base()

    def _sub(m: "re.Match") -> str:
        raw = m.group(1)
        trail = ""
        while raw and raw[-1] in ".,);:":       # don't swallow sentence punctuation
            trail, raw = raw[-1] + trail, raw[:-1]
        dest = raw.replace("&amp;", "&")        # undo the body escaping for the real URL
        if base and tracking_id:
            href = f'{base}?t={tracking_id}&e=click&u={quote(dest, safe="")}'
        else:
            href = raw
        return f'<a href="{href}">{raw}</a>{trail}'

    return _URL_RE.sub(_sub, html)


# ── Public API ───────────────────────────────────────────────────────────────

def get_weekly_cap() -> int:
    """Read weekly cap from env, default 50."""
    try:
        return int(os.getenv("WEEKLY_SEND_CAP", "50"))
    except ValueError:
        return 50


def get_dedup_days() -> int:
    """Read dedup window from env, default 14 days."""
    try:
        return int(os.getenv("DEDUP_DAYS", "14"))
    except ValueError:
        return 14


def recent_sent_emails(days: int = None) -> set:
    """Return a set of lowercased emails sent successfully within the last N days.

    Used by bulk send to filter recipients in one pass instead of N sheet reads.
    """
    if days is None:
        days = get_dedup_days()
    sheet_id = os.getenv("EMAIL_LOG_SHEET_ID", "")
    if not sheet_id:
        return set()
    df = fetch_log_rows(sheet_id, LOG_TAB_NAME)
    if df.empty or "to_email" not in df.columns or "timestamp_utc" not in df.columns:
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    def _parse(ts):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    sent = df[df["status"] == "sent"].copy()
    sent["_ts"] = sent["timestamp_utc"].apply(_parse)
    sent = sent[(sent["_ts"].notna()) & (sent["_ts"] >= cutoff)]
    return set(sent["to_email"].str.lower().str.strip().tolist())


def suppressed_emails() -> set:
    """Return a set of lowercased suppressed emails — used for bulk filtering."""
    df = fetch_suppressions()
    if df.empty or "email" not in df.columns:
        return set()
    return set(df["email"].str.lower().str.strip().tolist())


def last_sent_to(email: str):
    """Return (last_sent_datetime_utc, days_ago) for a recipient, or (None, None) if never sent.

    Looks at successful sends only (status == 'sent'). Test sends count too —
    composer-level bypass_dedup handles the test-mode case separately.
    """
    if not email:
        return None, None
    sheet_id = os.getenv("EMAIL_LOG_SHEET_ID", "")
    if not sheet_id:
        return None, None
    df = fetch_log_rows(sheet_id, LOG_TAB_NAME)
    if df.empty or "to_email" not in df.columns or "timestamp_utc" not in df.columns:
        return None, None
    target = email.lower().strip()
    matches = df[
        (df["to_email"].str.lower().str.strip() == target) &
        (df["status"] == "sent")
    ].copy()
    if matches.empty:
        return None, None

    def _parse(ts):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    matches["_ts"] = matches["timestamp_utc"].apply(_parse)
    matches = matches[matches["_ts"].notna()]
    if matches.empty:
        return None, None
    latest = matches["_ts"].max()
    days_ago = (datetime.now(timezone.utc) - latest).days
    return latest, days_ago


def get_sends_this_week() -> int:
    """Count successful sends in the trailing 7 days from the log sheet."""
    sheet_id = os.getenv("EMAIL_LOG_SHEET_ID", "")
    if not sheet_id:
        return 0
    df = fetch_log_rows(sheet_id, LOG_TAB_NAME)
    if df.empty or "timestamp_utc" not in df.columns or "status" not in df.columns:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    def _parse(ts):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    sent = df[df["status"] == "sent"].copy()
    sent["_ts"] = sent["timestamp_utc"].apply(_parse)
    sent = sent[sent["_ts"].notna()]
    return int((sent["_ts"] >= cutoff).sum())


def remaining_cap() -> int:
    return max(0, get_weekly_cap() - get_sends_this_week())


def preflight_check() -> Optional[str]:
    """Return a human-readable error string if sending is misconfigured, else None."""
    if not os.getenv("SMTP_USER"):
        return "SMTP_USER not set in .env"
    if not os.getenv("SMTP_PASS"):
        return "SMTP_PASS not set in .env (need Gmail App Password for insights@)"
    if not os.getenv("EMAIL_LOG_SHEET_ID"):
        return "EMAIL_LOG_SHEET_ID not set in .env"
    return None


def send_email(
    sender_label: str,
    to_email: str,
    to_name: str,
    company: str,
    subject: str,
    body: str,
    bucket: str = "",
    template: str = "",
    bypass_dedup: bool = False,
) -> tuple[bool, str]:
    """Send a single email + log the result.

    Returns (success, message). Message is "ok" on success or the error reason.
    Enforces:
      - preflight config check
      - weekly cap (refuses send if cap reached)
      - sender_label must be a known sender
      - suppression list (do-not-contact emails)
      - dedup window (refuses if same email was sent within DEDUP_DAYS unless
        bypass_dedup=True; bypass is meant for test mode + user-confirmed
        overrides from the composer)
    """
    err = preflight_check()
    if err:
        return False, err

    if sender_label not in SENDERS:
        return False, f"Unknown sender: {sender_label}"

    if remaining_cap() <= 0:
        return False, f"Weekly cap reached ({get_weekly_cap()} sends in last 7d)"

    if not to_email or "@" not in to_email:
        return False, f"Invalid recipient: {to_email}"

    # Suppression check — block if recipient is on the do-not-contact list.
    # Test addresses can also be suppressed (e.g. someone typo'd them in by accident);
    # if you really need to send to a suppressed address, remove it from the
    # Suppressions tab in the Outreach Log sheet first.
    suppressed, supp_reason = is_suppressed(to_email)
    if suppressed:
        return False, f"On suppression list: {supp_reason or 'no reason given'}"

    # Dedup check — refuse to email the same recipient twice within DEDUP_DAYS
    # unless bypass_dedup is explicitly True (test mode, or composer override).
    if not bypass_dedup:
        dedup_days = get_dedup_days()
        last_sent, days_ago = last_sent_to(to_email)
        if last_sent and days_ago is not None and days_ago < dedup_days:
            return False, (
                f"Recipient was emailed {days_ago} day(s) ago "
                f"(dedup window = {dedup_days} days). "
                f"To override, check 'Send anyway' in the composer."
            )

    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    sender_name, reply_to = SENDERS[sender_label]
    from_display = "Graas Insights"  # Visible From line — always insights@

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_display, smtp_user))
    msg["To"] = formataddr((to_name or "", to_email))
    msg["Reply-To"] = formataddr((sender_name, reply_to))
    msg["Message-ID"] = make_msgid(domain="graas.ai")

    # Per-send token — ties the open/click beacons back to this log row.
    tracking_id = uuid.uuid4().hex

    # Plain text + minimal HTML (just escapes the body and preserves line breaks)
    msg.attach(MIMEText(body, "plain", "utf-8"))
    _escaped = (body.replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;").replace("\n", "<br>"))
    html_body = (
        "<html><body style=\"font-family: -apple-system, system-ui, sans-serif; "
        "color: #111; line-height: 1.5;\">"
        + _linkify_with_tracking(_escaped, tracking_id)
        + _tracking_pixel_html(tracking_id)
        + "</body></html>"
    )
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    status = "sent"
    error_msg = ""
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_email], msg.as_string())
    except smtplib.SMTPAuthenticationError as e:
        status, error_msg = "failed", f"SMTP auth failed — check App Password: {e}"
    except Exception as e:
        status, error_msg = "failed", f"{type(e).__name__}: {e}"

    # Always log, success or failure
    log_row = [
        datetime.now(timezone.utc).isoformat(),
        sender_label,
        smtp_user,
        reply_to,
        to_email,
        to_name or "",
        company or "",
        bucket or "",
        template or "",
        subject,
        body,
        status,
        error_msg,
        tracking_id,
    ]
    sheet_id = os.getenv("EMAIL_LOG_SHEET_ID", "")
    if sheet_id:
        append_log_row(sheet_id, LOG_TAB_NAME, log_row, headers=LOG_HEADERS)

    return (status == "sent"), (error_msg or "ok")


def recent_sends(limit: int = 20):
    """Return the most recent N sends as a DataFrame."""
    import pandas as pd
    sheet_id = os.getenv("EMAIL_LOG_SHEET_ID", "")
    if not sheet_id:
        return pd.DataFrame()
    df = fetch_log_rows(sheet_id, LOG_TAB_NAME)
    if df.empty:
        return df
    return df.tail(limit).iloc[::-1].reset_index(drop=True)


TRACKING_TAB_NAME = "Tracking"


def fetch_tracking_events():
    """Raw open/click beacons — written by the Apps Script web app.

    Columns: ts_utc | tracking_id | event | dest_url.
    """
    import pandas as pd
    sheet_id = os.getenv("EMAIL_LOG_SHEET_ID", "")
    if not sheet_id:
        return pd.DataFrame()
    try:
        return fetch_log_rows(sheet_id, TRACKING_TAB_NAME)
    except Exception:
        return pd.DataFrame()


def engagement_by_template(days: int = 30):
    """Opens / clicks per template — i.e. the A/B answer.

    Counts are UNIQUE per send (per tracking_id), so one recipient opening
    five times still counts once. Read Click % as the real signal: opens are
    inflated by Apple Mail Privacy Protection pre-fetching images.
    """
    import pandas as pd
    sends = recent_sends(limit=100000)
    if sends.empty or "tracking_id" not in sends.columns:
        return pd.DataFrame()

    s = sends.copy()
    s["tracking_id"] = s["tracking_id"].astype(str).str.strip()
    s = s[s["tracking_id"] != ""]
    if "status" in s.columns:
        s = s[s["status"].astype(str).str.strip().str.lower() == "sent"]
    if days and "timestamp_utc" in s.columns:
        _ts = pd.to_datetime(s["timestamp_utc"], errors="coerce", utc=True)
        s = s[_ts >= (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days))]
    if s.empty:
        return pd.DataFrame()

    if "template" not in s.columns:
        s["template"] = "(none)"
    s["template"] = (s["template"].astype(str).str.strip()
                     .replace({"": "(none)", "nan": "(none)"}))

    opened, clicked = set(), set()
    ev = fetch_tracking_events()
    if not ev.empty and "tracking_id" in ev.columns:
        e = ev.copy()
        e["tracking_id"] = e["tracking_id"].astype(str).str.strip()
        e["event"] = e.get("event", "").astype(str).str.strip().str.lower()
        opened = set(e.loc[e["event"] == "open", "tracking_id"])
        clicked = set(e.loc[e["event"] == "click", "tracking_id"])

    s["_opened"] = s["tracking_id"].isin(opened)
    s["_clicked"] = s["tracking_id"].isin(clicked)

    out = (s.groupby("template")
             .agg(Sent=("tracking_id", "nunique"),
                  Opened=("_opened", "sum"),
                  Clicked=("_clicked", "sum"))
             .reset_index())
    out["Open %"] = (out["Opened"] / out["Sent"] * 100).round(0)
    out["Click %"] = (out["Clicked"] / out["Sent"] * 100).round(0)
    return out.sort_values("Sent", ascending=False).reset_index(drop=True)


# ── Suppression list ─────────────────────────────────────────────────────────

def fetch_suppressions():
    """Return the suppression list as a DataFrame (email, reason, added_at_utc, added_by)."""
    import pandas as pd
    sheet_id = os.getenv("EMAIL_LOG_SHEET_ID", "")
    if not sheet_id:
        return pd.DataFrame()
    return fetch_log_rows(sheet_id, SUPPRESSION_TAB_NAME)


def is_suppressed(email: str) -> tuple[bool, str]:
    """Check if an email is on the suppression list. Returns (is_suppressed, reason)."""
    if not email:
        return False, ""
    df = fetch_suppressions()
    if df.empty or "email" not in df.columns:
        return False, ""
    target = email.lower().strip()
    matches = df[df["email"].str.lower().str.strip() == target]
    if matches.empty:
        return False, ""
    return True, str(matches.iloc[0].get("reason", ""))


def add_to_suppression(email: str, reason: str, added_by: str = "") -> bool:
    """Add an email to the suppression list. Idempotent — duplicates are skipped."""
    if not email or "@" not in email:
        return False
    sheet_id = os.getenv("EMAIL_LOG_SHEET_ID", "")
    if not sheet_id:
        return False
    already, _ = is_suppressed(email)
    if already:
        return True  # nothing to do
    row = [
        email.lower().strip(),
        reason or "",
        datetime.now(timezone.utc).isoformat(),
        added_by or "",
    ]
    return append_log_row(sheet_id, SUPPRESSION_TAB_NAME, row, headers=SUPPRESSION_HEADERS)
