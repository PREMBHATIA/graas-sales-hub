"""Impact-first data health check.

Replaces the column-by-column schema sentry (`services/schema.py`) with
a single, page-level "what's broken, what does it affect" banner.

USAGE — one call per page, at the top:

    from services.data_health import render_banner

    render_banner([
        {
            "name": "Hoppr Q&A log",
            "df": raw_eval,
            "powers": [
                "Home tab KPIs + 7d chart",
                "Account Detail timeline",
                "Ask Hoppr context",
            ],
            "required_cols": ["Seller ID", "Email ID", "Date", "Question", "Answer"],
            "tab_hint": "IMP - Evaluation_sheet",
        },
        {
            "name": "Hoppr User_State",
            "df": raw_user_state,
            "powers": ["Accounts tab classification + segments"],
        },
    ])

WHAT GETS DETECTED:
    • df is None or empty               → "returned 0 rows — tab likely renamed/deleted"
    • df missing a `required_cols` entry → "missing column 'X'"

The banner is silent when everything is OK (no clutter on the happy path).
When something's broken it renders a single red expander at the very top
of the page that lists each broken source AND every downstream feature
it powers, so the user knows exactly what won't work and why.

Design choice: NO per-column registry, no required-vs-optional tiers, no
context strings threaded through every call. Just (name, df, powers,
maybe required_cols, maybe tab_hint). The old sentry's column-by-column
verbosity is gone on purpose — for 95% of incidents (missing tab,
renamed column, empty result) you don't need it.
"""

from __future__ import annotations

from typing import Optional
import pandas as pd
import streamlit as st


def _issues_for(source: dict) -> list:
    name = source.get("name", "<unnamed source>")
    df = source.get("df")
    required_cols = source.get("required_cols", []) or []
    tab_hint = source.get("tab_hint", "")
    out = []

    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        msg = f"`{name}` returned **0 rows**"
        if tab_hint:
            msg += f" — expected tab name `{tab_hint}`; if it was renamed, fix the loader"
        else:
            msg += " — tab was likely renamed or the service account lost access"
        out.append(msg)
        return out  # no point checking columns if empty

    if isinstance(df, pd.DataFrame):
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            cols_fmt = ", ".join(f"`{c}`" for c in missing)
            out.append(
                f"`{name}` is missing required column{'s' if len(missing) > 1 else ''}: "
                f"{cols_fmt} — column was likely renamed in the source sheet"
            )
    return out


def report(sources: list) -> list:
    """Return a structured list of broken sources. Each entry:
        {"source_name": str, "powers": list[str], "issues": list[str]}
    Empty list = everything healthy.
    """
    broken = []
    for s in sources:
        issues = _issues_for(s)
        if issues:
            broken.append({
                "source_name": s.get("name", "<unnamed>"),
                "powers": s.get("powers", []) or [],
                "issues": issues,
            })
    return broken


def render_banner(sources: list) -> bool:
    """Render a single top-of-page banner for any broken sources.
    Returns True if all healthy (no banner rendered), False if any broke.

    Call this ONCE per page, right after data loads. The banner stays
    silent on the happy path — no visual noise when everything works.
    """
    broken = report(sources)
    if not broken:
        return True

    lines = [
        f"⚠️ **{len(broken)} data source"
        f"{'s' if len(broken) > 1 else ''} broken** — "
        "sections below may be incomplete or stale.",
        "",
    ]
    for b in broken:
        lines.append(f"**{b['source_name']}**")
        for issue in b["issues"]:
            lines.append(f"- {issue}")
        if b["powers"]:
            lines.append(
                "- **Affects:** " + " · ".join(b["powers"])
            )
        lines.append("")

    st.error("\n".join(lines))
    return False
