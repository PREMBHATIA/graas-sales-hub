"""Bounce scanner — closes the gap between "sent" and "delivered".

The composer logs status="sent" when Gmail ACCEPTS a message. Rejections happen
later and arrive as bounce emails to insights@ — a mailbox nobody reads, so the
log said "sent" for mail that never landed (found 2026-08-26: Wipro's India CIO
had left, their server rejected us, log showed sent).

This reads insights@ over IMAP with the same App Password used for SMTP, parses
postmaster/mailer-daemon reports, and returns one row per failed recipient. The
page layer decides what to do with them (flip log rows, suppress, display).

Read-only on the mailbox: messages are fetched with readonly=True and never
deleted or flagged.

Requires SMTP_USER + SMTP_PASS (Gmail App Password with IMAP enabled).
"""

from __future__ import annotations

import email as email_lib
import imaplib
import os
import re
from email.header import decode_header, make_header
from typing import Optional

IMAP_HOST = "imap.gmail.com"

# Senders/subjects that mark a delivery-status report.
_BOUNCE_SEARCHES = [
    '(FROM "mailer-daemon")',
    '(FROM "postmaster")',
    '(SUBJECT "Undeliverable")',
    '(SUBJECT "Delivery Status Notification")',
    '(SUBJECT "couldn\'t be delivered")',
    '(SUBJECT "Returned mail")',
]

_OUR_DOMAINS = ("graas.ai",)
_NOISE = ("mailer-daemon", "postmaster", "no-reply", "noreply", "notifications")

# Reason patterns, most specific first — the phrase we surface to the user.
_REASON_PATTERNS = [
    (r"no longer with [^.\n]{0,40}", "left the company"),
    (r"(?:user|recipient|address|mailbox)[^.\n]{0,30}(?:unknown|not found|does not exist|doesn't exist)", "address doesn't exist"),
    (r"mailbox (?:is )?full|quota exceeded|over quota", "mailbox full"),
    (r"blocked by (?:a )?(?:custom )?mail flow rule|organization policy|transport\.rules", "blocked by their mail policy"),
    (r"spam|blacklist|blocked as suspicious", "flagged as spam"),
    (r"domain[^.\n]{0,30}(?:not found|does not exist|invalid)", "domain doesn't exist"),
    (r"relay(?:ing)? denied|access denied", "relay denied"),
]

# Hard vs soft: hard bounces are permanent → auto-suppress. Soft (full mailbox,
# temporary failures) are worth retrying, so they're reported but not suppressed.
_SOFT_REASONS = {"mailbox full"}


def _decode(v) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return str(v or "")


def _body_text(msg) -> str:
    chunks = []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype in ("text/plain", "message/delivery-status", "message/rfc822"):
            try:
                payload = part.get_payload(decode=True)
                if payload:
                    chunks.append(payload.decode("utf-8", "replace"))
            except Exception:
                continue
    return "\n".join(chunks)


def _classify(text: str) -> tuple:
    """(human reason, is_hard) from the bounce body."""
    low = text.lower()
    for pattern, label in _REASON_PATTERNS:
        m = re.search(pattern, low, re.I)
        if m:
            return label, label not in _SOFT_REASONS
    m = re.search(r"\b5\.\d\.\d\b[^\n]{0,90}", text)
    if m:
        return m.group(0).strip()[:100], True
    m = re.search(r"\b4\.\d\.\d\b[^\n]{0,90}", text)
    if m:
        return m.group(0).strip()[:100], False
    return "delivery failed (reason not parsed)", False


def _failed_recipients(msg, text: str) -> list:
    """Addresses the report says failed — header first, then body scan."""
    out = []
    hdr = msg.get("X-Failed-Recipients", "")
    if hdr:
        out += [a.strip() for a in hdr.split(",") if "@" in a]
    if not out:
        # "Original Message Details / Recipient Address: x@y.com" (Office 365)
        for m in re.finditer(r"(?:recipient(?:'s)?\s*address|to)\s*[:=]\s*([\w.+-]+@[\w-]+\.[\w.-]+)", text, re.I):
            out.append(m.group(1))
    if not out:
        for m in re.finditer(r"<?([\w.+-]+@[\w-]+\.[\w.-]+)>?", text):
            out.append(m.group(1))
    seen, clean = set(), []
    for a in out:
        a = a.strip().strip("<>.,;").lower()
        if not a or a in seen:
            continue
        if any(d in a for d in _OUR_DOMAINS) or any(n in a for n in _NOISE):
            continue
        seen.add(a)
        clean.append(a)
    return clean


def scan_bounces(since: str = "01-Aug-2026", limit: int = 200,
                 user: Optional[str] = None, password: Optional[str] = None) -> list:
    """Return [{email, reason, hard, subject, date, msg_id}] for bounces in the
    insights@ inbox. Empty list on any failure — never raises at the caller."""
    user = user or os.getenv("SMTP_USER", "")
    password = password or os.getenv("SMTP_PASS", "")
    if not user or not password:
        return []
    rows, seen_pairs = [], set()
    try:
        M = imaplib.IMAP4_SSL(IMAP_HOST)
        M.login(user, password)
        M.select("INBOX", readonly=True)
        ids = set()
        for crit in _BOUNCE_SEARCHES:
            try:
                typ, data = M.search(None, f"(SINCE {since})", crit)
                if typ == "OK" and data and data[0]:
                    ids |= set(data[0].split())
            except Exception:
                continue
        for mid in sorted(ids, key=lambda x: int(x))[-limit:]:
            try:
                typ, msgdata = M.fetch(mid, "(RFC822)")
                if typ != "OK" or not msgdata or not msgdata[0]:
                    continue
                msg = email_lib.message_from_bytes(msgdata[0][1])
                text = _body_text(msg)
                reason, hard = _classify(text)
                for addr in _failed_recipients(msg, text):
                    key = (addr, reason)
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    rows.append({
                        "email": addr,
                        "reason": reason,
                        "hard": hard,
                        "subject": _decode(msg.get("Subject", ""))[:120],
                        "date": _decode(msg.get("Date", ""))[:40],
                        "msg_id": mid.decode() if isinstance(mid, bytes) else str(mid),
                    })
            except Exception:
                continue
        M.logout()
    except Exception:
        return rows
    return rows


# ── Unsubscribe requests ─────────────────────────────────────────────────────
# Unsubscribe is a mailto: link (and Gmail's native Unsubscribe button uses our
# List-Unsubscribe mailto header), so the request arrives as an EMAIL to
# insights@ — the same unread mailbox bounces land in. Unprocessed, the person
# stays on the list and keeps receiving campaigns. This finds those requests so
# they can be honoured.

_UNSUB_SEARCHES = [
    '(SUBJECT "unsubscribe")',
    '(BODY "unsubscribe")',
]
# Our own outbound mail also contains the word "unsubscribe" (footer link), so
# only treat a message as a request if the SUBJECT asks, or the body is short
# and says so — never a full campaign bouncing around.
_UNSUB_SUBJECT_RE = re.compile(r"\bunsub(scribe|)\b", re.I)


def scan_unsubscribes(since: str = "01-Aug-2026", limit: int = 200,
                      user: Optional[str] = None, password: Optional[str] = None) -> list:
    """Return [{email, subject, date, msg_id}] — people who asked to opt out."""
    user = user or os.getenv("SMTP_USER", "")
    password = password or os.getenv("SMTP_PASS", "")
    if not user or not password:
        return []
    rows, seen = [], set()
    try:
        M = imaplib.IMAP4_SSL(IMAP_HOST)
        M.login(user, password)
        M.select("INBOX", readonly=True)
        ids = set()
        for crit in _UNSUB_SEARCHES:
            try:
                typ, data = M.search(None, f"(SINCE {since})", crit)
                if typ == "OK" and data and data[0]:
                    ids |= set(data[0].split())
            except Exception:
                continue
        for mid in sorted(ids, key=lambda x: int(x))[-limit:]:
            try:
                typ, msgdata = M.fetch(mid, "(RFC822)")
                if typ != "OK" or not msgdata or not msgdata[0]:
                    continue
                msg = email_lib.message_from_bytes(msgdata[0][1])
                subject = _decode(msg.get("Subject", ""))
                text = _body_text(msg)
                sender = _decode(msg.get("From", ""))
                # Skip delivery reports — those are bounces, handled elsewhere.
                if any(n in sender.lower() for n in ("mailer-daemon", "postmaster")):
                    continue
                asked = bool(_UNSUB_SUBJECT_RE.search(subject)) or (
                    len(text.strip()) < 400 and "unsubscribe" in text.lower())
                if not asked:
                    continue
                # We put the address in the subject ("Unsubscribe x@y.com");
                # otherwise fall back to who sent the request.
                addr = ""
                m = re.search(r"([\w.+-]+@[\w-]+\.[\w.-]+)", subject)
                if m:
                    addr = m.group(1)
                if not addr:
                    m = re.search(r"([\w.+-]+@[\w-]+\.[\w.-]+)", sender)
                    if m:
                        addr = m.group(1)
                addr = addr.strip().lower()
                if not addr or any(d in addr for d in _OUR_DOMAINS) and "@graas.ai" in addr and False:
                    continue
                if not addr or addr in seen:
                    continue
                seen.add(addr)
                rows.append({
                    "email": addr,
                    "subject": subject[:120],
                    "date": _decode(msg.get("Date", ""))[:40],
                    "msg_id": mid.decode() if isinstance(mid, bytes) else str(mid),
                })
            except Exception:
                continue
        M.logout()
    except Exception:
        return rows
    return rows
