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
YELLOW = "FFF4B8"  # post-call highlight — rows changed by the latest call
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
    highlighted_rows: set = None,
) -> None:
    """Build a table with explicit column widths and tighter cell padding.

    rows: list[list[str]] — must match len(headers).
    col_widths_cm: list[float] — column widths in cm, must match len(headers).
    col_styles: optional dict of {col_index: {"size": float, "italic": bool, "color": RGBColor}}
                to override per-column font size / italic / color in DATA cells only.
    highlighted_rows: optional set of 0-based row indices to paint with YELLOW
                fill (post-call change-highlight — surfaces which rows the
                latest call updated/added).
    """
    highlighted_rows = highlighted_rows or set()
    col_styles = col_styles or {}
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.autofit = False
    table.style = "Table Grid"

    # Force fixed table layout — without this OOXML flag, Word and Google Docs
    # auto-fit columns based on cell content length, ignoring our cm widths.
    # Long-content cells then squish other columns, producing "scrambled"
    # tables. With type="fixed", widths are respected.
    tbl_pr = table._tbl.tblPr
    layout_el = OxmlElement("w:tblLayout")
    layout_el.set(qn("w:type"), "fixed")
    tbl_pr.append(layout_el)
    tbl_w = OxmlElement("w:tblW")
    tbl_w.set(qn("w:w"), str(int(sum(col_widths_cm) * 567)))  # 567 twips ≈ 1cm
    tbl_w.set(qn("w:type"), "dxa")
    tbl_pr.append(tbl_w)

    # Override <w:tblGrid> with our actual column widths in twips. python-docx
    # populates this with equal page-width-divided-by-col-count regardless of
    # what we set on individual cells — and Google Docs uses tblGrid (not tcW)
    # when laying out tables, so the rendered widths come out wrong without
    # this. This is what was making Exec Summary (3-col) render narrower than
    # the stat band (5-col) even though both tblW values were the same.
    _grid = table._tbl.find(qn("w:tblGrid"))
    if _grid is not None:
        for _child in list(_grid):
            _grid.remove(_child)
        for _w in col_widths_cm:
            _gc = OxmlElement("w:gridCol")
            _gc.set(qn("w:w"), str(int(_w * 567)))
            _grid.append(_gc)

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
        # 0-based data-row index for highlight check (r_idx is table-row index
        # which counts the header at 0)
        data_idx = r_idx - 1
        is_highlighted = data_idx in highlighted_rows
        for c_idx, val in enumerate(row):
            cell = table.rows[r_idx].cells[c_idx]
            cell.text = ""
            if is_highlighted:
                _set_cell_shading(cell, YELLOW)
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

    # Tiny trailing spacer paragraph — without this, Word and Google Docs
    # visually merge consecutive <w:tbl> blocks into one continuous table
    # with no border break (Exec Summary rows fused with the stat band).
    # A 4pt-font empty paragraph forces a clean disconnect between tables
    # without adding noticeable vertical space.
    _spacer = doc.add_paragraph()
    _spacer.paragraph_format.space_before = Pt(0)
    _spacer.paragraph_format.space_after = Pt(0)
    _spacer_run = _spacer.add_run("")
    _spacer_run.font.size = Pt(4)


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

    # Post-call highlight map: {table_name: set(row_indices_changed)}. Empty
    # in pre-call drafts (no highlighting). Each table's _add_table call
    # passes its key's set through highlighted_rows.
    _cr = data.get("_changed_rows") or {}
    _ch = lambda key: set(_cr.get(key, []) or [])
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

    # ── Timeline (deal-pace anchor) ─────────────────────────────────────────
    # Weaves CRM dates (first_conv + last_conv from the pipeline sheet) with
    # post_call_log dates and today. Gives the salesperson temporal context:
    # how long the deal's been running, days-since-last-touch, the cadence
    # of the discovery cycle. All dates are known facts — no LLM involvement.
    _tl = data.get("_timeline_meta") or {}
    _first = (_tl.get("first_conv") or "").strip()
    _last = (_tl.get("latest_conv") or "").strip()
    _today = (_tl.get("today") or "").strip()
    _pcl_for_tl = data.get("post_call_log") or []
    if _first or _last or _pcl_for_tl:
        from datetime import date as _date
        def _days_since(d_str):
            try:
                y, m, d = d_str.split("-")
                return (_date.today() - _date(int(y), int(m), int(d))).days
            except Exception:
                return None
        _parts = []
        if _first:
            _ds = _days_since(_first)
            _parts.append(f"First conv {_first}" + (f" ({_ds}d ago)" if _ds is not None else ""))
        if _last and _last != _first:
            _ds = _days_since(_last)
            _parts.append(f"Last conv {_last}" + (f" ({_ds}d ago)" if _ds is not None else ""))
        # Add post-call entries — earliest first for chronological flow
        for entry in reversed(_pcl_for_tl):
            cn = entry.get("call_number") or "?"
            dt = entry.get("date") or ""
            if dt:
                _ds = _days_since(dt)
                tag = " (today)" if _ds == 0 else (f" ({_ds}d ago)" if _ds is not None else "")
                _parts.append(f"Call {cn} {dt}{tag}")
        if _parts:
            _tl_p = doc.add_paragraph()
            _tl_run_label = _tl_p.add_run("Timeline: ")
            _tl_run_label.font.size = Pt(8.5)
            _tl_run_label.font.bold = True
            _tl_run_label.font.color.rgb = GREY
            _tl_run_body = _tl_p.add_run(" · ".join(_parts))
            _tl_run_body.font.size = Pt(8.5)
            _tl_run_body.font.color.rgb = GREY
            _tl_p.paragraph_format.space_before = Pt(0)
            _tl_p.paragraph_format.space_after = Pt(4)

    # ── Post-call analysis (only present after first post-call update) ──────
    # Most recent entry first. Each entry summarises what THAT call added.
    # Salesperson re-opening the brief reads this section first to see what
    # changed without diffing against a prior Doc revision.
    post_call_log = data.get("post_call_log") or []
    if post_call_log:
        # Legend so anyone opening the Doc knows what the yellow shading means
        _legend_p = doc.add_paragraph()
        _legend_run = _legend_p.add_run(
            "▮ Yellow highlights = sections updated in the latest call"
        )
        _legend_run.font.size = Pt(8.5)
        _legend_run.font.italic = True
        _legend_run.font.color.rgb = GREY
        _legend_p.paragraph_format.space_before = Pt(0)
        _legend_p.paragraph_format.space_after = Pt(4)

        _add_h2(doc, "Post-call analysis")
        for idx, entry in enumerate(post_call_log):
            tag = "  (latest)" if idx == 0 else "  (prior)"
            cn = entry.get("call_number") or (idx + 1)
            dt = entry.get("date") or ""
            _add_h3(doc, f"Call {cn} — {dt}{tag}")
            if entry.get("what_we_learned"):
                _add_kv_para(doc, "What we learned", entry["what_we_learned"])
            if entry.get("now_confirmed"):
                _add_kv_para(doc, "Now confirmed", "")
                _add_bullets(doc, entry["now_confirmed"])
            if entry.get("newly_surfaced"):
                _add_kv_para(doc, "Newly surfaced", "")
                _add_bullets(doc, entry["newly_surfaced"])
            if entry.get("still_open"):
                _add_kv_para(doc, "Still open", "")
                _add_bullets(doc, entry["still_open"])
            if entry.get("route_or_next_step_change"):
                _add_kv_para(doc, "Route / next step change",
                             entry["route_or_next_step_change"])

        # Clear divider so it's obvious where post-call notes end and the
        # standing brief begins. A paragraph with a thick bottom border
        # renders as a hard horizontal rule in both Word and Google Docs.
        _div_p = doc.add_paragraph()
        _div_pPr = _div_p._p.get_or_add_pPr()
        _pBdr = OxmlElement("w:pBdr")
        _bottom = OxmlElement("w:bottom")
        _bottom.set(qn("w:val"), "single")
        _bottom.set(qn("w:sz"), "12")  # thickness
        _bottom.set(qn("w:space"), "1")
        _bottom.set(qn("w:color"), "2742FF")  # Graas blue
        _pBdr.append(_bottom)
        _div_pPr.append(_pBdr)
        _div_p.paragraph_format.space_before = Pt(2)
        _div_p.paragraph_format.space_after = Pt(8)
        _div_label = doc.add_paragraph()
        _div_label_run = _div_label.add_run("— end of post-call notes · standing brief follows —")
        _div_label_run.font.size = Pt(8)
        _div_label_run.font.italic = True
        _div_label_run.font.color.rgb = GREY
        _div_label.paragraph_format.space_before = Pt(0)
        _div_label.paragraph_format.space_after = Pt(8)
        _div_label.paragraph_format.alignment = 1  # CENTER

    # ══════════════════════════════════════════════════════════════════════
    # MAIN BRIEF — what the salesperson reads to run the meeting
    # ══════════════════════════════════════════════════════════════════════

    # ── Strategic hook (sets the meeting frame, one line) ───────────────────
    if data.get("strategic_hook"):
        _add_para(doc, f"“{data['strategic_hook']}”", italic=True, size=10.5)

    # ── Executive Summary ────────────────────────────────────────────────────
    es = data.get("executive_summary")
    top_type = data.get("type") or ""
    top_motion = data.get("motion") or ""
    if isinstance(es, dict) and any(es.values()):
        _add_h2(doc, "Executive Summary")
        es_type = es.get("type") or top_type
        es_motion = es.get("motion") or top_motion
        _add_table(
            doc,
            headers=["Category", "Type", "Motion"],
            rows=[[es.get("category", ""), es_type, es_motion]],
            col_widths_cm=[6.0, 6.0, 6.0],
        )
        _add_table(
            doc,
            headers=["Comps", "History", "Maturity"],
            rows=[[es.get("comps", ""), es.get("history", ""), es.get("maturity", "")]],
            col_widths_cm=[6.0, 6.0, 6.0],
        )
    elif isinstance(es, str) and es.strip():
        _add_h2(doc, "Executive Summary")
        _add_para(doc, es, size=10)

    # ── Stat band ────────────────────────────────────────────────────────────
    stat_band = data.get("stat_band") or []
    if stat_band:
        headers = [s.get("label", "") for s in stat_band]
        values = [s.get("value", "") for s in stat_band]
        n = max(1, len(headers))
        col_w = round(18.0 / n, 2)
        _add_table(doc, headers, [values], [col_w] * n, header_size=9.5, cell_size=9.5)

    # ── Why now (2 bullets, capped) ─────────────────────────────────────────
    why_now = data.get("why_now") or []
    if why_now:
        _add_h3(doc, "Why now")
        _add_bullets(doc, why_now[:2])  # cap at 2 in render too

    # ── Meeting game plan (3 bullets — open / pitch / close) ────────────────
    # Defensively accept both shapes Claude might return:
    #   • list[str] — preferred ("3-bullet meeting plan, not a 6-row table")
    #   • list[dict{minute,segment,talking_point}] — legacy shape from earlier prompt
    game_plan = data.get("meeting_game_plan") or []
    if game_plan:
        _add_h3(doc, "Meeting game plan")
        bullets = []
        for g in game_plan[:3]:
            if isinstance(g, str):
                if g.strip():
                    bullets.append(g.strip())
            elif isinstance(g, dict):
                seg = (g.get("segment") or "").strip()
                tp = (g.get("talking_point") or "").strip()
                if seg and tp:
                    bullets.append(f"{seg}: {tp}")
                elif tp:
                    bullets.append(tp)
                elif seg:
                    bullets.append(seg)
            else:
                bullets.append(str(g))
        if bullets:
            _add_bullets(doc, bullets)

    # ── Situation → Graas opportunity (merged main table) ───────────────────
    # Single 5-col table that replaces both the old pain_capability_cfo
    # AND most of what_they_have. Each row covers one operational area
    # with what they have today + the gap + the Graas fit + CFO metric.
    so = data.get("situation_and_opportunity") or []
    if so:
        _add_h2(doc, "Situation → Graas opportunity")
        rows = [
            [
                r.get("operational_area", ""),
                r.get("what_they_have_today", ""),
                r.get("pain_or_gap", ""),
                r.get("graas_fit", ""),
                r.get("cfo_metric", ""),
            ]
            for r in so[:6]  # cap at 6
        ]
        _add_table(
            doc,
            headers=["Area", "What's there today", "Pain / gap", "Graas fit", "CFO metric"],
            rows=rows,
            col_widths_cm=[2.8, 5.5, 3.8, 2.9, 3.0],
            highlighted_rows=_ch("situation_and_opportunity"),
        )
    else:
        # Back-compat: legacy pain_capability_cfo render path
        pain_map = data.get("pain_capability_cfo") or []
        if pain_map:
            _add_h2(doc, "Pain → Capability → CFO metric")
            rows = [
                [r.get("pain", ""), r.get("capability", ""), r.get("metric", "")]
                for r in pain_map[:3]
            ]
            _add_table(
                doc,
                headers=["Pain (their language)", "Product capability", "CFO metric it moves"],
                rows=rows,
                col_widths_cm=[6.5, 6.5, 5.0],
                highlighted_rows=_ch("pain_capability_cfo"),
            )

    if data.get("metric_that_matters"):
        _add_kv_para(doc, "The metric that matters", data["metric_that_matters"])

    # ── Who owns what — incumbency map (agencies/SIs + where NOT to fight) ──
    inc = data.get("incumbency_map") or []
    if inc:
        _add_h2(doc, "Who owns what — and where not to fight")
        rows = [
            [r.get("platform", ""), r.get("built_by", ""),
             r.get("internal_owner", ""), r.get("verdict", "")]
            for r in inc[:6]
        ]
        _add_table(
            doc,
            headers=["Platform / system", "Built by (SI / agency)", "Internal owner", "Verdict"],
            rows=rows,
            col_widths_cm=[3.6, 4.4, 4.0, 6.0],
            highlighted_rows=_ch("incumbency_map"),
        )

    # ── What they have MOVED to appendix — see below ───────────────────────
    # The full 10-row research ledger now lives as a small 'Background'
    # callout in the appendix. Operational rows (Scale, Channel structure,
    # Tech stack, etc.) have migrated into situation_and_opportunity.

    # ── People & path in (with per-attendee lead_with) ──────────────────────
    people = list(data.get("people_path_in") or [])
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
        _add_h2(doc, "People & path in")
        rows = []
        for p in people:
            why = p.get("why_matter", "") or ""
            li = (p.get("linkedin") or "").strip()
            lead = (p.get("lead_with") or "").strip()
            if li:
                why = f"{why}\nLinkedIn: {li}" if why else f"LinkedIn: {li}"
            if lead:
                why = f"{why}\n→ Lead with: {lead}" if why else f"→ Lead with: {lead}"
            rows.append([p.get("name", ""), p.get("role", ""), why, p.get("type", "")])
        _add_table(
            doc,
            headers=["Name", "Role", "Why they matter & how to play them", "Type"],
            rows=rows,
            col_widths_cm=[3.2, 3.2, 8.4, 3.2],
            highlighted_rows=_ch("people_path_in"),
        )

    # ── Objection handling (top 3) ──────────────────────────────────────────
    objections = data.get("objection_handling") or []
    if objections:
        _add_h2(doc, "Objection handling")
        rows = [[o.get("objection", ""), o.get("response", "")] for o in objections[:3]]
        _add_table(
            doc,
            headers=["Likely objection", "Response"],
            rows=rows,
            col_widths_cm=[7.0, 11.0],
            highlighted_rows=_ch("objection_handling"),
        )

    # ── Entry wedge + Next step + Opening hook (compact close) ──────────────
    if data.get("entry_wedge"):
        _add_kv_para(doc, "Entry wedge", data["entry_wedge"])

    next_step = data.get("next_step") or {}
    if next_step:
        _add_h3(doc, "Next step")
        if next_step.get("action"):
            _add_kv_para(doc, "Recommended next move", next_step["action"])
        if next_step.get("why"):
            _add_kv_para(doc, "Why", next_step["why"])
        gate = "Yes" if next_step.get("gate_met") else "No"
        gate_line = gate
        if next_step.get("still_open"):
            gate_line += f" — still open: {next_step['still_open']}"
        _add_kv_para(doc, "Ready to solution?", gate_line)

    if data.get("opening_hook"):
        _add_h3(doc, "Opening hook")
        _add_para(doc, f"“{data['opening_hook']}”", italic=True)

    # ══════════════════════════════════════════════════════════════════════
    # APPENDIX — prep reference + post-call notes scratchpad
    # ══════════════════════════════════════════════════════════════════════

    # Page break + big "APPENDIX" heading so reader knows we're below the fold
    doc.add_page_break()
    _add_h1(doc, "Appendix")
    _add_sub(doc, "Prep reference · scannable when drilling on a specific question")

    # ── Asset → Graas-layer map ─────────────────────────────────────────────
    asset_map = data.get("asset_graas_map") or []
    if asset_map:
        _add_h2(doc, "Their digital assets → Graas layer that fits")
        rows = [
            [a.get("asset", ""), a.get("what_it_does", ""), a.get("graas_layer", "")]
            for a in asset_map
        ]
        _add_table(
            doc,
            headers=["Asset (already live)", "What it does today", "Graas layer"],
            rows=rows,
            col_widths_cm=[5.0, 7.5, 5.5],
            highlighted_rows=_ch("asset_graas_map"),
        )

    # ── Product route (small narrative) ─────────────────────────────────────
    if data.get("product_route"):
        _add_h3(doc, "Product route")
        _add_para(doc, data["product_route"])

    # ── Background facts (trimmed what_they_have ledger — 4-6 rows) ─────────
    # What's left of the original 10-row research ledger after operational
    # rows migrated to situation_and_opportunity. Non-operational only:
    # Funding · Top brands · Top competitors · Founded · Business model.
    bg = data.get("what_they_have") or []
    if bg:
        _add_h2(doc, "Background")
        rows = [
            [
                r.get("dimension", ""),
                r.get("what_we_know", ""),
                r.get("confidence", ""),
                r.get("source", ""),
            ]
            for r in bg
        ]
        _add_table(
            doc,
            headers=["Dimension", "What we know", "Confidence", "Source"],
            rows=rows,
            col_widths_cm=[3.0, 10.0, 2.3, 2.7],
            col_styles={3: {"size": 6.5, "italic": True, "color": GREY}},
            highlighted_rows=_ch("what_they_have"),
        )

    # ── Persona & order flow REMOVED — content migrated to
    # situation_and_opportunity.

    # ── Graas proof points (case-study credibility) ─────────────────────────
    proof_points = data.get("graas_proof_points") or []
    if proof_points:
        _add_h2(doc, "Graas proof points relevant to this account")
        rows = [
            [p.get("customer", ""), p.get("result", ""), p.get("applies_here", "")]
            for p in proof_points
        ]
        _add_table(
            doc,
            headers=["Customer", "Result", "Applies here because…"],
            rows=rows,
            col_widths_cm=[4.0, 7.0, 7.0],
            highlighted_rows=_ch("graas_proof_points"),
        )

    # ── Discovery agenda — 5 must-haves + 5 nice-to-haves ───────────────────
    must = data.get("discovery_must_haves") or []
    nice = data.get("discovery_nice_to_haves") or []
    if must or nice:
        _add_h2(doc, "Discovery agenda")
        _add_sub(doc, "Operational questions to confirm at the meeting. Fill the Answer column live.")
        def _disc_rows(qs):
            return [["🔓 Open", q, ""] for q in qs[:5]]
        if must:
            _add_h3(doc, "🔴 Must-haves (5)")
            _add_table(
                doc,
                headers=["Status", "Question", "Answer (fill in meeting)"],
                rows=_disc_rows(must),
                col_widths_cm=[2.0, 9.0, 7.0],
            )
        if nice:
            _add_h3(doc, "🟡 Nice-to-haves (5)")
            _add_table(
                doc,
                headers=["Status", "Question", "Answer (fill in meeting)"],
                rows=_disc_rows(nice),
                col_widths_cm=[2.0, 9.0, 7.0],
            )

    # Back-compat: legacy `discovery` dict (5-bucket structure) — render as
    # flat bulleted list under each bucket. Only fires when new fields absent.
    legacy_discovery = data.get("discovery") or {}
    if legacy_discovery and not (must or nice):
        _add_h2(doc, "Discovery agenda (legacy format)")
        for key, label in [
            ("business_model", "Business model"),
            ("data_readiness", "Data readiness"),
            ("tech_integration", "Tech stack & integration"),
            ("commercial_authority", "Commercial authority"),
        ]:
            items = legacy_discovery.get(key) or []
            if items:
                _add_h4(doc, label)
                _add_bullets(doc, items)
        ms = (legacy_discovery.get("motion_specific") or {}).get("questions") or []
        if ms:
            _add_h4(doc, (legacy_discovery.get("motion_specific") or {}).get("label") or "Motion-specific")
            _add_bullets(doc, ms)

    # ── Meeting Notes (blank — salesperson fills during/after the call) ─────
    _add_h2(doc, "Meeting Notes")
    _add_sub(doc, "Write here during or after the meeting. The next post-call update will read these notes.")
    # Render 8 empty bullet rows as a scratchpad. Salesperson types into them.
    for _ in range(8):
        _add_bullets(doc, [" "])

    # ── Recent news ─────────────────────────────────────────────────────────
    recent = data.get("recent_news") or []
    if recent:
        _add_h2(doc, "Recent news (last 12 months)")
        _add_bullets(doc, recent)

    # ── Conflicts & unknowns (callout) ──────────────────────────────────────
    conflicts = data.get("conflicts_unknowns") or {}
    if conflicts and any(conflicts.values()):
        _add_h3(doc, "Conflicts & unknowns")
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

    # Post-call highlight map → which rows in each table to mark as 'changed'.
    # Empty for pre-call drafts; only renders the .changed class when populated.
    _cr_html = data.get("_changed_rows") or {}
    def _trc(key: str, idx: int) -> str:
        return " class='changed'" if idx in (_cr_html.get(key) or []) else ""

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
tr.changed td { background: #fff4b8; }
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

    _pcl = data.get("post_call_log") or []
    if _pcl:
        parts.append(
            "<p style='font-size:8.5pt;color:#666;font-style:italic;margin:2pt 0 4pt 0;'>"
            "<span style='background:#fff4b8;padding:0 6pt;'>&nbsp;</span> "
            "Yellow highlights = sections updated in the latest call"
            "</p>"
        )
        parts.append("<h2>Post-call analysis</h2>")
        for _i, _e in enumerate(_pcl):
            _tag = " <em>(latest)</em>" if _i == 0 else " <em>(prior)</em>"
            _cn = _e.get("call_number") or (_i + 1)
            _dt = _esc(_e.get("date", ""))
            parts.append(f"<h3>Call {_cn} — {_dt}{_tag}</h3>")
            if _e.get("what_we_learned"):
                parts.append(f"<p><strong>What we learned:</strong> {_esc(_e['what_we_learned'])}</p>")
            for _key, _label in (("now_confirmed", "Now confirmed"),
                                 ("newly_surfaced", "Newly surfaced"),
                                 ("still_open", "Still open")):
                _items = _e.get(_key) or []
                if _items:
                    parts.append(f"<p><strong>{_label}:</strong></p><ul>")
                    for _it in _items:
                        parts.append(f"<li>{_esc(_it)}</li>")
                    parts.append("</ul>")
            if _e.get("route_or_next_step_change"):
                parts.append(f"<p><strong>Route / next step change:</strong> {_esc(_e['route_or_next_step_change'])}</p>")
        # Close the post-call block with a clear divider
        parts.append(
            "<hr style='border:0;border-top:2px solid #2742FF;margin:8pt 0 2pt 0;'>"
            "<p style='text-align:center;font-size:8pt;color:#666;font-style:italic;"
            "margin:0 0 8pt 0;'>— end of post-call notes · standing brief follows —</p>"
        )

    if data.get("strategic_hook"):
        parts.append(f"<p class='hook'>“{_esc(data['strategic_hook'])}”</p>")

    _asset_map = data.get("asset_graas_map") or []
    if _asset_map:
        parts.append("<h2>Their digital assets &rarr; Graas layer that fits</h2><table>")
        parts.append("<tr><th>Asset (already live)</th><th>What it does today</th><th>Graas layer</th></tr>")
        for _idx, a in enumerate(_asset_map):
            parts.append(
                f"<tr{_trc('asset_graas_map', _idx)}><td>{_esc(a.get('asset'))}</td>"
                f"<td>{_esc(a.get('what_it_does'))}</td>"
                f"<td>{_esc(a.get('graas_layer'))}</td></tr>"
            )
        parts.append("</table>")

    _why_now = data.get("why_now") or []
    if _why_now:
        parts.append("<h3>Why now</h3><ul>")
        for w in _why_now:
            parts.append(f"<li>{_esc(w)}</li>")
        parts.append("</ul>")

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
        for _idx, r in enumerate(what):
            parts.append(
                f"<tr{_trc('what_they_have', _idx)}><td>{_esc(r.get('dimension'))}</td>"
                f"<td>{_esc(r.get('what_we_know'))}</td>"
                f"<td>{_esc(r.get('confidence'))}</td>"
                f"<td class='src'>{_esc(r.get('source'))}</td></tr>"
            )
        parts.append("</table>")

    inc = data.get("incumbency_map") or []
    if inc:
        parts.append("<h2>Who owns what — and where not to fight</h2><table>")
        parts.append("<tr><th>Platform / system</th><th>Built by (SI / agency)</th>"
                     "<th>Internal owner</th><th>Verdict</th></tr>")
        for _idx, r in enumerate(inc[:6]):
            parts.append(
                f"<tr{_trc('incumbency_map', _idx)}><td>{_esc(r.get('platform'))}</td>"
                f"<td>{_esc(r.get('built_by'))}</td>"
                f"<td>{_esc(r.get('internal_owner'))}</td>"
                f"<td>{_esc(r.get('verdict'))}</td></tr>"
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

    _pp = data.get("graas_proof_points") or []
    if _pp:
        parts.append("<h3>Graas proof points relevant to this account</h3><table>")
        parts.append("<tr><th>Customer</th><th>Result</th><th>Applies here because…</th></tr>")
        for _idx, p in enumerate(_pp):
            parts.append(
                f"<tr{_trc('graas_proof_points', _idx)}><td>{_esc(p.get('customer'))}</td>"
                f"<td>{_esc(p.get('result'))}</td>"
                f"<td>{_esc(p.get('applies_here'))}</td></tr>"
            )
        parts.append("</table>")

    if data.get("persona_map"):
        parts.append("<h3>Persona &amp; order flow</h3><table>")
        parts.append("<tr><th>Persona</th><th>Count</th><th>Surface today</th><th>Current flow &amp; leaks</th></tr>")
        for _idx, r in enumerate(data["persona_map"]):
            flow = r.get("flow_and_leaks", r.get("flow", ""))
            parts.append(
                f"<tr{_trc('persona_map', _idx)}><td>{_esc(r.get('persona'))}</td>"
                f"<td>{_esc(r.get('count'))}</td>"
                f"<td>{_esc(r.get('surface'))}</td>"
                f"<td>{_esc(flow)}</td></tr>"
            )
        parts.append("</table>")
        parts.append("<p class='sub'>(critical — to be further verified)</p>")

    if data.get("pain_capability_cfo"):
        parts.append("<h3>Pain → Capability → CFO metric</h3><table>")
        parts.append("<tr><th>Pain (their language)</th><th>Product capability</th><th>CFO metric it moves</th></tr>")
        for _idx, r in enumerate(data["pain_capability_cfo"]):
            parts.append(
                f"<tr{_trc('pain_capability_cfo', _idx)}><td>{_esc(r.get('pain'))}</td>"
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
        parts.append("<tr><th>Name</th><th>Role</th><th>Why they matter &amp; how to play them</th><th>Type</th></tr>")
        for _idx, p in enumerate(_people):
            why_raw = p.get("why_matter", "") or ""
            li = (p.get("linkedin") or "").strip()
            lead = (p.get("lead_with") or "").strip()
            cell = _esc(why_raw)
            if li:
                cell = f"{cell}<br><em>LinkedIn:</em> {_esc(li)}" if cell else f"<em>LinkedIn:</em> {_esc(li)}"
            if lead:
                cell = f"{cell}<br><strong>→ Lead with:</strong> {_esc(lead)}" if cell else f"<strong>→ Lead with:</strong> {_esc(lead)}"
            parts.append(
                f"<tr{_trc('people_path_in', _idx)}><td>{_esc(p.get('name'))}</td>"
                f"<td>{_esc(p.get('role'))}</td>"
                f"<td>{cell}</td>"
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

    _gp = data.get("meeting_game_plan") or []
    if _gp:
        parts.append("<h3>Meeting game plan</h3><table>")
        parts.append("<tr><th>Min</th><th>Segment</th><th>Talking point / owner</th></tr>")
        for _idx, g in enumerate(_gp):
            parts.append(
                f"<tr{_trc('meeting_game_plan', _idx)}><td>{_esc(g.get('minute'))}</td>"
                f"<td>{_esc(g.get('segment'))}</td>"
                f"<td>{_esc(g.get('talking_point'))}</td></tr>"
            )
        parts.append("</table>")

    if data.get("opening_hook"):
        parts.append("<h3>Opening hook</h3>")
        parts.append(f"<p class='hook'>“{_esc(data['opening_hook'])}”</p>")

    _objs = data.get("objection_handling") or []
    if _objs:
        parts.append("<h3>Objection handling</h3><table>")
        parts.append("<tr><th>Likely objection</th><th>Response</th></tr>")
        for _idx, o in enumerate(_objs):
            parts.append(
                f"<tr{_trc('objection_handling', _idx)}><td>{_esc(o.get('objection'))}</td>"
                f"<td>{_esc(o.get('response'))}</td></tr>"
            )
        parts.append("</table>")

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
