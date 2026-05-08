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
import smtplib
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
    "subject", "body", "status", "error_msg",
]

SUPPRESSION_TAB_NAME = "Suppressions"
SUPPRESSION_HEADERS = ["email", "reason", "added_at_utc", "added_by"]


# ── Public API ───────────────────────────────────────────────────────────────

def get_weekly_cap() -> int:
    """Read weekly cap from env, default 50."""
    try:
        return int(os.getenv("WEEKLY_SEND_CAP", "50"))
    except ValueError:
        return 50


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
) -> tuple[bool, str]:
    """Send a single email + log the result.

    Returns (success, message). Message is "ok" on success or the error reason.
    Enforces:
      - preflight config check
      - weekly cap (refuses send if cap reached)
      - sender_label must be a known sender
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

    # Plain text + minimal HTML (just escapes the body and preserves line breaks)
    msg.attach(MIMEText(body, "plain", "utf-8"))
    html_body = (
        "<html><body style=\"font-family: -apple-system, system-ui, sans-serif; "
        "color: #111; line-height: 1.5;\">"
        + body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
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
