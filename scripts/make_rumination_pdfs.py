#!/usr/bin/env python3
"""Render each rumination HTML to a PDF, and record it in the index.

A salesperson cannot send the HTML — you can't meaningfully attach it to a
mail, and copying the in-app preview doesn't work because the preview sits
inside an iframe. A PDF is the only form that actually travels, so every
rumination needs one (Prem, 25 Oct).

Uses headless Chrome, which is the only renderer here that handles the
emails' CSS and their CDN-hosted images correctly. Run it after exporting a
new rumination, then commit the PDFs — they are generated once and served
as files, so the app needs no PDF toolchain at runtime.

Usage:  python3 scripts/make_rumination_pdfs.py [--force]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
RUMI = ROOT / "content" / "collateral" / "ruminations"
PDF_DIR = RUMI / "pdf"
INDEX = RUMI / "index.json"

# Print CSS injected before rendering. The emails are a 552px column built
# for a phone, so on A4 they printed as a narrow strip down the middle with
# enormous side margins and ran to six pages. Widening the tables and easing
# the zoom down fills the page and gets the same content into four, still at
# a comfortable reading size (Prem, 25 Oct).
PRINT_CSS = (
    "<style>"
    "@page{size:A4;margin:9mm 8mm;}"
    "html,body{background:#fff !important;}"
    "body{zoom:0.85;}"
    "table{max-width:100% !important;width:100% !important;}"
    "table[bgcolor]{background:#fff !important;}"
    "img{max-width:100% !important;height:auto !important;"
    "page-break-inside:avoid;}"
    "tr,td{page-break-inside:avoid;}"
    "</style>"
)

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
]


def _chrome() -> Optional[str]:
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="re-render even if the PDF is newer than the HTML")
    args = ap.parse_args()

    chrome = _chrome()
    if not chrome:
        print("No Chrome/Chromium found — cannot render. Install one, or "
              "render the PDFs by hand and drop them in "
              f"{PDF_DIR.relative_to(ROOT)}/")
        return 1

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    made, skipped = [], []
    for html in sorted(RUMI.glob("*.html")):
        pdf = PDF_DIR / (html.stem + ".pdf")
        if (pdf.exists() and not args.force
                and pdf.stat().st_mtime >= html.stat().st_mtime):
            skipped.append(pdf.name)
            continue
        doc = html.read_text(encoding="utf-8")
        doc = (doc.replace("</head>", PRINT_CSS + "</head>", 1)
               if "</head>" in doc else PRINT_CSS + doc)
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as tmp:
            tmp.write(doc)
            tmp_path = tmp.name
        try:
            subprocess.run(
                [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                 f"--print-to-pdf={pdf}", "file://" + tmp_path],
                check=False, capture_output=True, timeout=120)
        finally:
            os.unlink(tmp_path)
        if pdf.exists():
            made.append(pdf.name)
        else:
            print(f"  FAILED to render {html.name}")

    # record paths and sizes so the page can offer the download
    try:
        idx = json.loads(INDEX.read_text(encoding="utf-8"))
    except Exception:
        idx = []
    for r in idx:
        pdf = PDF_DIR / (Path(r.get("file", "")).stem + ".pdf")
        if pdf.exists():
            r["pdf"] = str(pdf.relative_to(ROOT))
            r["pdf_kb"] = round(pdf.stat().st_size / 1024)
    INDEX.write_text(json.dumps(idx, indent=2, ensure_ascii=False),
                     encoding="utf-8")

    for n in made:
        print(f"  rendered  {n}")
    for n in skipped:
        print(f"  up to date {n}")
    print(f"\n{len(made)} rendered, {len(skipped)} already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
