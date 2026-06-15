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
    col_styles: dict = None,
) -> None:
    """Build a table with explicit column widths and tighter cell padding.

    rows: list[list[str]] — must match len(headers).
    col_widths_cm: list[float] — column widths in cm, must match len(headers).
    col_styles: optional dict of {col_index: {"size": float, "italic": bool, "color": RGBColor}}
                to override per-column font size / italic / color in DATA cells only.
    """
    col_styles = col_styles or {}
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
            style = col_styles.get(c_idx, {})
            run.font.size = Pt(style.get("size", cell_size))
            if style.get("italic"):
                run.font.italic = True
            if style.get("color"):
                run.font.color.rgb = style["color"]


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
    # Two stacked 3-col tables that look like the stat band — Category/Type/Motion
    # on row 1, Comps/History/Maturity on row 2. Type and Motion live INSIDE the
    # exec summary now (used to be standalone lines below the stat band).
    # Back-compat:
    #   - exec_summary as dict → new boxed layout
    #   - exec_summary as string → old paragraph rendering
    #   - type/motion may live at top level (legacy) or inside exec_summary
    es = data.get("executive_summary")
    top_type = data.get("type") or ""
    top_motion = data.get("motion") or ""
    if isinstance(es, dict) and any(es.values()):
        _add_h2(doc, "Executive Summary")
        # Row 1 — Category | Type | Motion
        es_type = es.get("type") or top_type
        es_motion = es.get("motion") or top_motion
        _add_table(
            doc,
            headers=["Category", "Type", "Motion"],
            rows=[[es.get("category", ""), es_type, es_motion]],
            col_widths_cm=[6.5, 6.5, 6.5],
        )
        # Row 2 — Comps | History | Maturity
        _add_table(
            doc,
            headers=["Comps", "History", "Maturity"],
            rows=[[es.get("comps", ""), es.get("history", ""), es.get("maturity", "")]],
            col_widths_cm=[6.5, 6.5, 6.5],
        )
    elif isinstance(es, str) and es.strip():
        _add_h2(doc, "Executive Summary")
        _add_para(doc, es, size=10)

    # ── Stat band ────────────────────────────────────────────────────────────
    stat_band = data.get("stat_band") or []
    if stat_band:
        headers = [s.get("label", "") for s in stat_band]
        values = [s.get("value", "") for s in stat_band]
        # Distribute 19.5cm of usable width across cells
        n = max(1, len(headers))
        col_w = round(19.5 / n, 2)
        _add_table(doc, headers, [values], [col_w] * n, header_size=9.5, cell_size=9.5)

    # Type / Motion now live INSIDE Executive Summary as boxes — no standalone
    # paragraphs here. Legacy briefs without a structured Exec Summary still get
    # the back-compat string paragraph above, so type/motion are surfaced there
    # via the schema's top-level keys when needed.

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
            # Source column = small, italic, grey — reads as a footnote
            col_styles={3: {"size": 6.5, "italic": True, "color": GREY}},
        )

    # ── Recent news ──────────────────────────────────────────────────────────
    recent = data.get("recent_news") or []
    if recent:
        _add_h2(doc, "Recent news (last 12 months)")
        _add_bullets(doc, recent)

    # ── What they're missing ─────────────────────────────────────────────────
    missing = data.get("what_missing") or []
    if missing:
        _add_h2(doc, "What they're likely missing")
        _add_bullets(doc, missing)

    # ── Product fit & CFO lens ───────────────────────────────────────────────
    _add_h2(doc, "Product fit & CFO lens")
    if data.get("product_route"):
        _add_h3(doc, "Product route")
        _add_para(doc, data["product_route"])

    persona_map = data.get("persona_map") or []
    if persona_map:
        _add_h3(doc, "Persona & order flow")
        # Each persona row = one sales motion: who they sell to, surface, current flow.
        rows = [
            [
                r.get("persona", ""),
                r.get("count", ""),
                r.get("surface", ""),
                r.get("flow_and_leaks", r.get("flow", "")),
            ]
            for r in persona_map
        ]
        _add_table(
            doc,
            headers=["Persona", "Count", "Surface today", "Current flow & leaks"],
            rows=rows,
            col_widths_cm=[3.5, 2.0, 4.0, 10.0],
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

    # ── People & path in (merges old Meeting Attendees) ──────────────────────
    # Each row: Name | Role | Why they matter (+ optional LinkedIn line) | Type
    # Type = Decision-maker | Champion | Finance buyer | Meeting attendee
    # If a row has a "linkedin" field, append it as a 2nd line inside the why-matter
    # cell so attendee context stays visible without a separate section.
    people = list(data.get("people_path_in") or [])
    # Back-compat: fold any legacy meeting_attendees rows in as type='Meeting attendee'
    legacy_attendees = data.get("meeting_attendees") or []
    for a in legacy_attendees:
        people.append({
            "name": a.get("name", ""),
            "role": a.get("title", ""),
            "why_matter": a.get("angle", ""),
            "type": "Meeting attendee",
            "linkedin": a.get("linkedin_summary", ""),
        })

    if people:
        _add_h3(doc, "People & path in")
        rows = []
        for p in people:
            why = p.get("why_matter", "") or ""
            li = (p.get("linkedin") or "").strip()
            if li:
                why = f"{why}\nLinkedIn: {li}" if why else f"LinkedIn: {li}"
            rows.append([p.get("name", ""), p.get("role", ""), why, p.get("type", "")])
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

    # ── Appendix: Conflicts & unknowns (de-emphasised, ends the doc) ─────────
    conflicts = data.get("conflicts_unknowns") or {}
    if conflicts and any(conflicts.values()):
        _add_h3(doc, "Appendix: Conflicts & unknowns")
        _add_callout_box(doc, [
            ("Conflicting figures", conflicts.get("conflicting", "")),
            ("Unverified, load-bearing", conflicts.get("unverified", "")),
            ("Fact that would most change the recommendation", conflicts.get("key_fact", "")),
        ])

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
td.src { font-size: 7pt; font-style: italic; color: #777; }
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

    _es = data.get("executive_summary")
    _top_type = _esc(data.get("type") or "")
    _top_motion = _esc(data.get("motion") or "")
    if isinstance(_es, dict) and any(_es.values()):
        parts.append("<h2>Executive Summary</h2>")
        _es_type = _esc(_es.get("type") or "") or _top_type
        _es_motion = _esc(_es.get("motion") or "") or _top_motion
        # Row 1 — Category | Type | Motion (stat-band style)
        parts.append("<table><tr>")
        parts.append("<th>Category</th><th>Type</th><th>Motion</th>")
        parts.append("</tr><tr>")
        parts.append(f"<td>{_esc(_es.get('category', ''))}</td>"
                     f"<td>{_es_type}</td>"
                     f"<td>{_es_motion}</td>")
        parts.append("</tr></table>")
        # Row 2 — Comps | History | Maturity
        parts.append("<table><tr>")
        parts.append("<th>Comps</th><th>History</th><th>Maturity</th>")
        parts.append("</tr><tr>")
        parts.append(f"<td>{_esc(_es.get('comps', ''))}</td>"
                     f"<td>{_esc(_es.get('history', ''))}</td>"
                     f"<td>{_esc(_es.get('maturity', ''))}</td>")
        parts.append("</tr></table>")
    elif isinstance(_es, str) and _es.strip():
        parts.append("<h2>Executive Summary</h2>")
        parts.append(f"<p>{_esc(_es)}</p>")

    stat_band = data.get("stat_band") or []
    if stat_band:
        parts.append("<table><tr>")
        for s in stat_band:
            parts.append(f"<th>{_esc(s.get('label'))}</th>")
        parts.append("</tr><tr>")
        for s in stat_band:
            parts.append(f"<td>{_esc(s.get('value'))}</td>")
        parts.append("</tr></table>")

    # Type / Motion now live inside Executive Summary boxes — no standalone lines.

    what = data.get("what_they_have") or []
    if what:
        parts.append("<h2>What they have</h2><table>")
        parts.append("<tr><th>Dimension</th><th>What we know</th><th>Confidence</th><th>Source</th></tr>")
        for r in what:
            parts.append(
                f"<tr><td>{_esc(r.get('dimension'))}</td>"
                f"<td>{_esc(r.get('what_we_know'))}</td>"
                f"<td>{_esc(r.get('confidence'))}</td>"
                f"<td class='src'>{_esc(r.get('source'))}</td></tr>"
            )
        parts.append("</table>")

    if data.get("recent_news"):
        parts.append("<h2>Recent news (last 12 months)</h2><ul>")
        for n in data["recent_news"]:
            parts.append(f"<li>{_esc(n)}</li>")
        parts.append("</ul>")

    if data.get("what_missing"):
        parts.append("<h2>What they're likely missing</h2><ul>")
        for m in data["what_missing"]:
            parts.append(f"<li>{_esc(m)}</li>")
        parts.append("</ul>")

    parts.append("<h2>Product fit &amp; CFO lens</h2>")
    if data.get("product_route"):
        parts.append("<h3>Product route</h3>")
        parts.append(f"<p>{_esc(data['product_route'])}</p>")

    if data.get("persona_map"):
        parts.append("<h3>Persona &amp; order flow</h3><table>")
        parts.append("<tr><th>Persona</th><th>Count</th><th>Surface today</th><th>Current flow &amp; leaks</th></tr>")
        for r in data["persona_map"]:
            flow = r.get("flow_and_leaks", r.get("flow", ""))
            parts.append(
                f"<tr><td>{_esc(r.get('persona'))}</td>"
                f"<td>{_esc(r.get('count'))}</td>"
                f"<td>{_esc(r.get('surface'))}</td>"
                f"<td>{_esc(flow)}</td></tr>"
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

    # People & path in (merges legacy meeting_attendees)
    _people = list(data.get("people_path_in") or [])
    for a in (data.get("meeting_attendees") or []):
        _people.append({
            "name": a.get("name", ""),
            "role": a.get("title", ""),
            "why_matter": a.get("angle", ""),
            "type": "Meeting attendee",
            "linkedin": a.get("linkedin_summary", ""),
        })
    if _people:
        parts.append("<h3>People &amp; path in</h3><table>")
        parts.append("<tr><th>Name</th><th>Role</th><th>Why they matter</th><th>Type</th></tr>")
        for p in _people:
            why = p.get("why_matter", "") or ""
            li = (p.get("linkedin") or "").strip()
            if li:
                why = f"{why}<br><em>LinkedIn:</em> {_esc(li)}" if why else f"<em>LinkedIn:</em> {_esc(li)}"
            else:
                why = _esc(why)
            parts.append(
                f"<tr><td>{_esc(p.get('name'))}</td>"
                f"<td>{_esc(p.get('role'))}</td>"
                f"<td>{why}</td>"
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

    # Appendix: Conflicts & unknowns (end of brief, de-emphasised)
    conflicts = data.get("conflicts_unknowns") or {}
    if conflicts and any(conflicts.values()):
        parts.append("<h3>Appendix: Conflicts &amp; unknowns</h3>")
        parts.append("<table class='callout'><tr><td>")
        if conflicts.get("conflicting"):
            parts.append(f"<strong>Conflicting figures:</strong> {_esc(conflicts['conflicting'])}<br>")
        if conflicts.get("unverified"):
            parts.append(f"<strong>Unverified, load-bearing:</strong> {_esc(conflicts['unverified'])}<br>")
        if conflicts.get("key_fact"):
            parts.append(f"<strong>Fact that would most change the recommendation:</strong> {_esc(conflicts['key_fact'])}")
        parts.append("</td></tr></table>")

    parts.append("</body></html>")
    return "".join(parts)
