"""Persistent meeting notes store — merges Slack-extracted and Granola-exported notes."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

STORE_PATH = Path(__file__).parent.parent / "content" / "meeting_notes.json"


def _load_store() -> List[Dict]:
    if STORE_PATH.exists():
        with open(STORE_PATH) as f:
            return json.load(f)
    return []


def _save_store(notes: List[Dict]):
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STORE_PATH, "w") as f:
        json.dump(notes, f, indent=2, default=str)


def _note_key(note: Dict) -> str:
    """Unique key to prevent duplicates — based on client + date + granola link."""
    return f"{note.get('client', '')}|{note.get('date', '')}|{note.get('granola', '')}"


def get_all_notes() -> List[Dict]:
    """Return all stored notes, sorted by date descending."""
    notes = _load_store()
    notes.sort(key=lambda x: x.get("date_ts", 0), reverse=True)
    return notes


def save_from_slack(slack_notes: List[Dict]) -> int:
    """Merge Slack-extracted notes into the persistent store. Returns count of new notes added."""
    existing = _load_store()
    existing_keys = {_note_key(n) for n in existing}
    added = 0

    for note in slack_notes:
        entry = {
            "client": note.get("client", "Unknown"),
            "date": note.get("date", ""),
            "date_ts": note.get("date_ts", 0),
            "channel": note.get("channel", ""),
            "author": note.get("author", ""),
            "granola": note.get("granola", ""),
            "takeaways": note.get("takeaways", []),
            "summary": note.get("summary", ""),
            "missing_granola": note.get("missing_granola", False),
            "source": "slack",
            "stored_at": datetime.now().isoformat(),
        }
        if _note_key(entry) not in existing_keys:
            existing.append(entry)
            existing_keys.add(_note_key(entry))
            added += 1

    if added:
        _save_store(existing)
    return added


def save_from_granola_export(markdown_text: str, filename: str = "") -> Dict:
    """Parse an exported Granola markdown file and add to the store.

    Granola exports typically have:
    - Title line (meeting name / client)
    - Date and attendees
    - Sections with bullet points (notes, action items, etc.)

    Returns the parsed note dict.
    """
    lines = markdown_text.strip().split("\n")
    if not lines:
        return {}

    # Extract title (first heading or first non-empty line)
    title = ""
    for line in lines:
        stripped = line.strip()
        if stripped:
            title = re.sub(r'^#+\s*', '', stripped)
            break

    # Try to extract date from the text
    date_str = ""
    date_ts = 0
    date_patterns = [
        r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})',
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4})',
        r'(\d{4}-\d{2}-\d{2})',
    ]
    for pattern in date_patterns:
        match = re.search(pattern, markdown_text, re.IGNORECASE)
        if match:
            raw_date = match.group(1)
            for fmt in ["%d %B %Y", "%d %b %Y", "%B %d, %Y", "%B %d %Y",
                        "%b %d, %Y", "%b %d %Y", "%Y-%m-%d"]:
                try:
                    dt = datetime.strptime(raw_date.replace(",", ""), fmt)
                    date_str = dt.strftime("%-d %b")
                    date_ts = dt.timestamp()
                    break
                except ValueError:
                    continue
            if date_str:
                break

    if not date_str:
        date_str = datetime.now().strftime("%-d %b")
        date_ts = datetime.now().timestamp()

    # Extract attendees
    attendees = []
    for line in lines:
        if re.match(r'(?:attendees|participants|people)', line.strip(), re.IGNORECASE):
            # Look at following lines for names
            idx = lines.index(line)
            for subsequent in lines[idx + 1:idx + 15]:
                name = subsequent.strip().lstrip("•-* ")
                if name and len(name) < 60 and not name.startswith("#"):
                    attendees.append(name)
                elif not name:
                    break

    # Extract bullet points as takeaways
    takeaways = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^[•\-\*]\s+', stripped) or re.match(r'^\d+[\.\)]\s+', stripped):
            clean = re.sub(r'^[•\-\*\d\.\)]+\s*', '', stripped).strip()
            if clean and len(clean) > 10 and len(takeaways) < 15:
                takeaways.append(clean)

    # Extract Granola link if present in the text
    granola_links = re.findall(r'https://notes\.granola\.ai/[^\s>|)\]]+', markdown_text)
    granola = granola_links[0] if granola_links else ""

    # Use filename as fallback client name
    client = title
    if not client and filename:
        client = Path(filename).stem.replace("-", " ").replace("_", " ").title()
    if not client:
        client = "Meeting Notes"

    entry = {
        "client": client,
        "date": date_str,
        "date_ts": date_ts,
        "channel": "",
        "author": ", ".join(attendees[:3]) if attendees else "",
        "granola": granola,
        "takeaways": takeaways,
        "full_text": markdown_text,
        "source": "granola_export",
        "stored_at": datetime.now().isoformat(),
    }

    # Save to store
    existing = _load_store()
    existing_keys = {_note_key(n) for n in existing}
    if _note_key(entry) not in existing_keys:
        existing.append(entry)
        _save_store(existing)

    return entry


def delete_note(client: str, date: str, granola: str) -> bool:
    """Remove a specific note from the store."""
    existing = _load_store()
    key = f"{client}|{date}|{granola}"
    filtered = [n for n in existing if _note_key(n) != key]
    if len(filtered) < len(existing):
        _save_store(filtered)
        return True
    return False
