"""Branded HTML wrappers for outreach emails.

Two variants, chosen per-send in the composer (manual toggle):

  • "branded"  — dark graas header bar + cyan→blue rule + dark footer.
                 For segment / newsletter sends where a Graas email is expected.
  • "minimal"  — clean white, tiny graas chip + unsubscribe in the footer.
                 For 1:1 cold outreach, so it reads like a personal note.

Design rules come from the graas-design system: lowercase `graas` wordmark
(the real white PNG on a dark surface — it's white-on-transparent, so it MUST
sit on a dark bar/chip), near-black #0D0D11 / raised #16161D chrome, electric
cyan→blue accent (#08C1FF → #2742FF), Outfit with a system fallback (webfonts
don't load in mail clients).

Email-client realities baked in here:
  • Table-based layout + inline styles (Outlook's Word engine ignores most CSS).
  • The logo is referenced as `cid:graaslogo` and attached inline by the sender
    — data: URIs and remote images are stripped by Gmail/Outlook.
  • The cyan→blue rule carries a solid #2742FF bgcolor fallback for Outlook.
  • Body text is passed through verbatim (header/footer only — we never
    reformat what the user typed).
"""

from __future__ import annotations

import base64
import html as _html
import os
import re
from email.mime.image import MIMEImage

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "graas_logo.png")
_LOGO_CID = "graaslogo"

# NOTE: font names are DOUBLE-quoted. Every style attribute below is
# single-quoted, so single-quoted font names ('Outfit') would terminate the
# attribute early and silently drop font-family + everything after it in that
# attribute (the bug that made emails render in the client's default serif).
_FONT = ('"Outfit", -apple-system, BlinkMacSystemFont, "Segoe UI", '
         '"Helvetica Neue", Arial, sans-serif')
_URL_RE = re.compile(r'(https?://[^\s<>"]+)')


def load_logo_bytes() -> bytes:
    with open(_LOGO_PATH, "rb") as f:
        return f.read()


def logo_data_uri() -> str:
    """Base64 data: URI of the logo — for the IN-APP preview only. Real emails
    use the CID attachment (Gmail/Outlook strip data: URIs)."""
    return "data:image/png;base64," + base64.b64encode(load_logo_bytes()).decode()


def preview_html(html: str) -> str:
    """Swap the cid: logo reference for a data: URI so wrap_email output renders
    in a browser / Streamlit components.html preview."""
    return html.replace(f"cid:{_LOGO_CID}", logo_data_uri())


def logo_mime_part() -> MIMEImage:
    """Inline logo attachment the HTML references via cid:graaslogo."""
    img = MIMEImage(load_logo_bytes(), _subtype="png")
    img.add_header("Content-ID", f"<{_LOGO_CID}>")
    img.add_header("Content-Disposition", "inline", filename="graas.png")
    return img


def body_to_paragraphs(body: str, linkify=None) -> str:
    """Turn the typed plain-text body into inline-styled <p> paragraphs.

    Header/footer-only contract: we do NOT restructure the content — blank
    lines become paragraph breaks, single newlines become <br>, bare URLs
    become links. `linkify` (optional) is the sender's tracking-aware
    linkifier; if omitted we fall back to a plain anchor.
    """
    blocks = re.split(r"\n\s*\n", body.strip("\n"))
    out = []
    for blk in blocks:
        esc = _html.escape(blk).replace("\n", "<br>")
        esc = linkify(esc) if linkify else _URL_RE.sub(r"<a href='\1'>\1</a>", esc)
        out.append(
            f"<p style=\"margin:0 0 14px;\">{esc}</p>"
        )
    return "".join(out)


def _footer_links(unsubscribe_href: str, *, dark: bool = False,
                  include_linkedin: bool = True) -> str:
    link_col = "#9fb4ff" if dark else "#2742FF"
    a = f"text-decoration:none;color:{link_col};"
    parts = [f"<a href='https://graas.ai' style='{a}'>graas.ai</a>"]
    if include_linkedin:
        parts.append(
            f"<a href='https://www.linkedin.com/company/graas' style='{a}'>LinkedIn</a>"
        )
    parts.append(f"<a href='{_html.escape(unsubscribe_href)}' style='{a}'>Unsubscribe</a>")
    return " &nbsp;·&nbsp; ".join(parts)


# Footer brand line — a different, bolder face than the body copy so it reads
# as a brand statement, not more prose.
_TAGLINE = "The System of Intelligence for Retail Commerce."
_TAGLINE_STYLE = (f"font-family:{_FONT};font-weight:700;font-size:13.5px;"
                  "color:#16161D;letter-spacing:-0.1px;")


def wrap_email(variant: str, body_html: str, *, sender_name: str = "",
               unsubscribe_href: str = "mailto:insights@graas.ai?subject=Unsubscribe",
               headline: str = "", deck: str = "", date_str: str = "") -> str:
    """Wrap already-rendered body HTML in the chosen shell.

    minimal — clean 1:1 note (no masthead; footer chip + tagline + links).
    branded — segment newsletter: dark graas masthead (logo + tagline),
              gradient rule, date, a large headline + optional deck, then body.
    """
    logo = f"<img src='cid:{_LOGO_CID}' alt='graas' style='display:block;border:0;'"
    base_td = f"font-family:{_FONT};font-size:14.5px;line-height:1.6;color:#2b2b38;"

    # Small dark chip carries the white wordmark on light footers (shared).
    chip = (
        "<table role='presentation' cellpadding='0' cellspacing='0' border='0' "
        "style='display:inline-block;vertical-align:middle;'><tr>"
        "<td bgcolor='#0D0D11' style='padding:4px 8px;border-radius:4px;'>"
        f"{logo} height='12'></td></tr></table>"
    )

    if variant == "branded":
        container_w, radius, page_bg = 620, 12, "#eceef3"
        # Masthead: logo left, tagline right, on a dark band.
        masthead = (
            "<tr><td bgcolor='#0D0D11' style='padding:17px 30px;'>"
            "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
            "border='0'><tr>"
            f"<td valign='middle'>{logo} height='22'></td>"
            "<td valign='middle' align='right' style='font-family:" + _FONT +
            ";font-size:12px;font-weight:600;color:#c7ccd6;letter-spacing:.1px;'>"
            + _TAGLINE + "</td></tr></table></td></tr>"
        )
        rule = ("<tr><td height='3' style='height:3px;line-height:3px;font-size:0;"
                "background:linear-gradient(90deg,#08C1FF,#2742FF 55%,#7C5CFF);'>"
                "&nbsp;</td></tr>")
        date_row = (
            "<tr><td align='right' style='padding:16px 34px 0;font-family:" + _FONT +
            ";font-size:12.5px;color:#8a92a1;'>" + _html.escape(date_str) + "</td></tr>"
        ) if date_str else ""
        headline_block = ""
        if headline:
            deck_div = (
                "<div style='font-family:" + _FONT + ";font-size:15.5px;line-height:1.5;"
                "color:#4b5563;margin-top:14px;'>" + _html.escape(deck) + "</div>"
            ) if deck else ""
            headline_block = (
                "<tr><td style='padding:8px 34px 0;'>"
                "<div style='font-family:" + _FONT + ";font-weight:800;font-size:30px;"
                "line-height:1.12;color:#0D0D11;letter-spacing:-0.5px;'>"
                + _html.escape(headline) + "</div>" + deck_div +
                "<div style='height:1px;background:#eceef3;margin:22px 0 4px;'></div>"
                "</td></tr>"
            )
        header = masthead + rule + date_row + headline_block
        body_pad = "14px 34px 8px"
        footer = (
            "<tr><td style='padding:16px 34px 24px;border-top:1px solid #eef0f4;"
            "font-family:" + _FONT + ";font-size:12px;line-height:1.7;color:#9aa1ad;'>"
            + _footer_links(unsubscribe_href, dark=False) + "</td></tr>"
        )
    else:  # minimal
        container_w, radius, page_bg = 600, 10, "#f4f5f7"
        header = "<tr><td style='height:22px;line-height:22px;font-size:0;'>&nbsp;</td></tr>"
        body_pad = "26px 30px 6px"
        footer = (
            "<tr><td style='padding:14px 30px 22px;border-top:1px solid #eef0f4;"
            "font-family:" + _FONT + ";font-size:12px;line-height:1.7;color:#9aa1ad;'>"
            f"{chip} &nbsp; <span style='" + _TAGLINE_STYLE +
            "vertical-align:middle;'>" + _TAGLINE + "</span> &nbsp;·&nbsp; "
            f"{_footer_links(unsubscribe_href, include_linkedin=False)}"
            "</td></tr>"
        )

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width'></head>"
        f"<body style='margin:0;padding:0;background:{page_bg};'>"
        f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
        f"border='0' bgcolor='{page_bg}'><tr><td align='center' style='padding:20px 12px;'>"
        f"<table role='presentation' width='{container_w}' cellpadding='0' cellspacing='0' "
        f"border='0' style='width:{container_w}px;max-width:{container_w}px;"
        f"background:#ffffff;border-radius:{radius}px;overflow:hidden;border:1px solid #e2e6ee;'>"
        f"{header}"
        f"<tr><td bgcolor='#ffffff' style='padding:{body_pad};{base_td}'>{body_html}</td></tr>"
        f"{footer}"
        "</table></td></tr></table></body></html>"
    )
