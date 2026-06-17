"""KB conflict scanner — finds contradictions / drift / stale features / overlaps
across all KB Docs and produces a Findings Report Doc.

Triggered manually from the Resources page's "KB Health" panel, or on a schedule.

Flow:
    1. gather_kb_corpus(kb_root_id) → walks KB, fetches text of every Google
       Doc and Google Slides file at root + every subfolder one level deep
    2. scan_for_conflicts(corpus, anthropic_client) → bundles corpus into one
       prompt, asks Claude for structured JSON of findings
    3. format_findings_report_html(findings, corpus_summary, scan_date) →
       turns findings into a readable Doc
    4. save_findings_to_drive(html, kb_root_id) → creates Doc in KB/_Reviews/
       (subfolder auto-created if missing)

Doc text fetch is capped per-doc to keep total prompt size reasonable.
"""

from __future__ import annotations

import json as _json
import re
from datetime import datetime
from typing import Optional

from services.sheets_client import (
    list_drive_subfolders,
    list_drive_folder_all_files,
    fetch_drive_doc_text,
    create_google_doc_from_html,
    ensure_subfolder_exists,
)

REVIEWS_SUBFOLDER_NAME = "_Reviews"
PER_DOC_CHAR_CAP = 25_000   # trim each Doc to keep corpus prompt manageable
SCANNABLE_MIMES = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.presentation",
}


# ──────────────────────────────────────────────────────────────────────────────
# 1. Gather corpus
# ──────────────────────────────────────────────────────────────────────────────

def gather_kb_corpus(kb_root_id: str) -> list:
    """Walk KB root + one level of subfolders; return list of scannable Docs.

    Each entry: {doc_id, name, bucket_path, mime, text, truncated: bool}.
    bucket_path = "1. eCom" or "3. Graas Products / All-e" — for the report
    so the user can locate the source. Skips raw HTML / PDF / other binary
    files (not text-extractable via Drive export).
    """
    corpus: list = []
    # Files directly under KB root (rare but possible — e.g. an Index Doc)
    for f in list_drive_folder_all_files(kb_root_id):
        if f["mime_type"] in SCANNABLE_MIMES:
            corpus.append(_make_corpus_entry(f, bucket_path=""))

    # One level of subfolders
    for bucket in list_drive_subfolders(kb_root_id):
        # Skip the _Reviews/ folder itself — we don't want to scan the
        # scan reports against the corpus
        if bucket["name"].strip() == REVIEWS_SUBFOLDER_NAME:
            continue
        bucket_label = bucket["name"]
        # Bucket-level files
        for f in list_drive_folder_all_files(bucket["id"]):
            if f["mime_type"] in SCANNABLE_MIMES:
                corpus.append(_make_corpus_entry(f, bucket_path=bucket_label))
        # Sub-subfolders
        for sub in list_drive_subfolders(bucket["id"]):
            sub_label = f"{bucket_label} / {sub['name']}"
            for f in list_drive_folder_all_files(sub["id"]):
                if f["mime_type"] in SCANNABLE_MIMES:
                    corpus.append(_make_corpus_entry(f, bucket_path=sub_label))

    return corpus


def _make_corpus_entry(f: dict, bucket_path: str) -> dict:
    """Fetch the doc text and truncate if needed."""
    text = fetch_drive_doc_text(f["id"]) or ""
    truncated = len(text) > PER_DOC_CHAR_CAP
    if truncated:
        text = text[:PER_DOC_CHAR_CAP] + "\n\n[... truncated for scan ...]"
    return {
        "doc_id": f["id"],
        "name": f["name"],
        "bucket_path": bucket_path,
        "mime": f["mime_type"],
        "text": text,
        "truncated": truncated,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 2. Scan for conflicts
# ──────────────────────────────────────────────────────────────────────────────

FINDINGS_SCHEMA = """{
  "scan_date": "YYYY-MM-DD",
  "corpus_size": {"docs": N, "buckets": N},
  "summary": "1-paragraph overall health assessment — is the KB consistent? Are there themes (e.g. 'product positioning drift across 3 Docs')?",
  "findings": [
    {
      "id": "f1",
      "category": "CONFLICT | DRIFT | STALE | OVERLAP",
      "severity": "high | medium | low",
      "title": "Short headline — what's wrong",
      "docs_involved": [
        {"name": "Doc A title", "bucket_path": "where it lives", "claim": "the specific claim from this Doc"},
        {"name": "Doc B title", "bucket_path": "...", "claim": "the conflicting claim"}
      ],
      "description": "1-2 sentence explanation of WHY this is a problem and what the impact is",
      "recommended_action": "specific action — e.g. 'Update Hoppr KB to reflect Q3 forecasting feature; remove the \\\"not a forecasting platform\\\" disclaimer'"
    }
  ]
}"""

SCAN_SYSTEM_PROMPT = """You are auditing a corporate knowledge base for internal consistency. The team adds Docs over time; some Docs supersede others, some drift, some flat-out contradict.

Your job: identify ONLY genuine, load-bearing inconsistencies. Be precise. Don't flag minor wording variations or stylistic differences — only things a reader would act on differently depending on which Doc they read.

Four categories of findings:

1. **CONFLICT** — Doc A says X, Doc B says NOT X. Direct factual contradiction. Highest priority.
2. **DRIFT** — Doc A describes a state ("we will" / "not yet") that Doc B describes as different ("we now do" / "shipped"). Usually means Doc A is stale.
3. **STALE** — Doc A describes a feature, decision, or claim that no longer matches the current product/strategy reality (often a Doc explicitly flagged as "v1" or "early version" where a newer one exists).
4. **OVERLAP** — Two Docs cover the same ground and have started to diverge in wording or detail; one should consolidate or one should reference the other.

Output rules:
- Maximum 15 findings per scan. Prioritise by severity.
- Each finding MUST cite specific Doc names + the specific claim from each Doc.
- Recommended action must be concrete (which Doc to update, what specifically to change).
- If the KB looks clean, return an empty findings array with a summary saying so.

Return ONLY a single JSON object matching the schema. No prose, no markdown fences."""


def scan_for_conflicts(corpus: list, anthropic_client, model: str = "claude-sonnet-4-6") -> dict:
    """Bundle the corpus into one prompt, call Claude, parse JSON findings."""
    if not corpus:
        return {
            "scan_date": datetime.now().strftime("%Y-%m-%d"),
            "corpus_size": {"docs": 0, "buckets": 0},
            "summary": "Empty KB — nothing to scan.",
            "findings": [],
        }

    buckets_seen = set(d.get("bucket_path", "") or "(root)" for d in corpus)
    today = datetime.now().strftime("%Y-%m-%d")

    # Build the user prompt — full corpus, one section per Doc with location header
    corpus_blob = ""
    for d in corpus:
        corpus_blob += (
            f"\n\n=== DOC: {d['name']} ===\n"
            f"Location: {d['bucket_path'] or '(KB root)'}\n"
            f"---\n{d['text']}\n=== END DOC: {d['name']} ===\n"
        )

    user_msg = (
        f"Today is {today}. The KB has {len(corpus)} Doc(s) across {len(buckets_seen)} location(s).\n\n"
        f"Scan the Docs below for conflicts, drift, stale content, and significant overlap. "
        f"Return a JSON object matching this schema:\n\n{FINDINGS_SCHEMA}\n\n"
        f"=== KB CORPUS ==={corpus_blob}"
    )

    resp = anthropic_client.messages.create(
        model=model,
        max_tokens=4000,
        system=SCAN_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```(?:json|JSON)?\s*\n", "", raw)
    raw = re.sub(r"\n```\s*$", "", raw)
    raw = raw.strip()
    start = raw.find("{")
    if start < 0:
        raise ValueError(f"No JSON in response. First 500 chars:\n{raw[:500]}")
    try:
        parsed = _json.loads(raw[start:])
    except _json.JSONDecodeError:
        # Balanced-brace fallback
        depth = 0
        in_str = False
        esc = False
        end_idx = None
        for i in range(start, len(raw)):
            c = raw[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break
        if end_idx is None:
            raise ValueError(f"Couldn't balance JSON. First 500 chars:\n{raw[:500]}")
        parsed = _json.loads(raw[start:end_idx])

    # Ensure required fields
    parsed.setdefault("scan_date", today)
    parsed.setdefault("corpus_size", {"docs": len(corpus), "buckets": len(buckets_seen)})
    parsed.setdefault("findings", [])
    parsed.setdefault("summary", "")
    return parsed


# ──────────────────────────────────────────────────────────────────────────────
# 3. Render findings as HTML report
# ──────────────────────────────────────────────────────────────────────────────

REPORT_CSS = """<style>
  body { font-family: Calibri, Arial, sans-serif; font-size: 11pt; line-height: 1.4; color: #1a1a1a; }
  h1 { font-size: 20pt; color: #2742FF; margin-bottom: 4pt; }
  h2 { font-size: 14pt; color: #2742FF; margin-top: 18pt; border-bottom: 1px solid #d6d9ee; padding-bottom: 2pt; }
  h3 { font-size: 12pt; margin-top: 10pt; }
  .sub { color: #666; font-size: 9.5pt; margin: 2pt 0 8pt 0; }
  blockquote { border-left: 3px solid #2742FF; padding: 4pt 12pt; background: #f6f8ff; margin: 8pt 0; }
  table { border-collapse: collapse; width: 100%; margin: 6pt 0; }
  th, td { border: 1px solid #bbb; padding: 4pt 7pt; text-align: left; vertical-align: top; font-size: 10pt; line-height: 1.3; }
  th { background: #eef1ff; font-weight: bold; }
  .finding { border: 1px solid #ddd; border-left: 4px solid #2742FF; padding: 10pt 14pt; margin: 12pt 0; background: #fafbff; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 9pt; font-weight: bold; margin-right: 6px; }
  .b-conflict { background: #fbe9e6; color: #8B1A0E; }
  .b-drift { background: #fef6e0; color: #8B6B0E; }
  .b-stale { background: #f0e6fa; color: #5B2E8C; }
  .b-overlap { background: #e7f5ec; color: #1A6B3A; }
  .b-high { background: #fbe9e6; color: #8B1A0E; }
  .b-medium { background: #fef6e0; color: #8B6B0E; }
  .b-low { background: #eef1ff; color: #2742FF; }
  .claim { font-style: italic; color: #444; margin: 2pt 0 4pt 16pt; }
</style>"""


def _badge(category_or_severity: str, value: str) -> str:
    cls = f"b-{value.lower()}"
    return f'<span class="badge {cls}">{value.upper()}</span>'


def format_findings_report_html(findings_data: dict) -> str:
    fd = findings_data
    findings = fd.get("findings", []) or []
    parts: list = [f"<!doctype html><html><head><meta charset='utf-8'>{REPORT_CSS}</head><body>"]
    parts.append(f"<h1>KB Health Scan — {fd.get('scan_date', '')}</h1>")
    cs = fd.get("corpus_size", {}) or {}
    parts.append(
        f"<p class='sub'>Scanned <strong>{cs.get('docs', '?')}</strong> Doc(s) across "
        f"<strong>{cs.get('buckets', '?')}</strong> location(s). "
        f"<strong>{len(findings)}</strong> finding(s).</p>"
    )

    if fd.get("summary"):
        parts.append("<h2>Overall</h2>")
        parts.append(f"<blockquote>{_esc(fd['summary'])}</blockquote>")

    if not findings:
        parts.append("<p><em>No conflicts, drift, or stale content detected. The KB looks consistent — re-scan next month.</em></p>")
        parts.append("</body></html>")
        return "".join(parts)

    parts.append("<h2>Findings</h2>")
    for i, f in enumerate(findings, 1):
        cat = f.get("category", "OVERLAP")
        sev = f.get("severity", "medium")
        parts.append('<div class="finding">')
        parts.append(
            f"<div>{_badge('cat', cat)}{_badge('sev', sev)}"
            f"<strong style='font-size: 11.5pt;'>{i}. {_esc(f.get('title', '(untitled)'))}</strong></div>"
        )
        parts.append(f"<p style='margin: 6pt 0;'>{_esc(f.get('description', ''))}</p>")
        di = f.get("docs_involved", []) or []
        if di:
            parts.append("<div style='font-size: 10pt;'><strong>Docs involved:</strong></div>")
            for d in di:
                parts.append(
                    f"<div style='font-size: 10pt; margin-left: 12pt;'>"
                    f"📄 <strong>{_esc(d.get('name', ''))}</strong>"
                    f" <span style='color: #888;'>({_esc(d.get('bucket_path', ''))})</span>"
                    f"</div>"
                    f"<div class='claim'>"
                    f"{_esc(d.get('claim', ''))}</div>"
                )
        if f.get("recommended_action"):
            parts.append(
                f"<div style='margin-top: 6pt; padding: 6pt 10pt; background: #eef1ff; "
                f"border-radius: 4px; font-size: 10pt;'>"
                f"<strong>Recommended action:</strong> {_esc(f['recommended_action'])}"
                f"</div>"
            )
        parts.append("</div>")

    parts.append(
        "<p class='sub' style='margin-top: 24pt;'>This report is generated by the KB Health Scanner. "
        "Walk each finding, update the underlying Doc(s) accordingly, and run a fresh scan to confirm. "
        "Old reports are kept in the _Reviews/ subfolder for audit history.</p>"
    )
    parts.append("</body></html>")
    return "".join(parts)


def _esc(s) -> str:
    import html as _h
    return _h.escape("" if s is None else str(s))


# ──────────────────────────────────────────────────────────────────────────────
# 4. Save to Drive
# ──────────────────────────────────────────────────────────────────────────────

def save_findings_to_drive(html: str, kb_root_id: str, scan_date: str,
                           share_with: Optional[list] = None) -> dict:
    """Create the Findings Doc inside KB/_Reviews/ — creates the subfolder
    if it doesn't exist yet."""
    reviews_id = ensure_subfolder_exists(kb_root_id, REVIEWS_SUBFOLDER_NAME)
    if not reviews_id:
        return {"ok": False, "error": "Couldn't find or create _Reviews/ subfolder"}
    title = f"KB Health Scan — {scan_date}"
    return create_google_doc_from_html(
        html_body=html,
        title=title,
        parent_folder_id=reviews_id,
        share_with=share_with or ["prem@graas.ai", "amruta@graas.ai"],
    )


def latest_scan_report(kb_root_id: str) -> Optional[dict]:
    """Return the most recent KB Health Scan report from _Reviews/, or None."""
    reviews_id = None
    for sub in list_drive_subfolders(kb_root_id):
        if sub.get("name", "").strip() == REVIEWS_SUBFOLDER_NAME:
            reviews_id = sub["id"]
            break
    if not reviews_id:
        return None
    files = list_drive_folder_all_files(reviews_id)
    scans = [f for f in files if f["name"].startswith("KB Health Scan")]
    if not scans:
        return None
    # Already sorted modifiedTime desc by list_drive_folder_all_files
    return scans[0]


# ──────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────────────

def run_scan(kb_root_id: str, anthropic_api_key: str,
             share_with: Optional[list] = None) -> dict:
    """End-to-end scan. Returns {ok, findings_doc_url, n_findings, error}."""
    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    corpus = gather_kb_corpus(kb_root_id)
    if not corpus:
        return {"ok": False, "error": "No scannable Docs found in KB"}
    findings = scan_for_conflicts(corpus, client)
    html = format_findings_report_html(findings)
    res = save_findings_to_drive(html, kb_root_id, findings.get("scan_date"), share_with)
    return {
        "ok": res.get("ok", False),
        "findings_doc_url": res.get("doc_url"),
        "n_findings": len(findings.get("findings", [])),
        "corpus_size": findings.get("corpus_size"),
        "error": res.get("error"),
    }
