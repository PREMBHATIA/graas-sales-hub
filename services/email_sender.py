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
from html import unescape as _html_unescape
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from typing import Optional

from .sheets_client import append_log_row, fetch_log_rows
from .email_layout import wrap_email, body_to_paragraphs, logo_mime_part


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

# Internal watchers — Graas folks who receive one copy of every bulk campaign
# send. Maintained as a "Watchers" tab (single "email" column) in the Outreach
# Log sheet so the list is self-serve; copies bypass dedup AND the weekly cap
# and are logged with template "... (internal copy)" so analytics can filter.
WATCHERS_TAB_NAME = "Watchers"

# Every EXTERNAL send is silently BCC'd to this list (true BCC — envelope
# recipients only, no header, invisible to the prospect). Tests and internal
# watcher copies are excluded so these folks aren't double-copied. Override
# via env AUDIT_BCC (comma-separated); set AUDIT_BCC="" to disable.
AUDIT_BCC_DEFAULT = ("prem@graas.ai,amruta@graas.ai,"
                     "dhanashree.mohite@graas.ai,ajinkya.patil@graas.ai")


def _audit_bcc() -> list:
    raw = os.getenv("AUDIT_BCC", AUDIT_BCC_DEFAULT)
    return [e.strip().lower() for e in raw.split(",") if "@" in e.strip()]

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


# ── Raw (bring-your-own) HTML mode ───────────────────────────────────────────
# When the composer is in "Paste my own HTML" mode, `body` is already a fully
# authored HTML email. We must NOT escape it, paragraphise it, or wrap it in a
# Graas shell — it renders as-authored. Two things still happen:
#   1. bare URLs in loose text become tracked links (her own <a> tags are left
#      completely alone, so her CTAs keep their exact destinations);
#   2. the open-tracking pixel is appended.
# The CID logo is NOT attached in this mode — her HTML brings its own imagery.

_TAG_SPLIT_RE = re.compile(r"(<[^>]+>)")
# Elements whose *text content* must not be linkified: existing links, and any
# style/script blocks (a bare-looking URL inside CSS `url(...)` is not a link).
_SKIP_OPEN_RE = re.compile(r"<\s*(a|style|script)\b", re.I)
_SKIP_CLOSE_RE = re.compile(r"<\s*/\s*(a|style|script)\s*>", re.I)


def _linkify_bare_text(text: str, tracking_id: str, base: str) -> str:
    """Turn bare URLs in a loose-text fragment into tracked anchors."""

    def _sub(m: "re.Match") -> str:
        raw = m.group(1)
        trail = ""
        while raw and raw[-1] in ".,);:":       # don't swallow trailing punctuation
            trail, raw = raw[-1] + trail, raw[:-1]
        dest = raw.replace("&amp;", "&")
        if base and tracking_id:
            href = f'{base}?t={tracking_id}&e=click&u={quote(dest, safe="")}'
        else:
            href = raw
        return f'<a href="{href}">{raw}</a>{trail}'

    return _URL_RE.sub(_sub, text)


_HREF_RE = re.compile(r'''(href\s*=\s*)(["'])(https?://[^"']+)\2''', re.I)


def _track_anchor_href(tag: str, tracking_id: str, base: str) -> str:
    """Rewrite an <a> tag's http(s) href through the click tracker.

    The destination URL (including any UTM params) is preserved inside the
    redirect, so GA attribution still works — the tracker just counts the click
    on the way through. mailto:/tel:/# hrefs are untouched. Added because the
    Aug 21 campaign's CTA clicks were invisible: raw mode used to leave author
    anchors alone, so the composer could never count them.
    """
    def _sub(m: "re.Match") -> str:
        dest = m.group(3)
        return f'{m.group(1)}{m.group(2)}{base}?t={tracking_id}&e=click&u={quote(dest, safe="")}{m.group(2)}'
    return _HREF_RE.sub(_sub, tag)


def _linkify_raw_html(html: str, tracking_id: str) -> str:
    """Make author-supplied HTML click-trackable without changing how it renders.

    Walks the HTML tag-by-tag: bare URLs in loose text become tracked anchors
    (outside <a>/<style>/<script>), and existing <a href="http…"> attributes are
    rewritten through the tracking redirect with the original destination (and
    its UTMs) preserved. All other markup passes through verbatim.
    """
    base = _tracking_base()
    skip_depth = 0
    out = []
    for tok in _TAG_SPLIT_RE.split(html):
        if not tok:
            continue
        if tok.startswith("<") and tok.endswith(">"):
            if _SKIP_CLOSE_RE.match(tok):
                skip_depth = max(0, skip_depth - 1)
            elif _SKIP_OPEN_RE.match(tok) and not tok.rstrip().endswith("/>"):
                skip_depth += 1
            if base and tracking_id and re.match(r"<\s*a\b", tok, re.I):
                tok = _track_anchor_href(tok, tracking_id, base)
            out.append(tok)
            continue
        if skip_depth > 0:
            out.append(tok)                      # text inside <a>/<style>/<script>
            continue
        out.append(_linkify_bare_text(tok, tracking_id, base))
    return "".join(out)


def _html_to_text(html: str) -> str:
    """Small HTML→text reduction for the text/plain alternative of a raw send.

    Not a renderer — strips tags, turns <br>/</p> into line breaks, decodes
    entities, collapses whitespace. The HTML part is the real payload; this is
    just the fallback for text-only clients (and helps spam scoring, which
    dislikes an HTML part with no text alternative).
    """
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", html)
    text = re.sub(r"(?i)<\s*br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|tr|h[1-6]|li)\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = _html_unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text)
    return text.strip()


# ── Public API ───────────────────────────────────────────────────────────────

def get_weekly_cap() -> int:
    """Read weekly cap from env. Default raised 50→500 (2026-08-26): 50 blocked
    a 46-recipient segment campaign; 500 is effectively uncapped at current
    volumes while still guarding against a runaway send loop."""
    try:
        return int(os.getenv("WEEKLY_SEND_CAP", "500"))
    except ValueError:
        return 500


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


def fetch_watchers() -> list:
    """Internal watcher emails from the Watchers tab, deduped, order kept."""
    sheet_id = os.getenv("EMAIL_LOG_SHEET_ID", "")
    if not sheet_id:
        return []
    try:
        df = fetch_log_rows(sheet_id, WATCHERS_TAB_NAME)
    except Exception:
        return []
    if df.empty or "email" not in df.columns:
        return []
    out = []
    for e in df["email"].astype(str):
        e = e.strip().lower()
        if e and "@" in e and e not in out:
            out.append(e)
    return out


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
    # Internal watcher copies don't count toward the cap (mirrors bypass_cap
    # on the send side — without this they'd still eat the cap indirectly).
    if "template" in sent.columns:
        sent = sent[~sent["template"].astype(str).str.endswith("(internal copy)")]
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
    layout: str = "minimal",
    headline: str = "",
    deck: str = "",
    bypass_cap: bool = False,
    precleared: bool = False,
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

    # precleared=True → the bulk pre-flight already ran cap/suppression/dedup
    # checks against the whole batch; re-reading the sheet per recipient here
    # only burns Sheets API quota (which is what rate-limited the log writes).
    # Internal watcher copies bypass the cap — they're not outreach volume.
    if not precleared and not bypass_cap and remaining_cap() <= 0:
        return False, f"Weekly cap reached ({get_weekly_cap()} sends in last 7d)"

    if not to_email or "@" not in to_email:
        return False, f"Invalid recipient: {to_email}"

    # Suppression check — block if recipient is on the do-not-contact list.
    # Test addresses can also be suppressed (e.g. someone typo'd them in by accident);
    # if you really need to send to a suppressed address, remove it from the
    # Suppressions tab in the Outreach Log sheet first.
    if not precleared:
        suppressed, supp_reason = is_suppressed(to_email)
        if suppressed:
            return False, f"On suppression list: {supp_reason or 'no reason given'}"

    # Dedup check — refuse to email the same recipient twice within DEDUP_DAYS
    # unless bypass_dedup is explicitly True (test mode, or composer override).
    if not precleared and not bypass_dedup:
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

    # Per-send token — ties the open/click beacons back to this log row.
    tracking_id = uuid.uuid4().hex
    unsub_href = f"mailto:insights@graas.ai?subject=Unsubscribe%20{to_email}"

    # Root is "related" so the inline graas logo (cid:graaslogo) resolves; it
    # holds an "alternative" part (plain + branded HTML) and the logo image.
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_display, smtp_user))
    msg["To"] = formataddr((to_name or "", to_email))
    msg["Reply-To"] = formataddr((sender_name, reply_to))
    msg["Message-ID"] = make_msgid(domain="graas.ai")
    # One-line-of-defence unsubscribe (helps deliverability; also gives Gmail a
    # native unsubscribe affordance). Recipient lands in the Suppressions tab.
    msg["List-Unsubscribe"] = f"<{unsub_href}>"

    alt = MIMEMultipart("alternative")
    msg.attach(alt)

    if layout == "raw":
        # Bring-your-own HTML: render exactly as authored — no escaping, no
        # paragraphising, no Graas shell, no CID logo. Only bare URLs in loose
        # text get tracked links (her <a> tags are left intact), and the open
        # beacon is appended. text/plain is a tag-stripped fallback.
        alt.attach(MIMEText(_html_to_text(body), "plain", "utf-8"))
        html_full = _linkify_raw_html(body, tracking_id) + _tracking_pixel_html(tracking_id)
        alt.attach(MIMEText(html_full, "html", "utf-8"))
        # No logo_mime_part() — her HTML carries its own imagery.
    else:
        alt.attach(MIMEText(body, "plain", "utf-8"))
        # Header/footer-only: body paragraphs are the user's text verbatim, links
        # rewritten through the tracking endpoint, plus the hidden open beacon.
        body_html = body_to_paragraphs(
            body, linkify=lambda h: _linkify_with_tracking(h, tracking_id)
        ) + _tracking_pixel_html(tracking_id)
        html_full = wrap_email(
            layout if layout in ("branded", "minimal") else "minimal",
            body_html, sender_name=sender_name, unsubscribe_href=unsub_href,
            headline=headline, deck=deck,
            date_str=datetime.now().strftime("%B %-d, %Y"),
        )
        alt.attach(MIMEText(html_full, "html", "utf-8"))
        msg.attach(logo_mime_part())

    # Audit BCC — external sends only. True BCC: the addresses go on the SMTP
    # envelope, never into the message headers, so recipients can't see them.
    _internal_send = (
        "[TEST]" in (company or "") or "[INTERNAL WATCHER]" in (company or "")
        or str(template).endswith("(test)") or str(template).endswith("(internal copy)")
    )
    _rcpts = [to_email]
    if not _internal_send:
        _rcpts += [b for b in _audit_bcc() if b != to_email.strip().lower()]

    status = "sent"
    error_msg = ""
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, _rcpts, msg.as_string())
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
        # Retry with backoff — bulk sends burst the Sheets API and rate-limited
        # appends silently dropped log rows (Aug 21: 9 of 18 watcher sends went
        # out but never got logged, so the log undercounted deliveries).
        import time as _time
        for _attempt, _wait in enumerate((0, 2, 5, 10)):
            if _wait:
                _time.sleep(_wait)
            try:
                if append_log_row(sheet_id, LOG_TAB_NAME, log_row, headers=LOG_HEADERS):
                    break
            except Exception:
                pass

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
