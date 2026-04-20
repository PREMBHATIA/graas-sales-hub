"""Pull meeting notes (Granola links + takeaways) from Slack GTM channels."""

import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# Channel IDs where Granola notes are shared
GTM_CHANNELS = {
    "C088U5CUXTP": "#ebu-offerings-gtm",
    "C0AKA0J4ZK8": "#my-gtm-alle",
}

# How far back to look (days)
DEFAULT_LOOKBACK_DAYS = 30


def _get_client():
    """Get an authenticated Slack WebClient."""
    from slack_sdk import WebClient

    token = os.getenv("SLACK_BOT_TOKEN", "")
    if not token:
        return None
    return WebClient(token=token)


def _extract_granola_links(text: str) -> List[str]:
    """Extract Granola note URLs from message text."""
    return re.findall(r'https://notes\.granola\.ai/[^\s>|)\]]+', text)


def _extract_client_name(text: str) -> str:
    """Try to extract a client/company name from the first line of a message."""
    # Common patterns: "Orient Bell Call Notes -", "Notes from Dalmia Cement -",
    # "Meeting notes from RSPL group -", "Decathlon / All-e"
    first_line = text.strip().split('\n')[0]

    # Remove granola/google links and Slack link markup <url|text>
    first_line = re.sub(r'<https?://[^>]+>', '', first_line)
    first_line = re.sub(r'https?://[^\s]+', '', first_line).strip()
    # Remove common prefixes (case-insensitive)
    for prefix in ['meeting notes from ', 'notes from ', 'call notes from ',
                   'meeting with ', 'notes - ', 'call notes - ',
                   'meeting notes - ', 'meeting notes with ']:
        if first_line.lower().startswith(prefix):
            first_line = first_line[len(prefix):]
            break
    # Remove "Call Notes" / "Meeting" / "Meeting Notes" suffix
    first_line = re.sub(r'\s+(call\s+notes|meeting\s+notes|meeting)\s*$', '', first_line, flags=re.IGNORECASE)
    # Strip after " - " long descriptions (e.g., "Unicharm meeting in Singapore - they are an existing...")
    if ' - ' in first_line and len(first_line) > 40:
        first_line = first_line.split(' - ')[0].strip()

    # Remove trailing dashes/hyphens/angle brackets
    first_line = first_line.rstrip(' -–—:<>')

    # Truncate if too long
    if len(first_line) > 60:
        first_line = first_line[:60].rsplit(' ', 1)[0] + '…'

    cleaned = first_line.strip()
    # If name is too generic or empty, try second line
    if not cleaned or cleaned.lower() in ('today', 'meeting', 'notes', 'meeting notes'):
        lines = text.strip().split('\n')
        for line in lines[1:4]:
            candidate = re.sub(r'<https?://[^>]+>', '', line)
            candidate = re.sub(r'https?://[^\s]+', '', candidate).strip().rstrip(' -–—:<>')
            if candidate and len(candidate) > 3 and candidate.lower() not in ('today', 'meeting', 'notes'):
                cleaned = candidate
                break
        if not cleaned or cleaned.lower() in ('today', 'meeting', 'notes', 'meeting notes'):
            cleaned = "Meeting Notes"

    return cleaned


def _extract_takeaways(text: str, max_items: int = 8) -> List[str]:
    """Extract top-level bullet-point takeaways from message text."""
    takeaways = []
    lines = text.strip().split('\n')
    for line in lines:
        raw = line
        line = line.strip()
        # Skip sub-bullets (indented with ◦ or 4+ leading spaces)
        if '◦' in raw or (len(raw) > 0 and raw[0] == ' ' and len(raw) - len(raw.lstrip()) >= 4):
            continue
        # Match top-level bullet points: •, -, *, numbered
        if re.match(r'^[•\-\*]\s+', line) or re.match(r'^\d+[\.\)]\s+', line):
            # Clean up the bullet
            clean = re.sub(r'^[•\-\*\d\.\)]+\s*', '', line).strip()
            # Remove Slack user mentions <@U...>
            clean = re.sub(r'<@[A-Z0-9]+(\|[^>]+)?>', lambda m: m.group(1)[1:] if m.group(1) else '', clean)
            if clean and len(clean) > 10:
                takeaways.append(clean)
                if len(takeaways) >= max_items:
                    break
    return takeaways


def fetch_meeting_notes(lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> List[Dict]:
    """
    Fetch recent meeting notes from Slack GTM channels.

    Returns list of dicts with keys:
        client, date, date_ts, channel, author, granola, takeaways
    """
    client = _get_client()
    if client is None:
        return []

    oldest_ts = str(int((datetime.now() - timedelta(days=lookback_days)).timestamp()))
    notes = []

    for ch_id, ch_name in GTM_CHANNELS.items():
        try:
            result = client.conversations_history(
                channel=ch_id,
                oldest=oldest_ts,
                limit=100,
            )
            messages = result.get("messages", [])

            # Also get user info cache
            user_cache = {}

            for msg in messages:
                text = msg.get("text", "")
                granola_links = _extract_granola_links(text)
                if not granola_links:
                    continue

                # Get author name
                user_id = msg.get("user", "")
                if user_id and user_id not in user_cache:
                    try:
                        user_info = client.users_info(user=user_id)
                        profile = user_info["user"]["profile"]
                        user_cache[user_id] = profile.get("real_name", profile.get("display_name", user_id))
                    except Exception:
                        user_cache[user_id] = user_id
                author = user_cache.get(user_id, user_id)

                # Parse timestamp
                ts = float(msg.get("ts", 0))
                dt = datetime.fromtimestamp(ts)
                date_str = dt.strftime("%-d %b")

                # Extract content
                client_name = _extract_client_name(text)
                takeaways = _extract_takeaways(text)

                # Also check thread replies for additional takeaways
                if msg.get("reply_count", 0) > 0:
                    try:
                        thread = client.conversations_replies(
                            channel=ch_id,
                            ts=msg["ts"],
                            limit=10,
                        )
                        remaining = 8 - len(takeaways)
                        for reply in thread.get("messages", [])[1:]:  # skip parent
                            if remaining <= 0:
                                break
                            reply_text = reply.get("text", "")
                            reply_takeaways = _extract_takeaways(reply_text, max_items=remaining)
                            takeaways.extend(reply_takeaways)
                            remaining -= len(reply_takeaways)
                    except Exception:
                        pass
                takeaways = takeaways[:8]

                notes.append({
                    "client": client_name,
                    "date": date_str,
                    "date_ts": ts,
                    "channel": ch_name,
                    "author": author,
                    "granola": granola_links[0],
                    "all_links": granola_links,
                    "takeaways": takeaways,
                })

        except Exception as e:
            # Channel not accessible or other error — skip silently
            continue

    # Sort by date descending
    notes.sort(key=lambda x: x["date_ts"], reverse=True)
    return notes
