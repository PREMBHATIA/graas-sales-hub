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

import html as _html
import os
import re
from email.mime.image import MIMEImage

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "graas_logo.png")
_LOGO_CID = "graaslogo"

_FONT = ("'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', "
         "'Helvetica Neue', Arial, sans-serif")
_URL_RE = re.compile(r'(https?://[^\s<>"]+)')


def load_logo_bytes() -> bytes:
    with open(_LOGO_PATH, "rb") as f:
        return f.read()


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


def _footer_links(unsubscribe_href: str, *, dark: bool) -> str:
    link_col = "#9fb4ff" if dark else "#2742FF"
    a = f"text-decoration:none;color:{link_col};"
    return (
        f"<a href='https://graas.ai' style='{a}'>graas.ai</a> &nbsp;·&nbsp; "
        f"<a href='https://www.linkedin.com/company/graas' style='{a}'>LinkedIn</a> "
        f"&nbsp;·&nbsp; <a href='{_html.escape(unsubscribe_href)}' style='{a}'>Unsubscribe</a>"
    )


def wrap_email(variant: str, body_html: str, *, sender_name: str = "",
               unsubscribe_href: str = "mailto:insights@graas.ai?subject=Unsubscribe") -> str:
    """Wrap already-rendered body HTML in the chosen branded shell."""
    logo = f"<img src='cid:{_LOGO_CID}' alt='graas' style='display:block;border:0;'"
    base_td = (f"font-family:{_FONT};font-size:14.5px;line-height:1.6;"
               f"color:#2b2b38;")

    if variant == "branded":
        header = (
            "<tr><td bgcolor='#0D0D11' style='padding:16px 30px;'>"
            f"{logo} height='20'></td></tr>"
            "<tr><td bgcolor='#2742FF' height='3' style='height:3px;line-height:3px;"
            "font-size:0;background:linear-gradient(90deg,#08C1FF,#2742FF);'>&nbsp;</td></tr>"
        )
        footer = (
            "<tr><td bgcolor='#16161D' style='padding:20px 30px;font-family:" + _FONT +
            ";font-size:12px;line-height:1.6;color:#8a8f9c;'>"
            f"{logo} height='15' style='display:block;border:0;opacity:.92;margin-bottom:7px;'>"
            "<div style='color:#c7ccd6;'>Growth as a Service — agentic commerce for modern brands.</div>"
            f"<div style='margin-top:6px;'>{_footer_links(unsubscribe_href, dark=True)}</div>"
            "<div style='margin-top:8px;color:#5c6070;'>Sent by insights@graas.ai · "
            "You're receiving this as a business contact.</div>"
            "</td></tr>"
        )
        page_bg = "#eceef3"
    else:  # minimal
        header = "<tr><td style='height:22px;line-height:22px;font-size:0;'>&nbsp;</td></tr>"
        chip = (
            "<table role='presentation' cellpadding='0' cellspacing='0' border='0' "
            "style='display:inline-block;vertical-align:middle;'><tr>"
            "<td bgcolor='#0D0D11' style='padding:4px 8px;border-radius:4px;'>"
            f"{logo} height='12'></td></tr></table>"
        )
        footer = (
            "<tr><td style='padding:14px 30px 22px;border-top:1px solid #eef0f4;"
            "font-family:" + _FONT + ";font-size:12px;line-height:1.7;color:#9aa1ad;'>"
            f"{chip} &nbsp; Growth as a Service &nbsp;·&nbsp; "
            f"{_footer_links(unsubscribe_href, dark=False)}"
            "</td></tr>"
        )
        page_bg = "#f4f5f7"

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width'></head>"
        f"<body style='margin:0;padding:0;background:{page_bg};'>"
        f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
        f"border='0' bgcolor='{page_bg}'><tr><td align='center' style='padding:20px 12px;'>"
        "<table role='presentation' width='600' cellpadding='0' cellspacing='0' border='0' "
        "style='width:600px;max-width:600px;background:#ffffff;border-radius:10px;"
        "overflow:hidden;border:1px solid #e2e6ee;'>"
        f"{header}"
        f"<tr><td bgcolor='#ffffff' style='padding:26px 30px 6px;{base_td}'>{body_html}</td></tr>"
        f"{footer}"
        "</table></td></tr></table></body></html>"
    )
