"""Render a Prospect Brief from a structured dict into DOCX (for Drive upload)
or HTML (for inline preview).

Both renderers consume the same `BriefData` shape so the LLM only has to
produce one format (JSON) — and the on-screen preview matches what the
Google Doc will look like.

The DOCX path uses python-docx and sets explicit table column widths,
margins, font sizes, and paragraph spacing — these survive Google Drive's
DOCX → Doc conversion, which is the whole reason we moved off HTML.
"""

from __future__ import annotations

import io
from typing import Any

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


GRAAS_BLUE = RGBColor(0x27, 0x42, 0xFF)
LIGHT_BLUE = "EEF1FF"  # table header fill
GREY = RGBColor(0x66, 0x66, 0x66)
CALLOUT_FILL = "FFF4E5"


# ──────────────────────────────────────────────────────────────────────────────
# DOCX low-level helpers
# ──────────────────────────────────────────────────────────────────────────────

def _set_cell_shading(cell, hex_fill: str) -> None:
    """Apply a background fill colour to a table cell."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def _set_cell_margins(cell, top: int = 40, bottom: int = 40,
                      left: int = 80, right: int = 80) -> None:
    """Tighter cell padding than the DOCX default (units = twentieths of a point)."""
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = OxmlElement("w:tcMar")
    for side, val in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tc_mar.append(node)
    tc_pr.append(tc_mar)


def _add_h1(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    run.font.size = Pt(16)
    run.font.bold = True
    run.font.color.rgb = GRAAS_BLUE


def _add_sub(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(1)
    run = p.add_run(text)
    run.font.size = Pt(8.5)
    run.font.color.rgb = GREY


def _add_status(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(text)
    run.font.size = Pt(9)
    run.font.bold = True
    run.font.color.rgb = GRAAS_BLUE


def _add_h2(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    run.font.size = Pt(11)
    run.font.bold = True
    run.font.color.rgb = GRAAS_BLUE


def _add_h3(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(1)
    run = p.add_run(text)
    run.font.size = Pt(10)
    run.font.bold = True
    run.font.color.rgb = GRAAS_BLUE


def _add_h4(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(1)
    run = p.add_run(text)
    run.font.size = Pt(10)
    run.font.bold = True


def _add_para(doc: Document, text: str, size: float = 10.0, italic: bool = False) -> None:
    if not text:
        return
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.2
    run = p.add_run(text)
    run.font.size = Pt(size)
    if italic:
        run.font.italic = True


def _add_kv_para(doc: Document, label: str, value: str, size: float = 10.0) -> None:
    """A 'Label: value' line where label is bold."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.2
    lbl = p.add_run(f"{label}: ")
    lbl.font.size = Pt(size)
    lbl.font.bold = True
    val = p.add_run(value)
    val.font.size = Pt(size)


def _add_bullets(doc: Document, items: list, size: float = 10.0) -> None:
    for item in items:
        if not item:
            continue
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.line_spacing = 1.2
        run = p.add_run(str(item))
        run.font.size = Pt(size)


def _add_table(
    doc: Document,
    headers: list,
    rows: list,
    col_widths_cm: list,
    header_size: float = 9.5,
    cell_size: float = 9.5,
) -> None:
    """Build a table with explicit column widths and tighter cell padding.

    rows: list[list[str]] — must match len(headers).
    col_widths_cm: list[float] — column widths in cm, must match len(headers).
    """
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.autofit = False
    table.style = "Table Grid"

    # Set widths on every cell of every row (DOCX needs this redundantly)
    for col_idx, w in enumerate(col_widths_cm):
        for row in table.rows:
            row.cells[col_idx].width = Cm(w)

    # Header row
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        _set_cell_shading(cell, LIGHT_BLUE)
        _set_cell_margins(cell)
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(str(h))
        run.font.size = Pt(header_size)
        run.font.bold = True

    # Data rows
    for r_idx, row in enumerate(rows, start=1):
        for c_idx, val in enumerate(row):
            cell = table.rows[r_idx].cells[c_idx]
            cell.text = ""
            _set_cell_margins(cell)
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.15
            run = p.add_run(str(val) if val is not None else "")
            run.font.size = Pt(cell_size)


def _add_callout_box(doc: Document, lines: list) -> None:
    """Single-cell amber-tinted callout box for Conflicts & Unknowns."""
    table = doc.add_table(rows=1, cols=1)
    table.autofit = False
    table.style = "Table Grid"
    cell = table.rows[0].cells[0]
    cell.width = Cm(19.5)
    _set_cell_shading(cell, CALLOUT_FILL)
    _set_cell_margins(cell, top=80, bottom=80, left=120, right=120)
    cell.text = ""
    for i, (label, val) in enumerate(lines):
        if not val:
            continue
        p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(2)
        lbl = p.add_run(f"{label}: ")
        lbl.font.size = Pt(9.5)
        lbl.font.bold = True
        v = p.add_run(str(val))
        v.font.size = Pt(9.5)


# ──────────────────────────────────────────────────────────────────────────────
# Public renderer — DOCX
# ──────────────────────────────────────────────────────────────────────────────

def render_brief_docx(data: dict) -> bytes:
    """Render a brief data dict into DOCX bytes."""
    doc = Document()

    # Page margins — narrow
    for section in doc.sections:
        section.top_margin = Cm(1.2)
        section.bottom_margin = Cm(1.2)
        section.left_margin = Cm(1.4)
        section.right_margin = Cm(1.4)

    # Default font — set on Normal style
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)
    style.paragraph_format.space_before = Pt(0)
    style.paragraph_format.space_after = Pt(2)

    company = data.get("company") or "[Company]"
    header = data.get("header", {}) or {}

    # ── Header / status ───────────────────────────────────────────────────────
    _add_h1(doc, f"Prospect Brief — {company}")
    sub_parts = ["Graas Pre-Sales", "Confidential"]
    if header.get("date_prepared"):
        sub_parts.append(f"Prepared {header['date_prepared']}")
    if header.get("meeting_date"):
        sub_parts.append(f"Meeting {header['meeting_date']}")
    if header.get("market"):
        sub_parts.append(f"Market {header['market']}")
    _add_sub(doc, " · ".join(sub_parts))
    if header.get("status"):
        _add_status(doc, f"Status: {header['status']}")

    # ── Executive Summary ────────────────────────────────────────────────────
    if data.get("executive_summary"):
        _add_h2(doc, "Executive Summary")
        _add_para(doc, data["executive_summary"], size=10)

    # ── Stat band ────────────────────────────────────────────────────────────
    stat_band = data.get("stat_band") or []
    if stat_band:
        headers = [s.get("label", "") for s in stat_band]
        values = [s.get("value", "") for s in stat_band]
        # Distribute 19.5cm of usable width across cells
        n = max(1, len(headers))
        col_w = round(19.5 / n, 2)
        _add_table(doc, headers, [values], [col_w] * n, header_size=9.5, cell_size=9.5)

    # ── Type / Motion ────────────────────────────────────────────────────────
    if data.get("type"):
        _add_kv_para(doc, "Type", data["type"])
    if data.get("motion"):
        _add_kv_para(doc, "Motion", data["motion"])

    # ── What they have ───────────────────────────────────────────────────────
    what = data.get("what_they_have") or []
    if what:
        _add_h2(doc, "What they have")
        rows = [
            [
                r.get("dimension", ""),
                r.get("what_we_know", ""),
                r.get("confidence", ""),
                r.get("source", ""),
            ]
            for r in what
        ]
        _add_table(
            doc,
            headers=["Dimension", "What we know", "Confidence", "Source"],
            rows=rows,
            col_widths_cm=[3.2, 10.8, 2.5, 3.0],
        )

    # ── Recent news ──────────────────────────────────────────────────────────
    recent = data.get("recent_news") or []
    if recent:
        _add_h2(doc, "Recent news (last 12 months)")
        _add_bullets(doc, recent)

    # ── Order flow ───────────────────────────────────────────────────────────
    if data.get("order_flow"):
        _add_h2(doc, "Order flow today")
        _add_para(doc, data["order_flow"])

    # ── What they're missing ─────────────────────────────────────────────────
    missing = data.get("what_missing") or []
    if missing:
        _add_h2(doc, "What they're likely missing")
        _add_bullets(doc, missing)

    # ── Other signals (conditional) ──────────────────────────────────────────
    other = data.get("other_signals") or []
    if other:
        _add_h2(doc, "Other signals")
        _add_bullets(doc, other)

    # ── Product fit & CFO lens ───────────────────────────────────────────────
    _add_h2(doc, "Product fit & CFO lens")
    if data.get("product_route"):
        _add_h3(doc, "Product route")
        _add_para(doc, data["product_route"])

    persona_map = data.get("persona_map") or []
    if persona_map:
        _add_h3(doc, "Persona map")
        rows = [
            [r.get("persona", ""), r.get("count", ""), r.get("surface", "")]
            for r in persona_map
        ]
        _add_table(
            doc,
            headers=["Persona", "Est. count", "Primary surface"],
            rows=rows,
            col_widths_cm=[7.5, 4.5, 7.5],
        )

    pain_map = data.get("pain_capability_cfo") or []
    if pain_map:
        _add_h3(doc, "Pain → Capability → CFO metric")
        rows = [
            [r.get("pain", ""), r.get("capability", ""), r.get("metric", "")]
            for r in pain_map
        ]
        _add_table(
            doc,
            headers=["Pain (their language)", "Product capability", "CFO metric it moves"],
            rows=rows,
            col_widths_cm=[7.0, 7.0, 5.5],
        )

    if data.get("metric_that_matters"):
        _add_h3(doc, "The metric that matters")
        _add_para(doc, data["metric_that_matters"])

    # ── Discovery & next move ────────────────────────────────────────────────
    discovery = data.get("discovery") or {}
    if discovery:
        _add_h2(doc, "Discovery & next move")
        _add_h3(doc, "Double-click in discovery")
        if discovery.get("business_model"):
            _add_h4(doc, "Business model")
            _add_bullets(doc, discovery["business_model"])
        if discovery.get("data_readiness"):
            _add_h4(doc, "Data readiness")
            _add_bullets(doc, discovery["data_readiness"])
        if discovery.get("tech_integration"):
            _add_h4(doc, "Tech stack & integration")
            _add_bullets(doc, discovery["tech_integration"])
        if discovery.get("commercial_authority"):
            _add_h4(doc, "Commercial authority")
            _add_bullets(doc, discovery["commercial_authority"])
        motion_block = discovery.get("motion_specific") or {}
        if motion_block.get("questions"):
            _add_h4(doc, motion_block.get("label") or "Motion-specific")
            _add_bullets(doc, motion_block["questions"])

    # ── Conflicts & unknowns ─────────────────────────────────────────────────
    conflicts = data.get("conflicts_unknowns") or {}
    if any(conflicts.values()) if conflicts else False:
        _add_h3(doc, "Conflicts & unknowns")
        _add_callout_box(doc, [
            ("Conflicting figures", conflicts.get("conflicting", "")),
            ("Unverified, load-bearing", conflicts.get("unverified", "")),
            ("The one fact that would most change the recommendation", conflicts.get("key_fact", "")),
        ])

    # ── Meeting attendees (conditional) ──────────────────────────────────────
    attendees = data.get("meeting_attendees") or []
    if attendees:
        _add_h3(doc, "Meeting attendees")
        rows = [
            [
                a.get("name", ""),
                a.get("title", ""),
                a.get("linkedin_summary", ""),
                a.get("angle", ""),
            ]
            for a in attendees
        ]
        _add_table(
            doc,
            headers=["Name", "Title", "LinkedIn summary", "Likely angle on Graas"],
            rows=rows,
            col_widths_cm=[3.2, 3.2, 8.6, 4.5],
        )

    # ── People & path in ─────────────────────────────────────────────────────
    people = data.get("people_path_in") or []
    if people:
        _add_h3(doc, "People & path in")
        rows = [
            [p.get("name", ""), p.get("role", ""), p.get("why_matter", ""), p.get("type", "")]
            for p in people
        ]
        _add_table(
            doc,
            headers=["Name", "Role", "Why they matter", "Type"],
            rows=rows,
            col_widths_cm=[3.5, 3.5, 9.0, 3.5],
        )
    if data.get("entry_wedge"):
        _add_kv_para(doc, "Entry wedge", data["entry_wedge"])

    # ── Next step ────────────────────────────────────────────────────────────
    next_step = data.get("next_step") or {}
    if next_step:
        _add_h3(doc, "Next step")
        if next_step.get("action"):
            _add_kv_para(doc, "Recommended next move", next_step["action"])
        if next_step.get("why"):
            _add_kv_para(doc, "Why", next_step["why"])
        gate = "Yes" if next_step.get("gate_met") else "No"
        gate_line = f"{gate}"
        if next_step.get("still_open"):
            gate_line += f" — still open: {next_step['still_open']}"
        _add_kv_para(doc, "Ready to solution?", gate_line)

    # ── Opening hook ─────────────────────────────────────────────────────────
    if data.get("opening_hook"):
        _add_h3(doc, "Opening hook")
        _add_para(doc, f"“{data['opening_hook']}”", italic=True)

    # Output bytes
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# Public renderer — HTML (for inline preview only)
# ──────────────────────────────────────────────────────────────────────────────

def _esc(s: Any) -> str:
    import html as _h
    return _h.escape("" if s is None else str(s))


def render_brief_html(data: dict) -> str:
    """Render the same brief data as a tight HTML preview for inline display."""
    company = _esc(data.get("company") or "[Company]")
    header = data.get("header", {}) or {}

    parts: list = []
    parts.append("""<!doctype html><html><head><meta charset='utf-8'><style>
body { font-family: Calibri, Arial, sans-serif; font-size: 10pt; color: #1a1a1a; line-height: 1.25; margin: 0; padding: 0 12px; }
h1 { font-size: 16pt; color: #2742FF; margin: 4pt 0 2pt 0; }
h2 { font-size: 11pt; color: #2742FF; margin: 10pt 0 4pt 0; }
h3 { font-size: 10pt; color: #2742FF; margin: 8pt 0 2pt 0; }
h4 { font-size: 10pt; margin: 4pt 0 1pt 0; }
p { margin: 2pt 0; }
ul { margin: 2pt 0 4pt 0; padding-left: 18pt; }
li { margin: 0; }
.sub { color: #666; font-size: 8.5pt; margin: 0; }
.status { color: #2742FF; font-size: 9pt; font-weight: bold; margin: 2pt 0 6pt 0; }
table { border-collapse: collapse; width: 100%; margin: 3pt 0; }
th, td { border: 1px solid #bbb; padding: 2pt 6pt; text-align: left; vertical-align: top; font-size: 9.5pt; line-height: 1.2; }
th { background: #eef1ff; font-weight: bold; }
.callout td { background: #fff4e5; }
.hook { font-style: italic; }
</style></head><body>""")

    parts.append(f"<h1>Prospect Brief — {company}</h1>")
    sub_parts = ["Graas Pre-Sales", "Confidential"]
    if header.get("date_prepared"):
        sub_parts.append(f"Prepared {_esc(header['date_prepared'])}")
    if header.get("meeting_date"):
        sub_parts.append(f"Meeting {_esc(header['meeting_date'])}")
    if header.get("market"):
        sub_parts.append(f"Market {_esc(header['market'])}")
    parts.append(f"<p class='sub'>{' · '.join(sub_parts)}</p>")
    if header.get("status"):
        parts.append(f"<p class='status'>Status: {_esc(header['status'])}</p>")

    if data.get("executive_summary"):
        parts.append("<h2>Executive Summary</h2>")
        parts.append(f"<p>{_esc(data['executive_summary'])}</p>")

    stat_band = data.get("stat_band") or []
    if stat_band:
        parts.append("<table><tr>")
        for s in stat_band:
            parts.append(f"<th>{_esc(s.get('label'))}</th>")
        parts.append("</tr><tr>")
        for s in stat_band:
            parts.append(f"<td>{_esc(s.get('value'))}</td>")
        parts.append("</tr></table>")

    if data.get("type"):
        parts.append(f"<p><strong>Type:</strong> {_esc(data['type'])}</p>")
    if data.get("motion"):
        parts.append(f"<p><strong>Motion:</strong> {_esc(data['motion'])}</p>")

    what = data.get("what_they_have") or []
    if what:
        parts.append("<h2>What they have</h2><table>")
        parts.append("<tr><th>Dimension</th><th>What we know</th><th>Confidence</th><th>Source</th></tr>")
        for r in what:
            parts.append(
                f"<tr><td>{_esc(r.get('dimension'))}</td>"
                f"<td>{_esc(r.get('what_we_know'))}</td>"
                f"<td>{_esc(r.get('confidence'))}</td>"
                f"<td>{_esc(r.get('source'))}</td></tr>"
            )
        parts.append("</table>")

    if data.get("recent_news"):
        parts.append("<h2>Recent news (last 12 months)</h2><ul>")
        for n in data["recent_news"]:
            parts.append(f"<li>{_esc(n)}</li>")
        parts.append("</ul>")

    if data.get("order_flow"):
        parts.append("<h2>Order flow today</h2>")
        parts.append(f"<p>{_esc(data['order_flow'])}</p>")

    if data.get("what_missing"):
        parts.append("<h2>What they're likely missing</h2><ul>")
        for m in data["what_missing"]:
            parts.append(f"<li>{_esc(m)}</li>")
        parts.append("</ul>")

    if data.get("other_signals"):
        parts.append("<h2>Other signals</h2><ul>")
        for s in data["other_signals"]:
            parts.append(f"<li>{_esc(s)}</li>")
        parts.append("</ul>")

    parts.append("<h2>Product fit &amp; CFO lens</h2>")
    if data.get("product_route"):
        parts.append("<h3>Product route</h3>")
        parts.append(f"<p>{_esc(data['product_route'])}</p>")

    if data.get("persona_map"):
        parts.append("<h3>Persona map</h3><table>")
        parts.append("<tr><th>Persona</th><th>Est. count</th><th>Primary surface</th></tr>")
        for r in data["persona_map"]:
            parts.append(
                f"<tr><td>{_esc(r.get('persona'))}</td>"
                f"<td>{_esc(r.get('count'))}</td>"
                f"<td>{_esc(r.get('surface'))}</td></tr>"
            )
        parts.append("</table>")

    if data.get("pain_capability_cfo"):
        parts.append("<h3>Pain → Capability → CFO metric</h3><table>")
        parts.append("<tr><th>Pain (their language)</th><th>Product capability</th><th>CFO metric it moves</th></tr>")
        for r in data["pain_capability_cfo"]:
            parts.append(
                f"<tr><td>{_esc(r.get('pain'))}</td>"
                f"<td>{_esc(r.get('capability'))}</td>"
                f"<td>{_esc(r.get('metric'))}</td></tr>"
            )
        parts.append("</table>")

    if data.get("metric_that_matters"):
        parts.append("<h3>The metric that matters</h3>")
        parts.append(f"<p>{_esc(data['metric_that_matters'])}</p>")

    discovery = data.get("discovery") or {}
    if discovery:
        parts.append("<h2>Discovery &amp; next move</h2>")
        parts.append("<h3>Double-click in discovery</h3>")
        for key, label in [
            ("business_model", "Business model"),
            ("data_readiness", "Data readiness"),
            ("tech_integration", "Tech stack &amp; integration"),
            ("commercial_authority", "Commercial authority"),
        ]:
            items = discovery.get(key) or []
            if items:
                parts.append(f"<h4>{label}</h4><ul>")
                for q in items:
                    parts.append(f"<li>{_esc(q)}</li>")
                parts.append("</ul>")
        motion_block = discovery.get("motion_specific") or {}
        if motion_block.get("questions"):
            parts.append(f"<h4>{_esc(motion_block.get('label') or 'Motion-specific')}</h4><ul>")
            for q in motion_block["questions"]:
                parts.append(f"<li>{_esc(q)}</li>")
            parts.append("</ul>")

    conflicts = data.get("conflicts_unknowns") or {}
    if any(conflicts.values()) if conflicts else False:
        parts.append("<h3>Conflicts &amp; unknowns</h3>")
        parts.append("<table class='callout'><tr><td>")
        if conflicts.get("conflicting"):
            parts.append(f"<strong>Conflicting figures:</strong> {_esc(conflicts['conflicting'])}<br>")
        if conflicts.get("unverified"):
            parts.append(f"<strong>Unverified, load-bearing:</strong> {_esc(conflicts['unverified'])}<br>")
        if conflicts.get("key_fact"):
            parts.append(f"<strong>The one fact that would most change the recommendation:</strong> {_esc(conflicts['key_fact'])}")
        parts.append("</td></tr></table>")

    if data.get("meeting_attendees"):
        parts.append("<h3>Meeting attendees</h3><table>")
        parts.append("<tr><th>Name</th><th>Title</th><th>LinkedIn summary</th><th>Likely angle on Graas</th></tr>")
        for a in data["meeting_attendees"]:
            parts.append(
                f"<tr><td>{_esc(a.get('name'))}</td>"
                f"<td>{_esc(a.get('title'))}</td>"
                f"<td>{_esc(a.get('linkedin_summary'))}</td>"
                f"<td>{_esc(a.get('angle'))}</td></tr>"
            )
        parts.append("</table>")

    if data.get("people_path_in"):
        parts.append("<h3>People &amp; path in</h3><table>")
        parts.append("<tr><th>Name</th><th>Role</th><th>Why they matter</th><th>Type</th></tr>")
        for p in data["people_path_in"]:
            parts.append(
                f"<tr><td>{_esc(p.get('name'))}</td>"
                f"<td>{_esc(p.get('role'))}</td>"
                f"<td>{_esc(p.get('why_matter'))}</td>"
                f"<td>{_esc(p.get('type'))}</td></tr>"
            )
        parts.append("</table>")

    if data.get("entry_wedge"):
        parts.append(f"<p><strong>Entry wedge:</strong> {_esc(data['entry_wedge'])}</p>")

    next_step = data.get("next_step") or {}
    if next_step:
        parts.append("<h3>Next step</h3>")
        if next_step.get("action"):
            parts.append(f"<p><strong>Recommended next move:</strong> {_esc(next_step['action'])}</p>")
        if next_step.get("why"):
            parts.append(f"<p><strong>Why:</strong> {_esc(next_step['why'])}</p>")
        gate = "Yes" if next_step.get("gate_met") else "No"
        gate_line = gate
        if next_step.get("still_open"):
            gate_line += f" — still open: {_esc(next_step['still_open'])}"
        parts.append(f"<p><strong>Ready to solution?</strong> {gate_line}</p>")

    if data.get("opening_hook"):
        parts.append("<h3>Opening hook</h3>")
        parts.append(f"<p class='hook'>“{_esc(data['opening_hook'])}”</p>")

    parts.append("</body></html>")
    return "".join(parts)
