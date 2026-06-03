"""Schema sentry — data observability for sheet tab schemas.

Why this exists:
    The team edits the source Google Sheets directly. When a column is renamed
    or removed, downstream pages silently produce wrong/blank metrics (e.g.
    the Pipeline page going to all-zeros after 'First conv date' was dropped
    from the unified tab). We want loud, specific errors instead — naming the
    missing column, the affected tab, and the page section that depends on it.

How to use:
    from services.schema import validate_schema

    df = fetch_sheet_tab(sheet_id, "Active presales")
    validate_schema(
        df,
        tab_name="Active presales",
        context="Pipeline Meetings YTD",
        required=["Lead name", "First conv date", "Source of lead"],  # optional override
    )

    # If columns are missing, an st.error banner renders inline and the call
    # returns {"ok": False, "missing_required": [...], "missing_optional": [...]}
    # The caller can decide whether to bail or render with what's available.

Adding a new tab:
    1. Add an entry to EXPECTED_SCHEMAS below with required + expected_optional
       columns. The registry is the source of truth for "what does the app
       expect from this tab".
    2. Call validate_schema() at the page's data-load site.
"""

from typing import Optional
import pandas as pd
import streamlit as st


# Registry of expected columns per tab name.
# 'required'           — must exist; missing → red banner, page renders broken metrics
# 'expected_optional'  — usually there; missing → yellow banner, some metrics may be empty
# 'note'               — short context shown when the tab is referenced in errors
#
# Keys are tab_name only (we identify tabs by name, not by sheet id — a tab
# named "Active presales" should have the same shape regardless of which
# spreadsheet it lives in).
EXPECTED_SCHEMAS: dict = {
    "Overall Pipeline for IN and SEA": {
        "required": [
            "Lead name", "Region", "Source of lead",
            "Active / Dropped", "Lead status",
        ],
        "expected_optional": [
            "First conv date",   # CRITICAL for Meetings YTD attribution — see note
            "Latest conv date",
            "POC Delivery Date", "Pilot Start Date", "Production Start Date",
            "Vertical", "Email of Key Personnel ",
        ],
        "note": ("Unified pipeline tab replacing 'Active presales' + 'Dropped leads'. "
                 "If 'First conv date' is missing, Pipeline meetings YTD will fall "
                 "back to the old tabs while they exist, then degrade further."),
    },
    "Active presales": {
        "required": ["Lead name", "First conv date", "Source of lead"],
        "expected_optional": [
            "Vertical", "Country", "Lead status", "Latest conv date",
            "Email of Key Personnel ",
        ],
        # NOTE: this tab uses "Country" while the unified tab + Dropped leads
        # use "Region" — pages that read it normalize via rename. Don't add
        # "Region" to the optional list here or the sentry will spuriously
        # flag it as missing every render.
        "note": ("Source of truth for Meetings YTD attribution until "
                 "'First conv date' is restored on the unified tab. "
                 "Uses 'Country' column (legacy); pages normalize to 'Region'."),
    },
    "Dropped leads": {
        "required": ["Lead name", "First conv date", "Source of lead"],
        "expected_optional": [
            "Vertical", "Region", "Lead status", "Latest conv date",
            "Email of Key Personnel ",
        ],
        "note": "Same role as 'Active presales' for the dropped-leads side.",
    },
    "Hoppr__Anaysis": {
        "required": ["user_key"],
        "expected_optional": [
            "email", "Last_seen", "Total_queries", "queries_last_7d",
            "Q_Summary_For_Hoppr", "bucket",
        ],
        "note": "Source of the Hoppr seller table + classifications.",
    },
}


def validate_schema(
    df: pd.DataFrame,
    tab_name: str,
    context: str = "",
    required: Optional[list] = None,
    expected_optional: Optional[list] = None,
    show_warnings: bool = True,
) -> dict:
    """Check a fetched dataframe against the expected schema for a tab.

    Args:
        df: the DataFrame returned by the fetch.
        tab_name: the sheet tab name (used as the registry key).
        context: human-readable identifier for where this is being called
                 from, e.g. "Pipeline Meetings YTD section". Shown in the
                 error banner so users know what's affected.
        required: optional override of the required column list. If omitted,
                  uses what's registered in EXPECTED_SCHEMAS.
        expected_optional: same, for optional columns.
        show_warnings: if False, suppress optional-column warnings (use this
                       for non-critical checks where missing optional cols
                       are acceptable).

    Returns:
        {
            "ok": bool,                  # True if all required cols present
            "missing_required": [...],   # required cols not in df
            "missing_optional": [...],   # optional cols not in df
            "tab_name": str,
        }
    """
    schema = EXPECTED_SCHEMAS.get(tab_name, {})
    req = required if required is not None else schema.get("required", [])
    opt = expected_optional if expected_optional is not None else schema.get("expected_optional", [])
    note = schema.get("note", "")

    ctx = f" (needed for **{context}**)" if context else ""

    # Empty dataframe is a separate failure mode — could mean tab renamed,
    # deleted, sheet permissions changed, or fetch errored silently.
    if df is None or df.empty:
        st.error(
            f"⚠️ **Schema sentry**: tab `{tab_name}` returned **no rows**{ctx}.\n\n"
            f"Possible causes:\n"
            f"- Tab was renamed or deleted in the source sheet\n"
            f"- Service account lost access (re-share with editor permission)\n"
            f"- Fetch errored silently (check Streamlit logs)\n\n"
            + (f"_Note about this tab: {note}_" if note else "")
        )
        return {
            "ok": False,
            "missing_required": list(req),
            "missing_optional": list(opt),
            "tab_name": tab_name,
        }

    have = set(df.columns)
    missing_req = [c for c in req if c not in have]
    missing_opt = [c for c in opt if c not in have]

    if missing_req:
        st.error(
            f"⚠️ **Schema sentry**: tab `{tab_name}` is missing **required** columns: "
            f"`{', '.join(missing_req)}`{ctx}.\n\n"
            f"This typically happens when someone renames or removes columns in the "
            f"source sheet. Either restore the columns, or update the code "
            f"(`services/schema.py` + the page that called this) to match the new schema.\n\n"
            + (f"_Note about this tab: {note}_" if note else "")
        )

    if missing_opt and show_warnings:
        st.warning(
            f"ℹ️ Tab `{tab_name}` is missing optional columns: `{', '.join(missing_opt)}`{ctx}. "
            f"Some metrics that depend on these will render as empty or use fallbacks."
            + (f"\n\n_{note}_" if note else "")
        )

    return {
        "ok": not missing_req,
        "missing_required": missing_req,
        "missing_optional": missing_opt,
        "tab_name": tab_name,
    }


def validate_many(checks: list) -> bool:
    """Run multiple validate_schema calls. Returns True only if ALL pass.

    Each item in `checks` is a tuple of (df, tab_name, context).
    Useful when a page depends on several tabs and you want a single
    bail-out check.

    Example:
        ok = validate_many([
            (df_active,  "Active presales", "Pipeline Meetings YTD"),
            (df_dropped, "Dropped leads",   "Pipeline Meetings YTD"),
        ])
        if not ok:
            st.stop()
    """
    results = [validate_schema(df, tab, context=ctx) for df, tab, ctx in checks]
    return all(r["ok"] for r in results)
