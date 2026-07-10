"""Hoppr — Usage Dashboard · Accounts · Ask Hoppr"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
from collections import Counter
import sys
import re
import os
from datetime import datetime as _dt, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"), override=True)

st.set_page_config(page_title="Hoppr | Graas", page_icon="📊", layout="wide")

# ── API key ───────────────────────────────────────────────────────────────────
try:
    ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Hardcoded fallback — same sheet the Command Center uses
HOPPR_SHEET_ID = os.getenv("HOPPR_SHEET_ID", "1IR6KuRhPMRj_JsF261ZEUjLlHXu6UZ33diZQRw2MqJM")

st.markdown("## 📊 Hoppr (+ MCP Beta)")


# ══════════════════════════════════════════════════════════════════════════════
# PROCESSING FUNCTIONS (inlined from Command Center data_processor.py)
# ══════════════════════════════════════════════════════════════════════════════

def process_hoppr_daily(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    header_row = None
    for idx, row in df.iterrows():
        vals = [str(v).strip() for v in row.values]
        if "DATE" in vals and "TOTAL_NO_OF_QUERIES" in vals:
            header_row = idx
            break
    if header_row is None:
        return pd.DataFrame()
    data_df = df.iloc[header_row + 1:].copy()
    headers = [str(v).strip() for v in df.iloc[header_row].values]
    daily_col_names = ["DATE", "TOTAL_NO_OF_QUERIES", "UNIQUE_USERS", "TOTAL_UNIQUE_SELLERS",
                       "REPEAT_GUEST_USERS", "NEW_SIGNUPS", "LOGGED_IN_SELLER_FROM_TC",
                       "LOGGED_IN_SELLER_FROM_HOPPR"]
    daily_indices = [headers.index(n) for n in daily_col_names if n in headers]
    if not daily_indices:
        return pd.DataFrame()
    result = data_df.iloc[:, daily_indices].copy()
    result.columns = ["date", "total_queries", "unique_users", "unique_sellers",
                      "repeat_guests", "new_signups", "login_from_tc", "login_from_hoppr"][:len(daily_indices)]
    result["date"] = result["date"].astype(str).str.strip()
    result = result[~result["date"].isin(["", "nan"])].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result = result.dropna(subset=["date"])
    for col in result.columns[1:]:
        result[col] = pd.to_numeric(result[col], errors="coerce").fillna(0).astype(int)
    return result.sort_values("date").reset_index(drop=True)


def process_hoppr_country(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    header_row = None
    for idx, row in df.iterrows():
        vals = [str(v).strip() for v in row.values]
        if "COUNTRY_CODE" in vals:
            header_row = idx
            break
    if header_row is None:
        return pd.DataFrame()
    headers = [str(v).strip() for v in df.iloc[header_row].values]
    data_df = df.iloc[header_row + 1:].copy()
    date_positions = [i for i, h in enumerate(headers) if h == "DATE"]
    if len(date_positions) < 2:
        return pd.DataFrame()
    country_code_idx = headers.index("COUNTRY_CODE")
    country_col_names = ["TOTAL_NO_OF_QUERIES", "TOTAL_UNIQUE_USER_EMAILS",
                         "TOTAL_UNIQUE_SELLERS", "NEW_SIGNUPS", "LOGGED_IN_SELLER",
                         "SELLERS_WITH_CONNECTED_CHANNELS"]
    country_indices = [date_positions[1], country_code_idx]
    for name in country_col_names:
        for i in range(country_code_idx + 1, len(headers)):
            if headers[i] == name:
                country_indices.append(i)
                break
    result = data_df.iloc[:, country_indices].copy()
    col_labels = ["date", "country", "total_queries", "unique_users",
                  "unique_sellers", "new_signups", "logged_in", "connected"]
    result.columns = col_labels[:len(country_indices)]
    result["date"] = result["date"].astype(str).str.strip()
    result = result[~result["date"].isin(["", "nan"])].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result = result.dropna(subset=["date"])
    for col in result.columns[2:]:
        result[col] = pd.to_numeric(result[col], errors="coerce").fillna(0).astype(int)
    return result.sort_values("date").reset_index(drop=True)


def process_hoppr_daily_from_eval(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    cols = [str(c).strip() for c in df.columns]
    df = df.copy()
    df.columns = cols
    sid_col   = next((c for c in cols if "seller" in c.lower() and "id" in c.lower()), None)
    email_col = next((c for c in cols if "email" in c.lower()), None)
    date_col  = next((c for c in cols if c.lower() == "date"), None)
    if not (sid_col and email_col and date_col):
        return pd.DataFrame()
    work = df[[sid_col, email_col, date_col]].copy()
    work["_date"] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=["_date"])
    if work.empty:
        return pd.DataFrame()
    daily = (work.groupby("_date")
             .agg(total_queries=(email_col, "count"),
                  unique_users=(email_col, "nunique"),
                  unique_sellers=(sid_col, "nunique"))
             .reset_index().rename(columns={"_date": "date"}))
    daily["new_signups"] = daily["repeat_guests"] = daily["login_from_tc"] = daily["login_from_hoppr"] = 0
    return daily.sort_values("date").reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADERS
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600)
def load_hoppr_daily():
    from services.sheets_client import fetch_sheet_tab
    try:
        df = fetch_sheet_tab(HOPPR_SHEET_ID, "Hoppr__Anaysis")
        return df if not df.empty else pd.DataFrame(), None
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl=1800)
def load_evaluation_sheet():
    """Read the Q&A log. The Hoppr team renamed the tab to
    'IMP - Evaluation_sheet'; we try the new name first and fall back to
    the old one so neither rename direction can break the page again."""
    from services.sheets_client import fetch_sheet_tab
    for tab_name in ("IMP - Evaluation_sheet", "Evaluation_sheet"):
        try:
            df = fetch_sheet_tab(HOPPR_SHEET_ID, tab_name)
            if not df.empty:
                return df, None
        except Exception as e:
            return pd.DataFrame(), str(e)
    return pd.DataFrame(), None

@st.cache_data(ttl=1800)
def load_user_state():
    from services.sheets_client import fetch_sheet_tab
    try:
        df = fetch_sheet_tab(HOPPR_SHEET_ID, "User_State")
        return df if not df.empty else pd.DataFrame(), None
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl=1800)
def load_internal_daily():
    """Internal Hoppr usage by Graas employees — daily series.
    Sheet has DATE / TOTAL_NO_OF_QUERIES / UNIQUE_USERS / UNIQUE_SELLERS."""
    from services.sheets_client import fetch_sheet_tab
    try:
        df = fetch_sheet_tab(HOPPR_SHEET_ID, "Internal Users-1")
        if df.empty:
            return pd.DataFrame(), None
        out = pd.DataFrame({
            "date":           pd.to_datetime(df.get("DATE"), errors="coerce"),
            "total_queries":  pd.to_numeric(df.get("TOTAL_NO_OF_QUERIES"), errors="coerce").fillna(0).astype(int),
            "unique_users":   pd.to_numeric(df.get("UNIQUE_USERS"), errors="coerce").fillna(0).astype(int),
            "unique_sellers": pd.to_numeric(df.get("UNIQUE_SELLERS"), errors="coerce").fillna(0).astype(int),
        }).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        return out, None
    except Exception as e:
        return pd.DataFrame(), str(e)


@st.cache_data(ttl=1800)
def load_new_signups():
    """Day-level new signups — the authoritative UTM-derived counts from the
    'IMP - New Signups' tab (already a tab in the Hoppr sheet). The header sits a
    row or two down, so we locate it, then sum 'New Signups' + 'New Channels
    Connected' per date across sources."""
    from services.sheets_client import fetch_sheet_tab
    try:
        raw = fetch_sheet_tab(HOPPR_SHEET_ID, "IMP - New Signups")
        if raw.empty:
            return pd.DataFrame(), None
        hdr = None
        for i, row in raw.iterrows():
            vals = [str(v).strip() for v in row.values]
            if "DATE" in vals and any("New Signups" in v for v in vals):
                hdr = i
                break
        if hdr is None:
            return pd.DataFrame(), "header row not found"
        H = [str(v).strip() for v in raw.iloc[hdr].values]
        d = raw.iloc[hdr + 1:]
        di = H.index("DATE")
        si = next(i for i, h in enumerate(H) if "New Signups" in h)
        ci = next((i for i, h in enumerate(H) if "Connected" in h), None)
        out = pd.DataFrame({
            "date": pd.to_datetime(d.iloc[:, di].astype(str).str.strip(), errors="coerce"),
            "new_signups": pd.to_numeric(d.iloc[:, si], errors="coerce").fillna(0),
            "connected": (pd.to_numeric(d.iloc[:, ci], errors="coerce").fillna(0)
                          if ci is not None else 0),
        }).dropna(subset=["date"])
        out = (out.groupby("date", as_index=False)
                  .agg(new_signups=("new_signups", "sum"),
                       connected=("connected", "sum")))
        out["new_signups"] = out["new_signups"].astype(int)
        out["connected"] = out["connected"].astype(int)
        return out.sort_values("date").reset_index(drop=True), None
    except Exception as e:
        return pd.DataFrame(), str(e)


# ── Fetch ─────────────────────────────────────────────────────────────────────

raw_daily,      _err_daily      = load_hoppr_daily()
raw_eval,       _err_eval       = load_evaluation_sheet()
raw_user_state, _err_user_state = load_user_state()
internal_daily, _err_internal   = load_internal_daily()
signups_daily,  _err_signups    = load_new_signups()

# MCP Beta usage (sellers querying the same warehouse via Claude/GPT).
# Import only PRE-EXISTING symbols from the shared module (_load_questions_log +
# the sheet id). Streamlit Cloud can serve a stale cached copy of a changed
# service module, so importing a brand-new symbol from it can ImportError — the
# daily-aggregate loader is therefore defined locally here (this page re-runs).
from services.mcp_beta_view import (
    _load_questions_log as _load_mcp_questions_log,
    MCP_SHEET_ID as _MCP_SHEET_ID,
)


@st.cache_data(ttl=1800)
def _load_mcp_daily():
    """MCP daily aggregate — the 'Daily Summary' tab (REPORT_DATE / USERS /
    QUESTIONS). Full history, unlike the recent-only Questions Log."""
    from services.sheets_client import fetch_sheet_tab
    try:
        df = fetch_sheet_tab(_MCP_SHEET_ID, "Daily Summary")
        if df.empty:
            return pd.DataFrame(), None
        out = pd.DataFrame({
            "date":        pd.to_datetime(df.get("REPORT_DATE"), errors="coerce"),
            "users":       pd.to_numeric(df.get("USERS"), errors="coerce").fillna(0).astype(int),
            "questions":   pd.to_numeric(df.get("QUESTIONS"), errors="coerce").fillna(0).astype(int),
            "sql_queries": pd.to_numeric(df.get("SQL_QUERIES"), errors="coerce").fillna(0).astype(int),
        }).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        return out, None
    except Exception as e:
        return pd.DataFrame(), str(e)


mcp_log, _err_mcp = _load_mcp_questions_log()        # per-question (recent) — powers the "asking about" text breakdown
mcp_daily, _err_mcp_daily = _load_mcp_daily()        # daily aggregate (full history) — powers the row + trend line

# ── Data health: one banner at the top, impact-first ─────────────────────────
# Silent on the happy path. When something breaks (tab renamed, column gone,
# empty result) the banner names the source AND every page section it affects.
# Replaces the old column-by-column schema sentry buried below the fold.
from services.data_health import render_banner as _data_health_banner
_data_health_banner([
    {
        "name": "Hoppr Q&A log (IMP - Evaluation_sheet)",
        "df": raw_eval,
        "powers": [
            "Home tab KPIs + 7d chart",
            "Account Detail timeline + per-seller usage",
            "Ask Hoppr context",
        ],
        "required_cols": ["Seller ID", "Email ID", "Date", "Question", "Answer"],
        "tab_hint": "IMP - Evaluation_sheet",
    },
    {
        "name": "Hoppr daily aggregate (Hoppr__Anaysis)",
        "df": raw_daily,
        "powers": [
            "Fallback Home KPIs when Q&A log unavailable",
            "Country breakdown chart",
        ],
        "tab_hint": "Hoppr__Anaysis",
    },
    {
        "name": "Hoppr User_State (account classification)",
        "df": raw_user_state,
        "powers": ["Accounts tab classification + segments + recommended actions"],
        "tab_hint": "User_State",
    },
    {
        "name": "Internal Hoppr Usage (Graas employees)",
        "df": internal_daily,
        "powers": ["Home tab 'Internal' KPI row", "Dashed internal-queries line on the chart"],
        "tab_hint": "Internal Users-1",
    },
])
if "_loading_rows_filtered" in st.session_state:
    n_load = st.session_state["_loading_rows_filtered"]
    if n_load > 0:
        st.caption(f"🚫 Filtered out **{n_load}** 'Loading…' rows from analytics.")

col_r, _ = st.columns([1, 9])
with col_r:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

# ── Build daily metrics ───────────────────────────────────────────────────────

daily_from_analysis = process_hoppr_daily(raw_daily) if not raw_daily.empty else pd.DataFrame()
daily_from_eval     = process_hoppr_daily_from_eval(raw_eval) if not raw_eval.empty else pd.DataFrame()

if not daily_from_eval.empty and (
    daily_from_analysis.empty or len(daily_from_eval) > len(daily_from_analysis) + 7
):
    daily = daily_from_eval
else:
    daily = daily_from_analysis

country = process_hoppr_country(raw_daily) if not raw_daily.empty else pd.DataFrame()

# ── Hard cutoff: ignore anything before this date everywhere on the page.
# The 2025 / pre-launch rows in the eval log + User_State + analysis sheet
# drag down completeness stats, distort trend charts, and create stale
# "last active" entries. Trim once at the top so every downstream view is
# clean by default.
HOPPR_DATA_START = pd.Timestamp("2026-01-01")

if not daily.empty and "date" in daily.columns:
    daily = daily[daily["date"] >= HOPPR_DATA_START].reset_index(drop=True)
if not country.empty and "date" in country.columns:
    country = country[country["date"] >= HOPPR_DATA_START].reset_index(drop=True)
if not internal_daily.empty and "date" in internal_daily.columns:
    internal_daily = internal_daily[
        internal_daily["date"] >= HOPPR_DATA_START
    ].reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# QUESTION CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

# Question taxonomy — shared with the MCP Beta page via services/question_classifier.py
from services.question_classifier import (
    ACCURACY_KEYWORDS,
    QUESTION_BUCKETS,
    classify_question,
    is_accuracy,
)


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT QUALITY SCORING
# ══════════════════════════════════════════════════════════════════════════════
# Score 0-100 on 4 signals: metric, timeframe, entity, comparison.
# Strong prompts (≥70) have most/all 4. Vague prompts (<20) have none + are short.

SCORE_METRIC_WORDS = [
    "gmv", "nmv", "revenue", "sales", "orders", "roas", "ctr", "cpc", "cpa",
    "aov", "conversion", "traffic", "visitor", "impression", "click",
    "units", "sold", "quantity", "stock", "inventory", "ad spend",
    "income", "profit", "margin", "performance",
    "cancellation", "refund", "return rate",
    "spend", "cost", "ads", "campaign",
]
SCORE_TIME_WORDS = [
    "yesterday", "today", "this week", "last week",
    "this month", "last month", "this year", "last year",
    "last 7", "last 30", "last 90", "past week", "past month",
    "wow", "mom", "yoy", "year on year", "month on month", "week on week",
    "year-on-year", "month-on-month", "week-on-week",
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    "january", "february", "march", "april", "june",
    "july", "august", "september", "october", "november", "december",
    "2024", "2025", "2026", "q1", "q2", "q3", "q4",
]
SCORE_ENTITY_WORDS = [
    "sku", "product", "brand", "category", "shopee", "lazada", "tiktok",
    "tokopedia", "amazon", "qoo10", "blibli", "channel", "marketplace",
    "campaign", "country", "indonesia", "malaysia", "philippines",
    "thailand", "vietnam", "singapore", "india",
    "customer", "buyer", "creator", "affiliate", "kol", "influencer",
]
SCORE_COMPARISON_WORDS = [
    " vs ", "versus", "compared", "compare", "comparison",
    "growth", "increase", "decrease", "drop", "rise", "fell",
    "trend", "trending", "better", "worse", "higher", "lower",
    "delta", "change", "vs.", "v/s",
]
SCORE_FOLLOWUP_PHRASES = [
    "give me the same", "same for", "include", "also show", "also give",
    "what about", "more", "another", "next", "again", "and that",
    "do that", "yes", "ok", "okay", "fine", "go ahead",
]

def score_prompt(q) -> dict:
    """Return {'score': 0-100, 'tier': str, 'reasons': list}."""
    if q is None or (isinstance(q, float) and pd.isna(q)):
        return {"score": 0, "tier": "Empty", "reasons": []}
    text = str(q).strip()
    ql = text.lower()
    if ql in ("", "loading...", "loading", "nan"):
        return {"score": 0, "tier": "Empty", "reasons": []}

    word_count = len(text.split())
    has_metric  = any(kw in ql for kw in SCORE_METRIC_WORDS)
    has_time    = any(kw in ql for kw in SCORE_TIME_WORDS)
    has_entity  = any(kw in ql for kw in SCORE_ENTITY_WORDS)
    has_compare = any(kw in ql for kw in SCORE_COMPARISON_WORDS)
    is_followup = (word_count <= 5
                   and any(p in ql for p in SCORE_FOLLOWUP_PHRASES))
    is_too_short = word_count < 4

    score = 0
    reasons = []
    if word_count >= 6:
        score += 15; reasons.append("✓ length")
    elif word_count >= 4:
        score += 5
    if has_metric:
        score += 30; reasons.append("✓ metric")
    else:
        reasons.append("✗ no metric")
    if has_time:
        score += 25; reasons.append("✓ timeframe")
    else:
        reasons.append("✗ no timeframe")
    if has_entity:
        score += 20; reasons.append("✓ entity")
    if has_compare:
        score += 10; reasons.append("✓ comparison")

    if is_followup:
        score = min(score, 25); reasons.append("✗ pure followup")
    if is_too_short:
        score = min(score, 25); reasons.append("✗ too short")

    score = max(0, min(score, 100))
    if   score >= 70: tier = "Strong"
    elif score >= 45: tier = "Decent"
    elif score >= 20: tier = "Weak"
    else:             tier = "Vague"
    return {"score": score, "tier": tier, "reasons": reasons}


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT INTENT CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════
# Orthogonal to Prompt Q: classifies WHAT KIND of question the seller is asking.
#   Factual    — what/when/how many · descriptive lookup
#   Diagnostic — why/cause · explanatory
#   Strategic  — should I / recommend / predict · prescriptive or forward-looking
# Order matters: Strategic and Diagnostic checked first because phrases like
# "what should I do" or "why is X dropping" would otherwise be caught by the
# broader Factual "what/" / "what is" patterns.

INTENT_STRATEGIC_PHRASES = [
    "should i", "should we", "what should", "how should", "what to do",
    "recommend", "recommendation", "suggest", "suggestion", "advise", "advice",
    "best way", "best approach", "optimi", "improve", "grow ", "increase",
    "predict", "forecast", "projection", "project ", "expected to",
    "going to", "will reach", "will be", "next quarter", "next month",
    "how can i", "how can we", "how do i grow", "how do we grow",
    "how to grow", "how to improve", "how to fix", "how to increase",
    "ways to", "strategy", "plan ", "action ", "next step", "next move",
]
INTENT_DIAGNOSTIC_PHRASES = [
    "why ", "why is", "why are", "why did", "why does", "why has", "why have",
    "reason", "cause", "caused", "because", "due to",
    "what's driving", "what is driving", "what drove",
    "root cause", "behind the", "explain", "explanation",
    "what happened", "what went wrong",
]
INTENT_FACTUAL_PHRASES = [
    "what is", "what was", "what are", "what were", "what's",
    "when ", "where ", "who ",
    "how many", "how much", "how often", "how long",
    "list ", "show ", "give me", "tell me", "display",
    "top ", "bottom ", "rank", "highest", "lowest",
    " vs ", "versus", "compare", "comparison", "between",
    "which ", "name ", "find ", "breakdown",
]

def classify_prompt_intent(q) -> str:
    """Return 'Strategic' | 'Diagnostic' | 'Factual' | 'Unclear'."""
    if q is None or (isinstance(q, float) and pd.isna(q)):
        return "Unclear"
    ql = str(q).strip().lower()
    if ql in ("", "loading...", "loading", "nan"):
        return "Unclear"
    if any(p in ql for p in INTENT_STRATEGIC_PHRASES):
        return "Strategic"
    if any(p in ql for p in INTENT_DIAGNOSTIC_PHRASES):
        return "Diagnostic"
    if any(p in ql for p in INTENT_FACTUAL_PHRASES):
        return "Factual"
    return "Unclear"


# ══════════════════════════════════════════════════════════════════════════════
# PRE-PROCESS EVAL SHEET
# ══════════════════════════════════════════════════════════════════════════════

eval_processed = pd.DataFrame()
sid_col_e = email_col_e = date_col_e = q_col_e = a_col_e = None

if not raw_eval.empty:
    edf = raw_eval.copy()
    ecols = [str(c).strip() for c in edf.columns]
    edf.columns = ecols

    # ── Detect helper / index columns by name (these are stable) ─────────────
    sid_col_e = (
        next((c for c in ecols if "seller" in c.lower() and "id" in c.lower()), None)
        or next((c for c in ecols if c.lower() in ("seller", "seller_id", "account")), None)
    )
    email_col_e = next((c for c in ecols if "email" in c.lower()), None)
    date_col_e = (
        next((c for c in ecols if c.strip().lower() == "date"), None)
        or next((c for c in ecols if "date" in c.lower() or "timestamp" in c.lower()), None)
    )

    # ── Question / answer detection — robust to column shifts + mislabeled headers.
    #    History: the eval sheet's Q/A headers AND positions have both proven
    #    unreliable. A column got inserted so the header "Question" (and index 5)
    #    pointed at a numbering column ("1") while the real question text sat under
    #    the "Answer" header — which silently classified every row as "General".
    #    So we ignore Q/A headers and positions: drop the known metadata columns,
    #    then take the two longest free-text columns. Earlier column (by sheet
    #    order) = question, later = answer.
    _META_NAMES = {
        "seller id", "seller_id", "seller", "account", "email id", "email",
        "email_id", "date", "timestamp", "response time", "response_time",
        "session id", "session_id",
    }

    def _avg_text_len(col: str) -> float:
        v = edf[col].astype(str).str.strip()
        v = v[~v.str.lower().isin(["", "nan", "loading...", "loading"])]
        return float(v.str.len().mean()) if len(v) else 0.0

    _cand = [c for c in ecols
             if c.lower() not in _META_NAMES
             and c not in (sid_col_e, email_col_e, date_col_e)]
    _qa = [c for c in sorted(_cand, key=_avg_text_len, reverse=True)
           if _avg_text_len(c) >= 10][:2]
    _qa = sorted(_qa, key=lambda c: ecols.index(c))  # sheet order: question first
    if len(_qa) >= 2:
        q_col_e, a_col_e = _qa[0], _qa[1]
    elif len(_qa) == 1:
        q_col_e, a_col_e = _qa[0], None
    else:
        # Degenerate sheet (no free-text columns) — best-effort named fallback.
        q_col_e = next((c for c in ecols if "question" in c.lower()), None)
        a_col_e = next((c for c in ecols if "answer" in c.lower()), None)

    # ── Always store debug info ───────────────────────────────────────────────
    st.session_state["eval_col_debug"] = (
        f"seller={sid_col_e} | email={email_col_e} | date={date_col_e} | "
        f"question={q_col_e} | answer={a_col_e} | "
        f"all_cols={ecols}"
    )

    if sid_col_e and date_col_e and q_col_e:
        edf["_date"]     = pd.to_datetime(edf[date_col_e], errors="coerce")
        edf["_week"]     = edf["_date"].dt.to_period("W").dt.start_time
        edf["_seller"]   = edf[sid_col_e].astype(str).str.strip()
        edf["_email"]    = edf[email_col_e].astype(str).str.strip() if email_col_e else ""
        edf["_question"] = edf[q_col_e].astype(str)
        edf["_answer"]   = edf[a_col_e].astype(str) if a_col_e else ""
        edf = edf.dropna(subset=["_date"])

        # ── Hard cutoff: 2025 / pre-launch rows out before counting ────────
        # Mirrors the daily-aggregate filter further up; same rationale.
        edf = edf[edf["_date"] >= HOPPR_DATA_START]

        # ── Filter "Loading..." log noise out of all analytics ─────────────
        # These rows are Hoppr's incomplete-response logs, not real prompts.
        # Counting them was inflating the "General" bucket and skewing the chart.
        _q_clean = edf["_question"].astype(str).str.strip().str.lower()
        _n_loading = int(_q_clean.isin(["loading...", "loading", "", "nan"]).sum())
        edf = edf[~_q_clean.isin(["loading...", "loading", "", "nan"])]
        st.session_state["_loading_rows_filtered"] = _n_loading

        edf["_is_accuracy"] = edf["_question"].apply(is_accuracy)
        edf["_buckets"]     = edf["_question"].apply(classify_question)
        _scores = edf["_question"].apply(score_prompt)
        edf["_prompt_score"] = _scores.apply(lambda d: d["score"])
        edf["_prompt_tier"]  = _scores.apply(lambda d: d["tier"])
        edf["_prompt_intent"] = edf["_question"].apply(classify_prompt_intent)
        eval_processed = edf


# ══════════════════════════════════════════════════════════════════════════════
# COLUMN-MAPPING DIAGNOSTICS (after eval_processed is built)
# ══════════════════════════════════════════════════════════════════════════════

if not eval_processed.empty and "_answer" in eval_processed.columns:
    _ans_clean = eval_processed["_answer"].astype(str).str.strip()
    _ans_real = _ans_clean[~_ans_clean.str.lower().isin(
        ["", "nan", "loading...", "loading"]
    )]
    _real_count = len(_ans_real)
    _missing_count = len(eval_processed) - _real_count
    _pct_real = _real_count / len(eval_processed) * 100 if len(eval_processed) else 0
    _q_loading = st.session_state.get("_loading_rows_filtered", 0)

    # Tucked into a collapsed expander — these are diagnostics for when
    # something's wrong with the upstream logging, not headline numbers.
    # Live page reads from filtered `eval_processed`, which already drops
    # `Loading…` rows for analytics — so this banner is purely informational.
    with st.expander(
        f"🔧 Data diagnostics (post-{HOPPR_DATA_START.strftime('%d %b %Y')}) — "
        f"{_pct_real:.0f}% of rows complete · {_q_loading} 'Loading…' rows filtered",
        expanded=False,
    ):
        st.caption(
            f"**Hoppr logging health:** "
            f"{_real_count} of {len(eval_processed) + _q_loading} total rows have BOTH "
            f"question + answer captured ({_pct_real:.0f}% complete). "
            f"**{_missing_count}** rows have a question but `Loading…` in the answer column · "
            f"**{_q_loading}** rows had `Loading…` in the question column too. "
            f"Reading from `{q_col_e}` / `{a_col_e}`."
        )
        st.caption("Picks one row with a real question, shows what every column "
                   "contains so you can verify which column has Hoppr's answer.")
        real_row = None
        if not raw_eval.empty:
            for i in range(min(50, len(raw_eval))):
                rr = raw_eval.iloc[i]
                qv = str(rr.iloc[5]).strip() if len(rr) > 5 else ""
                if (len(qv) > 20
                    and qv.lower() not in ("loading...", "loading", "nan", "")):
                    real_row = (i, rr)
                    break
        if real_row is None:
            st.info("No row with a substantive question found in the first 50 rows.")
        else:
            idx, rr = real_row
            st.markdown(f"**Inspecting row {idx}** (col F has real content here):")
            for col_idx, (col_name, val) in enumerate(zip(raw_eval.columns, rr.values)):
                val_str = str(val) if val is not None else ""
                val_len = len(val_str.strip())
                letter = chr(ord("A") + col_idx) if col_idx < 26 else f"col{col_idx}"
                snippet = val_str[:200].replace("\n", " ")
                st.markdown(
                    f"- **Col {letter}** (`{col_name}`) — len={val_len}: "
                    f"`{snippet}{'…' if val_len > 200 else ''}`"
                )
            st.caption(f"Currently reading question from `{q_col_e}` and answer from `{a_col_e}`. "
                       f"If the actual Hoppr response is in a different column above, "
                       f"tell me the column letter and I'll point at it directly.")


# ══════════════════════════════════════════════════════════════════════════════
# PARSE SELLERS FROM USER_STATE
# ══════════════════════════════════════════════════════════════════════════════

# ── Sellers list — built from eval (always fresh), enriched by User_State ────
#
# Source-of-truth choice:
#   Quantitative facts (last active, days silent, query counts, trend) →
#     derived from the raw Q&A log (IMP - Evaluation_sheet). Always fresh.
#   Qualitative judgements (classification bucket, running summary, sales
#     recommended action, reason/tags) → LEFT JOIN from User_State, which
#     is Hoppr's LLM-generated pipeline output. Marked "Unclassified" when
#     a seller appears in eval but User_State hasn't caught up yet.
#
# Earlier version drove sellers off User_State and overlaid eval dates. That
# meant sellers who'd queried in the last few days but hadn't been picked up
# by User_State's aggregator were invisible to the Accounts tab.
sellers = []
seller_users_map = {}
_today_d = _dt.now().date()


def _classify_bucket(raw_bucket: str) -> str:
    bl = (raw_bucket or "").lower()
    if "sales" in bl or "ready" in bl: return "Sales-Ready"
    if "power" in bl:                  return "Power User"
    if "explor" in bl:                 return "Explorer"
    if "block" in bl:                  return "Blocked"
    if raw_bucket:                     return "Low Usage"
    return "Unclassified"


def _trend_from_silent(days_silent: int) -> str:
    if days_silent <= 1:  return "Highly Active"
    if days_silent <= 7:  return "Active"
    if days_silent <= 30: return "Going Quiet"
    return "Churned"


# Build a lookup from User_State for the qualitative fields. Keyed by seller_id.
_us = {}
if not raw_user_state.empty:
    for idx in range(len(raw_user_state)):
        row = raw_user_state.iloc[idx]
        vals = [str(v).strip() if pd.notna(v) else "" for v in row.values]
        sid = vals[0]
        if not sid or sid in ("user_key", "") or not re.match(r"^[A-Z0-9]{2,10}$", sid):
            continue
        _us[sid] = {
            "email_fallback": vals[2] if len(vals) > 2 else "",
            "bucket":         vals[7] if len(vals) > 7 else "",
            "q_summary":      vals[6] if len(vals) > 6 else "",
            "action":         vals[8] if len(vals) > 8 else "",
            "a_summary":      vals[9] if len(vals) > 9 else "",
        }

# Build sellers from eval rows — every distinct seller_id that has logged a query.
if not eval_processed.empty and "_seller" in eval_processed.columns:
    _ev = eval_processed[["_seller", "_email", "_date"]].copy()
    _ev = _ev[_ev["_seller"].notna() & (_ev["_seller"].astype(str) != "")
              & (_ev["_seller"].astype(str) != "nan")]

    _seven_days_ago = pd.Timestamp(_today_d - timedelta(days=7))

    for sid, grp in _ev.groupby("_seller", sort=False):
        # Strict seller-id sanity (matches old User_State validation)
        if not re.match(r"^[A-Z0-9]{2,10}$", str(sid)):
            continue

        dates = grp["_date"].dropna()
        last_dt = dates.max() if not dates.empty else None
        last_active = last_dt.strftime("%Y-%m-%d") if last_dt is not None else ""
        days_silent = (_today_d - last_dt.date()).days if last_dt is not None else 999

        q_total = len(grp)
        q_recent = int((dates >= _seven_days_ago).sum()) if not dates.empty else 0

        # Email: pick the most-recently-active one for this seller; fall
        # back to User_State email if eval has no usable email.
        email = ""
        non_empty = grp[grp["_email"].astype(str).str.contains("@", na=False)]
        if not non_empty.empty:
            email = str(non_empty.sort_values("_date").iloc[-1]["_email"])
        elif sid in _us:
            email = _us[sid]["email_fallback"]

        us_row = _us.get(sid, {})
        sellers.append({
            "seller_id":      sid,
            "email":          email,
            "q_recent":       q_recent,
            "q_total":        q_total,
            "last_active":    last_active,
            "days_silent":    days_silent,
            "trend":          _trend_from_silent(days_silent),
            "classification": _classify_bucket(us_row.get("bucket", "")),
            "q_summary":      us_row.get("q_summary", ""),
            "a_summary":      us_row.get("a_summary", ""),
            "action":         us_row.get("action", ""),
        })

        # Per-seller email map (for the Accounts → Account Detail user list)
        seller_users_map[sid] = {}
        for em, eg in grp.groupby("_email", sort=False):
            em_str = str(em)
            if em_str in ("", "nan") or "@" not in em_str:
                continue
            em_dates = eg["_date"].dropna().dt.strftime("%Y-%m-%d").tolist()
            seller_users_map[sid][em_str] = {"count": len(eg), "dates": em_dates}

    # Per-seller avg prompt quality (excluding Empty rows)
    _scored_only = eval_processed[eval_processed["_prompt_tier"] != "Empty"]
    _seller_avg = (_scored_only.groupby("_seller")["_prompt_score"]
                   .mean().round(0).astype(int).to_dict()) if not _scored_only.empty else {}

    # Per-seller intent mix (excluding Unclear rows)
    _intent_rows = (eval_processed[eval_processed["_prompt_intent"] != "Unclear"]
                    if "_prompt_intent" in eval_processed.columns else pd.DataFrame())
    _seller_intent = {}
    if not _intent_rows.empty:
        for sid, grp in _intent_rows.groupby("_seller"):
            cnts = grp["_prompt_intent"].value_counts()
            total = int(cnts.sum())
            if total == 0:
                continue
            f = int(round(cnts.get("Factual", 0) / total * 100))
            d = int(round(cnts.get("Diagnostic", 0) / total * 100))
            s_pct = max(0, 100 - f - d)
            _seller_intent[sid] = {
                "mix": f"{f}F·{d}D·{s_pct}S",
                "dominant": cnts.idxmax(),
                "f_pct": f, "d_pct": d, "s_pct": s_pct,
            }

    for s in sellers:
        sid = s["seller_id"]
        if sid in seller_users_map:
            info = seller_users_map[sid]
            s["user_count"] = len(info)
            s["all_emails"] = list(info.keys())
        else:
            s["user_count"] = 1
            s["all_emails"] = [s["email"]]
        s["prompt_quality"] = _seller_avg.get(sid, None)
        _imix = _seller_intent.get(sid)
        s["intent_mix"]      = _imix["mix"]      if _imix else "—"
        s["intent_dominant"] = _imix["dominant"] if _imix else "—"
else:
    for s in sellers:
        s.setdefault("user_count", 1)
        s.setdefault("all_emails", [s.get("email", "")])
        s.setdefault("prompt_quality", None)
        s.setdefault("intent_mix", "—")
        s.setdefault("intent_dominant", "—")


# ══════════════════════════════════════════════════════════════════════════════
# HELPER
# ══════════════════════════════════════════════════════════════════════════════

def apply_period(df: pd.DataFrame, period: str, date_col: str = "_date"):
    if df.empty or date_col not in df.columns:
        return df
    today_ts   = df[date_col].max()
    data_start = df[date_col].min()
    cutoffs    = {"1W": today_ts - pd.Timedelta(days=7),
                  "1M": today_ts - pd.Timedelta(days=30),
                  "3M": today_ts - pd.Timedelta(days=90),
                  "YTD": pd.Timestamp(today_ts.year, 1, 1)}
    if period in cutoffs:
        return df[df[date_col] >= max(cutoffs[period], data_start)]
    return df


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_home, tab_accounts, tab_ask, tab_mcp = st.tabs(
    ["🏠 Home", "👥 Accounts", "💬 Ask Hoppr", "🔌 MCP Beta  ✨ NEW"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — HOME
# ══════════════════════════════════════════════════════════════════════════════

with tab_home:

    # Period drives BOTH the KPI grid and the chart below, so the cards
    # and the visual always tell the same story.
    period = st.radio("Period", ["1W", "1M", "3M", "YTD"], index=1, horizontal=True, key="hoppr_period")
    _PERIOD_LABEL = {"1W": "7d", "1M": "30d", "3M": "90d", "YTD": "YTD"}
    _period_suffix = _PERIOD_LABEL.get(period, period)

    def _slice_by_period(df, period_key, today_ts):
        if df.empty:
            return df
        if period_key == "YTD":
            year_start = pd.Timestamp(today_ts.year, 1, 1)
            return df[df["date"] >= year_start]
        if period_key not in {"1W", "1M", "3M"}:
            return df
        days = {"1W": 7, "1M": 30, "3M": 90}[period_key]
        return df[df["date"] >= today_ts - pd.Timedelta(days=days)]

    if not daily.empty:
        today_ts = daily["date"].max()
        ext_slice = _slice_by_period(daily, period, today_ts)

        # ── EXTERNAL: true period-uniques from the raw eval log ──
        # Summing daily uniques over-counts users who appear on multiple
        # days (the old bug). We compute nunique() on the raw rows instead.
        ext_queries = int(ext_slice["total_queries"].sum())
        # New Signups — authoritative day-level counts from the 'IMP - New Signups'
        # tab (Rohan's UTM-derived source, already in the Hoppr sheet). Fall back to
        # the Hoppr__Anaysis NEW_SIGNUPS column if that tab is unavailable/empty.
        ext_signups = 0
        if not signups_daily.empty and "new_signups" in signups_daily.columns:
            _sig_sl = _slice_by_period(signups_daily, period, today_ts)
            ext_signups = int(_sig_sl["new_signups"].sum()) if not _sig_sl.empty else 0
        elif not daily_from_analysis.empty and "new_signups" in daily_from_analysis.columns:
            _sig_sl = _slice_by_period(
                daily_from_analysis[daily_from_analysis["date"] >= HOPPR_DATA_START],
                period, today_ts)
            ext_signups = int(_sig_sl["new_signups"].sum()) if not _sig_sl.empty else 0
        ext_unique_users = 0
        ext_unique_sellers = 0
        if not eval_processed.empty and "_date" in eval_processed.columns:
            if period == "YTD":
                _ep_cutoff = pd.Timestamp(today_ts.year, 1, 1)
            else:
                _ep_cutoff = today_ts - pd.Timedelta(days={"1W": 7, "1M": 30, "3M": 90}[period])
            ep_slice = eval_processed[eval_processed["_date"] >= _ep_cutoff]
            if not ep_slice.empty:
                ext_unique_users = int(
                    ep_slice["_email"].dropna().astype(str)
                    .pipe(lambda s: s[s.str.contains("@", na=False)])
                    .nunique()
                )
                ext_unique_sellers = int(
                    ep_slice["_seller"].dropna().astype(str)
                    .pipe(lambda s: s[(s != "") & (s != "nan")])
                    .nunique()
                )

        # ── INTERNAL: peak daily uniques (true period-uniques not derivable
        # from the pre-aggregated Internal Users-1 source).
        int_queries = int_peak_users = int_peak_sellers = 0
        if not internal_daily.empty:
            int_slice = _slice_by_period(internal_daily, period, today_ts)
            if not int_slice.empty:
                int_queries     = int(int_slice["total_queries"].sum())
                int_peak_users   = int(int_slice["unique_users"].max())
                int_peak_sellers = int(int_slice["unique_sellers"].max())

        # ── Grid render ────────────────────────────────────────────────
        _HDR_STYLE = (
            "font-size:0.82rem;color:#4B5563;font-weight:600;"
            "letter-spacing:0.02em;text-transform:none;padding-bottom:4px;"
        )
        _LBL_STYLE = (
            "padding-top:6px;font-weight:600;color:#374151;font-size:0.9rem;"
        )
        _VAL_STYLE = (
            "font-size:2rem;font-weight:600;color:#111827;line-height:1.1;"
        )

        def _cell(html):
            st.markdown(html, unsafe_allow_html=True)

        h = st.columns([1, 2, 2, 2, 2, 2])
        with h[0]: _cell("")
        with h[1]: _cell(f"<div style='{_HDR_STYLE}'>Queries ({_period_suffix})</div>")
        with h[2]: _cell(f"<div style='{_HDR_STYLE}'>Unique Users ({_period_suffix})</div>")
        with h[3]: _cell(f"<div style='{_HDR_STYLE}'>Unique Sellers ({_period_suffix})</div>")
        with h[4]: _cell(f"<div style='{_HDR_STYLE}'>New Signups ({_period_suffix})</div>")
        with h[5]: _cell(f"<div style='{_HDR_STYLE}'>SQL Queries ({_period_suffix})</div>")

        def _val(v):
            return f"<div style='{_VAL_STYLE}'>{v:,}</div>" if isinstance(v, int) else f"<div style='{_VAL_STYLE}'>{v}</div>"

        # External row — all values are TRUE counts over the period.
        r1 = st.columns([1, 2, 2, 2, 2, 2])
        with r1[0]: _cell(f"<div style='{_LBL_STYLE}'>External</div>")
        with r1[1]: _cell(_val(ext_queries))
        with r1[2]: _cell(_val(ext_unique_users))
        with r1[3]: _cell(_val(ext_unique_sellers))
        with r1[4]: _cell(_val(ext_signups))
        with r1[5]: _cell(_val("—"))

        # Internal row — queries are true sum; users/sellers are PEAK DAILY
        # (marked with † and explained in the caption below).
        if not internal_daily.empty:
            r2 = st.columns([1, 2, 2, 2, 2, 2])
            with r2[0]: _cell(f"<div style='{_LBL_STYLE}'>Internal</div>")
            with r2[1]: _cell(_val(int_queries))
            with r2[2]: _cell(f"<div style='{_VAL_STYLE}'>{int_peak_users:,}<sup style='font-size:0.55em;color:#9CA3AF;'>†</sup></div>")
            with r2[3]: _cell(f"<div style='{_VAL_STYLE}'>{int_peak_sellers:,}<sup style='font-size:0.55em;color:#9CA3AF;'>†</sup></div>")
            with r2[4]: _cell(_val("—"))
            with r2[5]: _cell(_val("—"))

            st.caption(
                "† Internal Unique Users / Sellers = **peak day** in the period "
                "(true period-uniques aren't derivable from the pre-aggregated "
                "`Internal Users-1` sheet — it has daily counts only, no user IDs)."
            )

        # ── MCP row: sellers querying the same warehouse via Claude/GPT (MCP
        #    integration) — a third usage surface. Uses the MCP "Daily Summary"
        #    aggregate (full history). Like Internal, Users/Sellers are the peak
        #    day† — the pre-aggregated source has no per-user IDs for true
        #    period-uniques. (MCP user ≈ seller, so both columns show the same.)
        if not mcp_daily.empty and "date" in mcp_daily.columns:
            _mcp_sl = _slice_by_period(mcp_daily, period, today_ts)
            _mcp_q = int(_mcp_sl["questions"].sum()) if not _mcp_sl.empty else 0
            _mcp_u = int(_mcp_sl["users"].max()) if not _mcp_sl.empty else 0
            _mcp_sql = (int(_mcp_sl["sql_queries"].sum())
                        if not _mcp_sl.empty and "sql_queries" in _mcp_sl.columns else 0)
            _mcp_peak = (f"<div style='{_VAL_STYLE}'>{_mcp_u:,}"
                         f"<sup style='font-size:0.55em;color:#9CA3AF;'>†</sup></div>")
            r3 = st.columns([1, 2, 2, 2, 2, 2])
            with r3[0]: _cell(f"<div style='{_LBL_STYLE}'>MCP</div>")
            with r3[1]: _cell(_val(_mcp_q))
            with r3[2]: _cell(_mcp_peak)
            with r3[3]: _cell(_mcp_peak)
            with r3[4]: _cell(_val("—"))
            with r3[5]: _cell(_val(_mcp_sql))
            st.caption(
                "MCP = sellers querying the Graas warehouse via Claude / GPT "
                "(same data, different surface). Users/Sellers = peak day†. "
                "Full detail on the 🔌 MCP Beta tab."
            )

    if not daily.empty:
        today_ts   = daily["date"].max()
        data_start = daily["date"].min()
        cutoffs = {"1W": today_ts - pd.Timedelta(days=7),
                   "1M": today_ts - pd.Timedelta(days=30),
                   "3M": today_ts - pd.Timedelta(days=90)}
        if period in cutoffs:
            cutoff    = max(cutoffs[period], data_start)
            daily_f   = daily[daily["date"] >= cutoff]
            country_f = country[country["date"] >= cutoff] \
                if not country.empty and "date" in country.columns else country
        else:
            daily_f, country_f = daily, country

        f_start = daily_f["date"].min().strftime("%d %b %Y").lstrip("0") if not daily_f.empty else "—"
        f_end   = daily_f["date"].max().strftime("%d %b %Y").lstrip("0") if not daily_f.empty else "—"
        st.caption(f"📅 {f_start} → {f_end} · {len(daily_f)} days")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=daily_f["date"], y=daily_f["total_queries"],
                                 mode="lines+markers", name="Hoppr · Queries (ext)",
                                 line=dict(color="#4F46E5", width=2)))
        fig.add_trace(go.Bar(x=daily_f["date"], y=daily_f["unique_sellers"],
                             name="Hoppr · Sellers (ext)", marker_color="#7C3AED", opacity=0.5))
        fig.add_trace(go.Scatter(x=daily_f["date"], y=daily_f["new_signups"],
                                 mode="lines+markers", name="Hoppr · New Signups",
                                 line=dict(color="#10B981", dash="dot")))
        # Internal Hoppr usage — only the queries line, dashed gray so it
        # reads as "background context", not a competing primary signal.
        if not internal_daily.empty:
            i_f = internal_daily[internal_daily["date"] >= daily_f["date"].min()]
            if not i_f.empty:
                fig.add_trace(go.Scatter(
                    x=i_f["date"], y=i_f["total_queries"],
                    mode="lines", name="Hoppr · Queries (int)",
                    line=dict(color="#9CA3AF", dash="dash", width=1.5),
                ))
        # MCP queries — red dotted, from the MCP "Daily Summary" aggregate (full
        # history, unlike the recent-only Questions Log). Kept visually distinct
        # because usage is currently internal-driven, not external adoption yet.
        if not mcp_daily.empty and "date" in mcp_daily.columns:
            _mcp_d = mcp_daily[mcp_daily["date"] >= daily_f["date"].min()]
            if not _mcp_d.empty:
                fig.add_trace(go.Scatter(
                    x=_mcp_d["date"], y=_mcp_d["questions"],
                    mode="lines+markers", name="MCP · Queries",
                    line=dict(color="#EF4444", dash="dot", width=1.8),
                ))
        fig.update_layout(height=340, template="plotly_dark", margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)

        if not country_f.empty:
            ca = (country_f.groupby("country")["total_queries"].sum()
                  .reset_index().query("country != 'Unknown'")
                  .sort_values("total_queries", ascending=True))
            if not ca.empty:
                fig_c = px.bar(ca, x="total_queries", y="country", orientation="h",
                               color_discrete_sequence=["#4F46E5"],
                               labels={"total_queries": "Queries", "country": ""},
                               title="By Country")
                fig_c.update_layout(height=220, template="plotly_dark",
                                    margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig_c, use_container_width=True)
    else:
        st.warning("No daily usage data available. Check that the Google service account has access to the Hoppr sheet.")

    # ── What sellers are asking ───────────────────────────────────────────────
    if not eval_processed.empty:
        st.markdown("---")
        st.markdown("### 📊 What Hoppr Sellers Are Asking About")
        ev_f = apply_period(eval_processed, period)
        if not ev_f.empty:
            bucket_rows = [{"bucket": b} for buckets in ev_f["_buckets"] for b in buckets]
            if bucket_rows:
                bc = pd.DataFrame(bucket_rows)["bucket"].value_counts().reset_index()
                bc.columns = ["Question Type", "Count"]
                fig_b = px.bar(bc, x="Count", y="Question Type", orientation="h",
                               color="Question Type",
                               color_discrete_sequence=px.colors.qualitative.Bold,
                               labels={"Count": "Queries", "Question Type": ""})
                fig_b.update_layout(height=400, template="plotly_dark",
                                    margin=dict(l=20, r=20, t=10, b=20),
                                    showlegend=False, yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig_b, use_container_width=True)

            # ── Diagnostic: what's hiding inside "General"? ───────────────────
            general_qs = ev_f[ev_f["_buckets"].apply(
                lambda bs: bs == ["General"]
            )]["_question"].dropna().astype(str)
            general_qs = general_qs[general_qs.str.strip().str.lower()
                                    .ne("loading...")]
            general_qs = general_qs[general_qs.str.strip().ne("")]

            if len(general_qs) > 0:
                with st.expander(f"🔍 What's in 'General'? ({len(general_qs)} uncategorised queries)"):
                    # Top recurring n-grams (2-3 words) — finds repeated phrases
                    import re as _re
                    from collections import Counter as _Counter
                    STOP = {
                        "the","a","an","of","to","in","on","for","is","are","was","were",
                        "i","you","we","my","me","our","this","that","it","be","do","does",
                        "and","or","but","if","what","how","why","when","where","which",
                        "show","give","tell","please","can","could","would","should","get",
                        "with","by","at","from","as","have","has","had","not","no","yes",
                    }
                    def _tokens(s):
                        return [w for w in _re.findall(r"[a-zA-Z]+", s.lower())
                                if w not in STOP and len(w) > 2]
                    bigrams, trigrams, words = _Counter(), _Counter(), _Counter()
                    for q in general_qs:
                        toks = _tokens(q)
                        words.update(toks)
                        bigrams.update(zip(toks, toks[1:]))
                        trigrams.update(zip(toks, toks[1:], toks[2:]))

                    cA, cB, cC = st.columns(3)
                    with cA:
                        st.markdown("**Top words**")
                        for w, c in words.most_common(15):
                            st.text(f"{c:>3}  {w}")
                    with cB:
                        st.markdown("**Top 2-word phrases**")
                        for (w1, w2), c in bigrams.most_common(15):
                            if c < 2: break
                            st.text(f"{c:>3}  {w1} {w2}")
                    with cC:
                        st.markdown("**Top 3-word phrases**")
                        for (w1, w2, w3), c in trigrams.most_common(15):
                            if c < 2: break
                            st.text(f"{c:>3}  {w1} {w2} {w3}")

                    st.markdown("**Sample questions (first 25)**")
                    for q in general_qs.head(25):
                        st.text(f"• {q[:180]}")

    # ── What MCP users are asking about — its own graphic, right under the Hoppr
    #    one. MCP questions phrase differently; buckets need not match Hoppr's. ──
    if not mcp_log.empty and "QUESTION_TEXT" in mcp_log.columns and "_ts" in mcp_log.columns:
        st.markdown("---")
        st.markdown("### 🔌 What MCP Users Are Asking About")
        st.caption("Sellers querying the Graas warehouse via Claude / GPT (MCP) — same period as above.")
        if period == "YTD":
            _mcp_cut2 = pd.Timestamp(mcp_log["_ts"].max().year, 1, 1)
        else:
            _mcp_cut2 = mcp_log["_ts"].max() - pd.Timedelta(
                days={"1W": 7, "1M": 30, "3M": 90}[period])
        _mcp_qsl = mcp_log[mcp_log["_ts"] >= _mcp_cut2]
        _mcp_buckets = [b for q in _mcp_qsl["QUESTION_TEXT"].dropna().astype(str)
                        for b in classify_question(q)]
        if _mcp_buckets:
            _mbc = pd.Series(_mcp_buckets).value_counts().reset_index()
            _mbc.columns = ["Question Type", "Count"]
            _fig_m = px.bar(_mbc, x="Count", y="Question Type", orientation="h",
                            color="Question Type",
                            color_discrete_sequence=px.colors.qualitative.Bold,
                            labels={"Count": "Queries", "Question Type": ""})
            _fig_m.update_layout(height=400, template="plotly_dark",
                                 margin=dict(l=20, r=20, t=10, b=20),
                                 showlegend=False, yaxis=dict(autorange="reversed"))
            st.plotly_chart(_fig_m, use_container_width=True)
        else:
            st.caption("_No MCP questions in this period._")

    # ── Data accuracy ─────────────────────────────────────────────────────────
    if not eval_processed.empty:
        st.markdown("---")
        st.markdown("### ⚠️ Data Accuracy Issues")
        st.caption("Questions where sellers flagged data gaps, mismatches, or incorrect values")
        acc_all = eval_processed[eval_processed["_is_accuracy"]]
        acc_f   = apply_period(acc_all, period) if not acc_all.empty else acc_all
        if acc_f.empty:
            st.success("No data accuracy queries in this period.")
        else:
            a1, a2, a3 = st.columns(3)
            with a1: st.metric("Accuracy Queries", len(acc_f))
            with a2: st.metric("Sellers Affected", acc_f["_seller"].nunique())
            with a3:
                total_f = len(apply_period(eval_processed, period))
                st.metric("% of All Queries", f"{len(acc_f)/total_f*100:.1f}%" if total_f else "—")
            view = st.radio("View as", ["Over Time", "By Account"], horizontal=True, key="acc_view")
            if view == "Over Time":
                weekly = acc_f.groupby("_week").size().reset_index(name="Queries")
                weekly.columns = ["Week", "Queries"]
                fig_a = px.bar(weekly, x="Week", y="Queries", color_discrete_sequence=["#EF4444"])
                fig_a.update_layout(height=260, template="plotly_dark", margin=dict(l=20, r=20, t=20, b=20))
                st.plotly_chart(fig_a, use_container_width=True)
            else:
                by_acct = (acc_f.groupby("_seller")
                           .agg(Queries=("_question", "count"),
                                Example=("_question", lambda x: x.iloc[0][:100]))
                           .reset_index().sort_values("Queries", ascending=False).head(20))
                by_acct.columns = ["Seller", "Accuracy Queries", "Example Question"]
                st.dataframe(by_acct, use_container_width=True, hide_index=True)
            with st.expander(f"Show all {len(acc_f)} accuracy queries"):
                show = acc_f[["_date", "_seller", "_email", "_question"]].copy()
                show.columns = ["Date", "Seller", "Email", "Question"]
                show["Question"] = show["Question"].str[:200]
                st.dataframe(show.sort_values("Date", ascending=False), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — ACCOUNTS
# ══════════════════════════════════════════════════════════════════════════════

with tab_accounts:

    if not sellers:
        st.warning("No account data available.")
    else:
        sellers_df = pd.DataFrame(sellers)
        if "user_count" not in sellers_df.columns:
            sellers_df["user_count"] = 1

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        with k1: st.metric("Total Sellers", len(sellers_df))
        with k2: st.metric("Total Users", int(sellers_df["user_count"].sum()))
        with k3: st.metric("Active (7d)", len(sellers_df[sellers_df["days_silent"] <= 7]))
        with k4: st.metric("Power Users", len(sellers_df[sellers_df["classification"] == "Power User"]))
        with k5: st.metric("Sales-Ready", len(sellers_df[sellers_df["classification"] == "Sales-Ready"]))
        with k6: st.metric("Going Quiet", len(sellers_df[sellers_df["trend"] == "Going Quiet"]), delta_color="inverse")

        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            classes = sorted(sellers_df["classification"].unique())
            sel_cls = st.multiselect("Classification", classes, default=list(classes), key="acct_class")
        with fc2:
            trends_l = sorted(sellers_df["trend"].unique())
            sel_tr = st.multiselect("Trend", trends_l, default=list(trends_l), key="acct_trend")
        with fc3:
            search = st.text_input("Search (ID or email)", "", key="acct_search")

        filt = sellers_df[sellers_df["classification"].isin(sel_cls) & sellers_df["trend"].isin(sel_tr)]
        if search:
            filt = filt[filt["seller_id"].str.contains(search, case=False, na=False) |
                        filt["email"].str.contains(search, case=False, na=False)]

        def cls_color(v):
            return {"Sales-Ready": "background-color:#065F46;color:white",
                    "Power User":  "background-color:#1E40AF;color:white",
                    "Explorer":    "background-color:#92400E;color:white",
                    "Low Usage":   "background-color:#78350F;color:white",
                    "Blocked":     "background-color:#7F1D1D;color:white"}.get(v, "")

        def tr_color(v):
            return {"Highly Active": "color:#10B981", "Active": "color:#06B6D4",
                    "Going Quiet":   "color:#F59E0B", "Churned": "color:#EF4444"}.get(v, "")

        def pq_color(v):
            try:    n = int(v)
            except: return ""
            if n >= 70: return "color:#10B981;font-weight:600"   # Strong
            if n >= 45: return "color:#06B6D4"                    # Decent
            if n >= 20: return "color:#F59E0B"                    # Weak
            return "color:#EF4444;font-weight:600"                # Vague

        def intent_color(v):
            return {"Strategic":  "color:#A78BFA;font-weight:600",
                    "Diagnostic": "color:#F59E0B",
                    "Factual":    "color:#9CA3AF"}.get(v, "")

        disp_cols = ["seller_id", "email", "user_count", "q_total", "q_recent",
                     "prompt_quality", "intent_dominant", "intent_mix",
                     "last_active", "days_silent", "trend", "classification"]
        if "prompt_quality" not in filt.columns:
            filt = filt.copy()
            filt["prompt_quality"] = None
        if "intent_dominant" not in filt.columns:
            filt = filt.copy()
            filt["intent_dominant"] = "—"
            filt["intent_mix"] = "—"
        disp = filt[disp_cols].copy()
        disp = disp.sort_values("days_silent")
        def _pq_fmt(v):
            try:
                if v is None or pd.isna(v): return "—"
                return f"{int(v)}"
            except Exception:
                return "—"

        # Click any row → Account Detail section below jumps to that seller.
        # selection.rows is indexed into the dataframe we pass (positional, not
        # post-user-sort), so disp.iloc[i] always gives the right seller.
        table_event = st.dataframe(
            disp.rename(columns={
                "seller_id": "Seller", "email": "Email", "user_count": "Users",
                "q_total": "Total Q", "q_recent": "Q (7d)",
                "prompt_quality": "Prompt Q",
                "intent_dominant": "Intent",
                "intent_mix": "Mix (F·D·S)",
                "last_active": "Last Active", "days_silent": "Days Silent",
                "trend": "Trend", "classification": "Class",
            }).style.map(cls_color, subset=["Class"])
              .map(tr_color, subset=["Trend"])
              .map(pq_color, subset=["Prompt Q"])
              .map(intent_color, subset=["Intent"])
              .format({"Prompt Q": _pq_fmt}),
            use_container_width=True, height=380, hide_index=True,
            on_select="rerun", selection_mode="single-row",
            key="sellers_table",
        )
        st.caption("👆 **Tip:** click any row to jump the Account Detail section below to that seller.")
        st.caption("**Prompt Q** is a 0–100 score per seller — Strong ≥70 (green) · Decent 45–69 · Weak 20–44 · Vague <20 (red). Based on whether prompts include a metric, timeframe, entity, and comparison.")
        st.caption("**Intent** classifies what kind of question sellers ask: **Factual** (what/when/how many — descriptive lookup), **Diagnostic** (why/cause — explanatory), **Strategic** (should I/recommend/predict — prescriptive). Mix shows the % split. Strategic-heavy sellers are getting more value from Hoppr.")

        # Stash the clicked seller_id so the Account Detail dropdown picks it up
        # on the next render. Two-step (set + rerun) is needed because the
        # dropdown is built later in the page — we can't write to its session
        # state after it's already rendered.
        if table_event and getattr(table_event, "selection", None):
            clicked_rows = list(table_event.selection.get("rows", []))
            if clicked_rows:
                _clicked_sid = str(disp.iloc[clicked_rows[0]]["seller_id"])
                if st.session_state.get("_jump_to_seller") != _clicked_sid:
                    st.session_state["_jump_to_seller"] = _clicked_sid
                    st.rerun()

        st.markdown("---")
        st.markdown("### 🔍 Account Detail")

        dd_col1, dd_col2 = st.columns([3, 1])
        with dd_col1:
            # Build options from ALL sellers (not just those with eval rows).
            # Sellers whose only queries were "Loading..." get filtered from
            # eval_processed, so they would otherwise vanish from the picker.
            sq = (eval_processed["_seller"].value_counts().to_dict()
                  if not eval_processed.empty else {})
            # Sort: most recently active first (days_silent ascending — 0 = today).
            # Tiebreaker: higher query volume first so equally-recent accounts
            # surface the more-engaged one. Accounts with no last_active default
            # to days_silent=999, so they naturally sink to the bottom.
            dd_opts = []
            for s in sorted(sellers,
                            key=lambda x: (
                                x.get("days_silent", 999),
                                -(sq.get(x["seller_id"], 0) or x.get("q_total", 0)),
                            )):
                sid = s["seller_id"]
                eval_q = sq.get(sid, 0)
                total_q = s.get("q_total", 0)
                if eval_q > 0:
                    dd_opts.append(f"{sid} ({eval_q}Q)")
                elif total_q > 0:
                    dd_opts.append(f"{sid} ({total_q}Q · no logs)")
                else:
                    dd_opts.append(f"{sid} (—)")
            if not dd_opts and not eval_processed.empty:
                # Fallback if sellers list was empty
                dd_opts = [f"{sid} ({sq[sid]}Q)"
                           for sid in sorted(sq, key=lambda x: -sq[x])]

            # If the user just clicked a row in the table above, override the
            # dropdown's session state to that seller BEFORE rendering it.
            # Setting session_state["dd_seller"] after the widget has rendered
            # would have no effect — the override must happen first.
            _jump = st.session_state.pop("_jump_to_seller", None)
            if _jump:
                for _opt in dd_opts:
                    if _opt.startswith(_jump + " ") or _opt == _jump:
                        st.session_state["dd_seller"] = _opt
                        break

            sel_dd = st.selectbox("Select account", dd_opts, key="dd_seller")
        with dd_col2:
            dd_period = st.radio("Usage period", ["1W", "1M", "3M", "YTD"], index=2,
                                 horizontal=False, key="dd_period")

        if sel_dd:
            sel_sid  = sel_dd.split(" (")[0]
            acct_rows = (eval_processed[eval_processed["_seller"] == sel_sid].copy()
                         if not eval_processed.empty
                         else pd.DataFrame())
            if acct_rows.empty:
                st.info(
                    f"⚠️ No Q&A logs found for **{sel_sid}** in the Evaluation_sheet. "
                    f"This seller exists in User_State (so they have an account record) "
                    f"but every logged query was either 'Loading…' or empty — meaning "
                    f"Hoppr never captured a completed response for them. "
                    f"Showing User_State summary below."
                )
            us = {}
            if not raw_user_state.empty:
                for i in range(len(raw_user_state)):
                    v = [str(x).strip() if pd.notna(x) else "" for x in raw_user_state.iloc[i].values]
                    if v[0] == sel_sid:
                        us = {"summary": v[6] if len(v) > 6 else "",
                              "bucket":  v[7] if len(v) > 7 else "",
                              "action":  v[8] if len(v) > 8 else "",
                              "reason":  v[9] if len(v) > 9 else ""}
                        break

            # Safe access — acct_rows may be empty or column-less
            if acct_rows.empty or "_email" not in acct_rows.columns:
                emails = []
                all_dates = []
            else:
                emails    = [e for e in acct_rows["_email"].unique() if e and e != "nan"]
                all_dates = sorted(acct_rows["_date"].dropna().unique())
            first_date = str(all_dates[0])[:10]  if all_dates else "—"
            last_date  = str(all_dates[-1])[:10] if all_dates else "—"

            # Fallback to User_State values when no eval rows
            sel_seller_meta = next((s for s in sellers if s["seller_id"] == sel_sid), {})
            display_total = (len(acct_rows) if not acct_rows.empty
                             else sel_seller_meta.get("q_total", 0))
            display_users = (len(emails) if emails
                             else sel_seller_meta.get("user_count", 1))
            if last_date == "—" and sel_seller_meta.get("last_active"):
                last_date = sel_seller_meta["last_active"]

            kk1, kk2, kk3, kk4, kk5 = st.columns(5)
            with kk1: st.metric("Total Queries", display_total)
            with kk2: st.metric("Users", display_users)
            with kk3: st.metric("First Active", first_date)
            with kk4: st.metric("Last Active", last_date)
            with kk5: st.metric("Classification", us.get("bucket", "—") or "—")

            if us.get("action"):
                st.info(f"**Recommended Action:** {us['action'][:400]}")

            acct_f = apply_period(acct_rows, dd_period)
            if not acct_f.empty:
                st.markdown("#### 📈 Usage Over Time")
                daily_s = acct_f.groupby("_date").agg(
                    Queries=("_question", "count"), Users=("_email", "nunique")
                ).reset_index().rename(columns={"_date": "Date"})
                fig_u = go.Figure()
                fig_u.add_trace(go.Bar(x=daily_s["Date"], y=daily_s["Queries"],
                                       name="Queries", marker_color="#4F46E5"))
                fig_u.add_trace(go.Scatter(x=daily_s["Date"], y=daily_s["Users"],
                                           name="Users", mode="lines+markers",
                                           line=dict(color="#10B981", width=2), yaxis="y2"))
                fig_u.update_layout(height=260, template="plotly_dark",
                                    margin=dict(l=20, r=50, t=20, b=20),
                                    yaxis=dict(title="Queries"),
                                    yaxis2=dict(title="Users", overlaying="y", side="right"),
                                    legend=dict(orientation="h", y=1.12))
                st.plotly_chart(fig_u, use_container_width=True)

            st.markdown("#### 👥 Users")
            user_rows = []
            for em in emails:
                em_rows  = acct_rows[acct_rows["_email"] == em]
                em_dates = sorted(em_rows["_date"].dropna().unique())
                top_types = pd.Series([t for q in em_rows["_question"]
                                       for t in classify_question(q)]).value_counts().index.tolist()[:3]
                user_rows.append({
                    "Email": em, "Queries": len(em_rows),
                    "Question Types": ", ".join(top_types),
                    "First Active": str(em_dates[0])[:10]  if em_dates else "—",
                    "Last Active":  str(em_dates[-1])[:10] if em_dates else "—",
                })
            user_rows.sort(key=lambda x: -x["Queries"])
            if user_rows:
                st.dataframe(pd.DataFrame(user_rows), use_container_width=True, hide_index=True)
            else:
                st.info("No user email data found for this account.")

            if us.get("summary") or us.get("reason"):
                st.markdown("#### 🧠 AI Analysis")
                col_s, col_a = st.columns(2)
                with col_s:
                    st.markdown("**What they're asking about:**")
                    st.markdown(us.get("summary", "—")[:2000])
                with col_a:
                    st.markdown("**Answer quality:**")
                    st.markdown(us.get("reason", "—")[:2000])

            # ── Prompt Quality Scorecard ──────────────────────────────────────
            st.markdown("#### 🎯 Prompt Quality Scorecard")
            scored_acct = acct_f[acct_f["_prompt_tier"] != "Empty"] \
                          if "_prompt_tier" in acct_f.columns else pd.DataFrame()
            if scored_acct.empty:
                st.info("Not enough scoreable prompts in this period.")
            else:
                avg_score = scored_acct["_prompt_score"].mean()
                tier_counts = scored_acct["_prompt_tier"].value_counts()
                n_strong = int(tier_counts.get("Strong", 0))
                n_decent = int(tier_counts.get("Decent", 0))
                n_weak   = int(tier_counts.get("Weak", 0))
                n_vague  = int(tier_counts.get("Vague", 0))
                n_total  = len(scored_acct)

                if   avg_score >= 70: overall = ("Strong", "#10B981")
                elif avg_score >= 45: overall = ("Decent", "#06B6D4")
                elif avg_score >= 20: overall = ("Weak",   "#F59E0B")
                else:                 overall = ("Vague",  "#EF4444")

                ps1, ps2, ps3, ps4, ps5 = st.columns(5)
                with ps1:
                    st.markdown(
                        f"<div style='font-size:0.85rem;color:#9CA3AF;margin-bottom:4px'>Avg Quality</div>"
                        f"<div style='font-size:2.4rem;font-weight:700;color:{overall[1]};line-height:1'>"
                        f"{avg_score:.0f}<span style='font-size:1rem;color:#6B7280'>/100</span></div>"
                        f"<div style='font-size:0.9rem;color:{overall[1]};font-weight:600'>{overall[0]}</div>",
                        unsafe_allow_html=True,
                    )
                with ps2: st.metric("Strong (≥70)", n_strong, f"{n_strong/n_total*100:.0f}%" if n_total else "—")
                with ps3: st.metric("Decent (45-69)", n_decent, f"{n_decent/n_total*100:.0f}%" if n_total else "—")
                with ps4: st.metric("Weak (20-44)", n_weak, f"{n_weak/n_total*100:.0f}%" if n_total else "—")
                with ps5: st.metric("Vague (<20)", n_vague, f"{n_vague/n_total*100:.0f}%" if n_total else "—",
                                    delta_color="inverse")

                # Distribution bar
                tier_df = pd.DataFrame({
                    "Tier": ["Vague", "Weak", "Decent", "Strong"],
                    "Count": [n_vague, n_weak, n_decent, n_strong],
                })
                fig_tier = px.bar(
                    tier_df, x="Count", y="Tier", orientation="h",
                    color="Tier",
                    color_discrete_map={"Strong": "#10B981", "Decent": "#06B6D4",
                                        "Weak": "#F59E0B", "Vague": "#EF4444"},
                    labels={"Count": "Queries", "Tier": ""},
                )
                fig_tier.update_layout(height=180, template="plotly_dark",
                                       margin=dict(l=20, r=20, t=10, b=20),
                                       showlegend=False)
                st.plotly_chart(fig_tier, use_container_width=True)

                # ── Intent breakdown (Factual / Diagnostic / Strategic) ───
                if "_prompt_intent" in scored_acct.columns:
                    intent_rows = scored_acct[scored_acct["_prompt_intent"] != "Unclear"]
                    if not intent_rows.empty:
                        ic = intent_rows["_prompt_intent"].value_counts()
                        n_fact = int(ic.get("Factual", 0))
                        n_diag = int(ic.get("Diagnostic", 0))
                        n_strat = int(ic.get("Strategic", 0))
                        n_i_total = n_fact + n_diag + n_strat
                        st.markdown("**Question intent**")
                        ic1, ic2, ic3 = st.columns(3)
                        with ic1: st.metric("Factual",    n_fact,  f"{n_fact/n_i_total*100:.0f}%"  if n_i_total else "—")
                        with ic2: st.metric("Diagnostic", n_diag,  f"{n_diag/n_i_total*100:.0f}%"  if n_i_total else "—")
                        with ic3: st.metric("Strategic",  n_strat, f"{n_strat/n_i_total*100:.0f}%" if n_i_total else "—")
                        intent_df = pd.DataFrame({
                            "Intent": ["Factual", "Diagnostic", "Strategic"],
                            "Count":  [n_fact, n_diag, n_strat],
                        })
                        fig_intent = px.bar(
                            intent_df, x="Count", y="Intent", orientation="h",
                            color="Intent",
                            color_discrete_map={"Factual": "#9CA3AF",
                                                "Diagnostic": "#F59E0B",
                                                "Strategic": "#A78BFA"},
                            labels={"Count": "Queries", "Intent": ""},
                        )
                        fig_intent.update_layout(height=160, template="plotly_dark",
                                                 margin=dict(l=20, r=20, t=10, b=20),
                                                 showlegend=False)
                        st.plotly_chart(fig_intent, use_container_width=True)

                # Examples — best + worst prompts (theme-adaptive colors)
                def _score_md(score):
                    s = int(score)
                    if s >= 70: return f":green[**{s}**]"
                    if s >= 45: return f":blue[**{s}**]"
                    if s >= 20: return f":orange[**{s}**]"
                    return f":red[**{s}**]"

                col_best, col_worst = st.columns(2)
                with col_best:
                    st.markdown("**🟢 Strongest prompts**")
                    best = (scored_acct.sort_values("_prompt_score", ascending=False)
                            .drop_duplicates(subset=["_question"]).head(5))
                    if best.empty:
                        st.caption("—")
                    else:
                        for _, r in best.iterrows():
                            q = str(r["_question"]).strip()
                            st.markdown(f"{_score_md(r['_prompt_score'])} &nbsp; {q[:200]}")
                with col_worst:
                    st.markdown("**🔴 Vaguest prompts**")
                    worst = (scored_acct.sort_values("_prompt_score", ascending=True)
                             .drop_duplicates(subset=["_question"]).head(5))
                    if worst.empty:
                        st.caption("—")
                    else:
                        for _, r in worst.iterrows():
                            q = str(r["_question"]).strip()
                            st.markdown(f"{_score_md(r['_prompt_score'])} &nbsp; {q[:200]}")
                st.caption("Score is based on: metric (revenue/ROAS/units), "
                           "timeframe (March, last week, YoY), entity (SKU/channel/country), "
                           "comparison (vs/growth). Pure follow-ups and very short prompts are capped.")

            st.markdown("#### 📋 Query Timeline")
            # Guard: when the selected seller has no eval rows (or the period
            # filter wiped them all) acct_f is empty and lacks `_date`. Skip
            # the whole timeline block rather than crashing on sort_values.
            if acct_f.empty or "_date" not in acct_f.columns:
                st.caption(
                    "No Q&A logs with timestamps for this seller in the "
                    "selected period. Widen the period above (3M / All) if "
                    "you expected to see rows."
                )
            else:
                timeline_all = acct_f.sort_values("_date", ascending=False)

                # Split rows into 3 buckets:
                #   answered      — both Q and A captured (the useful ones)
                #   no_answer     — Q captured but Hoppr never logged an answer
                #   no_question   — Q itself was Loading... (shouldn't happen post-filter, but safe)
                _q = timeline_all["_question"].astype(str).str.strip().str.lower()
                _a = timeline_all["_answer"].astype(str).str.strip().str.lower()
                _empty = ["loading...", "loading", "", "nan"]
                no_question_mask = _q.isin(_empty)
                no_answer_mask   = (~no_question_mask) & _a.isin(_empty)
                answered_mask    = (~no_question_mask) & (~no_answer_mask)

                no_answer_rows = timeline_all[no_answer_mask]
                timeline       = timeline_all[answered_mask].head(100)

                # Single clean banner instead of per-row warnings
                if len(no_answer_rows) > 0:
                    pct = len(no_answer_rows) / max(1, len(timeline_all)) * 100
                    st.warning(
                        f"⚠️ **Hoppr logging issue:** {len(no_answer_rows)} of "
                        f"{len(timeline_all)} queries ({pct:.0f}%) have a question "
                        f"but no captured answer. The questions show in analytics; "
                        f"the answers are missing from the sheet (Hoppr team to fix)."
                    )
                    with st.expander(f"Show the {len(no_answer_rows)} questions with no captured answer"):
                        for _, qrow in no_answer_rows.head(50).iterrows():
                            dt = str(qrow["_date"])[:10]
                            em = str(qrow["_email"]).split("@")[0]
                            st.caption(f"• {dt} — {em} — {str(qrow['_question'])[:200]}")

                for _, qrow in timeline.iterrows():
                    dt       = str(qrow["_date"])[:10]
                    em       = str(qrow["_email"])
                    question = str(qrow["_question"])
                    answer   = str(qrow["_answer"])
                    has_data = any(c in answer for c in ["📊", "|", "%", "table", "##"])
                    failed   = any(w in answer.lower() for w in
                                   ["unable", "don't have", "not available", "cannot provide", "no data"])
                    acc_flag = "🔴 " if is_accuracy(question) else ""
                    if failed:    status = "⚠️"
                    elif has_data: status = "✅"
                    else:          status = "➡️"
                    em_short = em.split("@")[0] if "@" in em else em
                    q_short = question[:120] + ("…" if len(question) > 120 else "")
                    with st.expander(f"{acc_flag}{status} {dt} — **{em_short}** — {q_short}"):
                        st.markdown(f"**Q:** {question}")
                        st.markdown("**A:**")
                        if len(answer) > 800:
                            st.markdown(answer[:800] + "…")
                            with st.expander("Show full answer"):
                                st.markdown(answer)
                        else:
                            st.markdown(answer)
                if len(timeline) == 100 and answered_mask.sum() > 100:
                    st.caption(f"Showing most recent 100 of {int(answered_mask.sum())} answered queries.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — ASK HOPPR
# ══════════════════════════════════════════════════════════════════════════════

with tab_ask:
    st.markdown("### 💬 Ask Hoppr")
    st.caption("Ask anything about Hoppr usage, seller health, query trends, or data quality.")

    # ── Live data status (always visible) ────────────────────────────────────
    _has_sellers = len(sellers) > 0
    _has_eval    = not eval_processed.empty
    _eval_rows   = len(eval_processed) if _has_eval else 0

    _diag_cols = st.columns(4)
    with _diag_cols[0]:
        st.metric("Sellers loaded", len(sellers), help="From User_State tab")
    with _diag_cols[1]:
        st.metric("Q&A rows loaded", _eval_rows, help="From Evaluation_sheet tab")
    with _diag_cols[2]:
        _eq = "✅ question col" if q_col_e else "❌ no question col"
        _ea = "✅ answer col" if a_col_e else "❌ no answer col"
        st.metric("Eval columns", "OK" if q_col_e and a_col_e else "MISSING")
    with _diag_cols[3]:
        if _err_eval:
            st.error(f"Eval error: {_err_eval[:80]}")
        elif not _has_eval and not _err_eval:
            st.warning("Eval sheet: empty or col mismatch")
        else:
            st.success("Eval sheet: OK")

    if q_col_e or a_col_e:
        st.caption(f"Column mapping: question=`{q_col_e}` | answer=`{a_col_e}` | "
                   f"seller=`{sid_col_e}` | date=`{date_col_e}` | email=`{email_col_e}`")
    elif not raw_eval.empty:
        st.warning(f"⚠️ Evaluation_sheet loaded ({len(raw_eval)} rows) but couldn't identify "
                   f"question/answer columns. Columns found: `{list(raw_eval.columns)}`")

    st.markdown("---")

    if not ANTHROPIC_API_KEY:
        st.warning("Add `ANTHROPIC_API_KEY` to `.streamlit/secrets.toml` to enable Ask Hoppr.")
    else:
        # ── Context builder ───────────────────────────────────────────────────
        def _build_hoppr_context(_daily, _sellers_list, _eval_df):
            lines = []
            if not _daily.empty:
                lines.append(f"DATA RANGE: {_daily['date'].min().date()} → {_daily['date'].max().date()}")
                lines.append(f"TOTAL QUERIES (all time): {int(_daily['total_queries'].sum())}")
                today_ts = _daily["date"].max()
                wk  = _daily[_daily["date"] >= today_ts - pd.Timedelta(days=7)]
                pwk = _daily[(_daily["date"] >= today_ts - pd.Timedelta(days=14)) &
                             (_daily["date"] <  today_ts - pd.Timedelta(days=7))]
                wq, pq = int(wk["total_queries"].sum()), int(pwk["total_queries"].sum())
                wow = f"{(wq-pq)/pq*100:+.0f}%" if pq else "N/A"
                lines.append(f"LAST 7 DAYS: {wq} queries ({wow} WoW), "
                             f"{int(wk['unique_sellers'].sum())} sellers, "
                             f"{int(wk['unique_users'].sum())} users")
            if _sellers_list:
                sdf = pd.DataFrame(_sellers_list)
                lines.append(f"\nSELLERS: {len(sdf)} total | "
                             f"Active ≤7d: {len(sdf[sdf['days_silent'] <= 7])} | "
                             f"Power Users: {len(sdf[sdf['classification'] == 'Power User'])} | "
                             f"Sales-Ready: {len(sdf[sdf['classification'] == 'Sales-Ready'])} | "
                             f"Going Quiet: {len(sdf[sdf['trend'] == 'Going Quiet'])} | "
                             f"Churned: {len(sdf[sdf['trend'] == 'Churned'])}")
                lines.append("\nALL SELLERS:")
                for _, r in sdf.sort_values("q_total", ascending=False).iterrows():
                    qs  = str(r.get("q_summary", "")).strip()
                    act = str(r.get("action", "")).strip()
                    aq  = str(r.get("a_summary", "")).strip()
                    pq  = r.get("prompt_quality", None)
                    pq_str = (f" | PromptQ {int(pq)}/100"
                              if pq is not None and not pd.isna(pq) else "")
                    parts = [f"  {r['seller_id']} | {r['email']} | {r['q_total']}Q total | "
                             f"{r['q_recent']}Q(7d) | {r['classification']} | "
                             f"{r['trend']} | {r['days_silent']}d silent{pq_str}"]
                    if qs and qs != "nan":
                        parts.append(f"    What they ask: {qs[:250]}")
                    if aq and aq != "nan":
                        parts.append(f"    Answer quality: {aq[:200]}")
                    if act and act != "nan":
                        parts.append(f"    Recommended action: {act[:150]}")
                    lines.extend(parts)
            if not _eval_df.empty and "_buckets" in _eval_df.columns:
                all_b = [b for bl in _eval_df["_buckets"] for b in bl]
                lines.append(f"\nQUESTION TYPES (all time):")
                for bucket, cnt in Counter(all_b).most_common(10):
                    lines.append(f"  {bucket}: {cnt}")
            if not _eval_df.empty and "_is_accuracy" in _eval_df.columns:
                acc = int(_eval_df["_is_accuracy"].sum())
                tot = len(_eval_df)
                lines.append(f"\nDATA ACCURACY ISSUES: {acc} of {tot} queries "
                             f"({acc/tot*100:.1f}%)")
                if acc:
                    top_acc = (_eval_df[_eval_df["_is_accuracy"]]
                               ["_seller"].value_counts().head(10))
                    lines.append("  Top sellers flagging accuracy issues:")
                    for sid, cnt in top_acc.items():
                        lines.append(f"    {sid}: {cnt}")
            return "\n".join(lines)

        ctx = _build_hoppr_context(
            daily if not daily.empty else pd.DataFrame(),
            sellers,
            eval_processed,
        )

        eval_status = (f"✅ {_eval_rows} Q&A rows loaded from Evaluation_sheet"
                       if _has_eval else
                       "⚠️ Evaluation_sheet did not load — individual query/response "
                       "data is unavailable. Seller summaries from User_State are available.")

        HOPPR_SYSTEM = f"""You are Ask Hoppr — an AI analyst for the Graas Sales Hub.

CRITICAL: All Hoppr data is pre-loaded into this system prompt. You ALREADY have the data.
- DO NOT say you cannot access Google Sheets or URLs — you don't need to, the data is here.
- DO NOT ask the user to paste data — it is already in your context below.
- If a user pastes a Google Sheets URL, tell them you already have the data and answer directly.
- To find a seller by company name, match their email domain (e.g. "paula's choice" → paulaschoice → @paulaschoice.vn → seller AAIDF).

Data availability: {eval_status}

Answer questions by referencing the data below. Be specific — use seller IDs, emails, dates, and exact query text where available.

=== CURRENT DATA SNAPSHOT ===
{ctx}
=== END SNAPSHOT ==="""

        def _get_seller_detail(seller_id: str, eval_df: pd.DataFrame) -> str:
            """Return full Q+A log for a seller."""
            if eval_df.empty or "_seller" not in eval_df.columns:
                return ""
            rows = eval_df[eval_df["_seller"] == seller_id].sort_values("_date")
            if rows.empty:
                return ""
            out = [f"\n===== FULL Q&A LOG: {seller_id} ({len(rows)} queries) ====="]
            for email, grp in rows.groupby("_email", sort=False):
                em = str(email)
                if not em or em == "nan":
                    continue
                out.append(f"\n  USER: {em} ({len(grp)} queries)")
                for _, r in grp.sort_values("_date").iterrows():
                    dt  = str(r["_date"])[:10]
                    q   = str(r["_question"])
                    a   = str(r.get("_answer", "")) if "_answer" in r.index else ""
                    acc = " [DATA ACCURACY ISSUE]" if is_accuracy(q) else ""
                    out.append(f"\n    [{dt}]{acc}")
                    out.append(f"    Q: {q}")
                    out.append(f"    A: {a[:1200] if a and a.strip() and a != 'nan' else '(no response recorded)'}")
            out.append("\n===== END =====")
            return "\n".join(out)

        def _detect_sellers(text: str) -> list:
            """Find seller IDs mentioned in text by ID or company name / email domain."""
            text_upper = text.upper()
            text_norm  = re.sub(r"[^a-z0-9]", "", text.lower())
            found = set()
            for s in sellers:
                sid = s["seller_id"]
                if len(sid) >= 3 and sid in text_upper:
                    found.add(sid); continue
                for em in [s.get("email", "")] + s.get("all_emails", []):
                    if em and "@" in em:
                        dp = re.sub(r"[^a-z0-9]", "",
                                    em.split("@")[1].split(".")[0].lower())
                        if len(dp) >= 4 and dp in text_norm:
                            found.add(sid); break
            return list(found)

        def _detect_sellers_from_history(current_msg: str, history: list) -> list:
            """Scan current message AND recent conversation history for seller mentions.
            This ensures follow-up questions ('show me their queries') work after the
            seller was established earlier in the conversation."""
            # Combine current message with last 10 messages of history
            all_text = current_msg + " " + " ".join(
                m["content"] for m in history[-10:]
            )
            return _detect_sellers(all_text)

        if "hoppr_chat" not in st.session_state:
            st.session_state.hoppr_chat = []

        # Example prompts
        st.markdown("**Try asking:**")
        hcols = st.columns(4)
        for i, ep in enumerate([
            "Show all queries for AAIDF (Paula's Choice)",
            "Which sellers are going quiet this week?",
            "What are the top question types?",
            "Who are the top 5 sellers by query volume?",
        ]):
            with hcols[i]:
                if st.button(ep, key=f"hq_{i}", use_container_width=True):
                    st.session_state["hoppr_prefill"] = ep

        for msg in st.session_state.hoppr_chat:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        user_q = st.chat_input("Ask about Hoppr usage, sellers, or data quality...")
        if "hoppr_prefill" in st.session_state:
            user_q = st.session_state.pop("hoppr_prefill")

        if user_q:
            st.session_state.hoppr_chat.append({"role": "user", "content": user_q})
            with st.chat_message("user"):
                st.markdown(user_q)
            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    try:
                        import anthropic as _anthropic
                        mentioned = _detect_sellers_from_history(
                            user_q, st.session_state.hoppr_chat
                        )
                        extra = ""
                        if mentioned:
                            for sid in mentioned[:3]:
                                detail = _get_seller_detail(sid, eval_processed)
                                if detail:
                                    extra += detail
                                else:
                                    # eval not loaded — inject full seller info from User_State
                                    s_info = next((s for s in sellers
                                                   if s["seller_id"] == sid), None)
                                    if s_info:
                                        extra += (
                                            f"\n===== SELLER INFO: {sid} =====\n"
                                            f"Email: {s_info.get('email','')}\n"
                                            f"All users: {s_info.get('all_emails', [])}\n"
                                            f"Total queries: {s_info.get('q_total',0)}\n"
                                            f"Recent (7d): {s_info.get('q_recent',0)}\n"
                                            f"Classification: {s_info.get('classification','')}\n"
                                            f"Trend: {s_info.get('trend','')}\n"
                                            f"Last active: {s_info.get('last_active','')}\n"
                                            f"What they ask: {s_info.get('q_summary','')}\n"
                                            f"Answer quality: {s_info.get('a_summary','')}\n"
                                            f"Recommended action: {s_info.get('action','')}\n"
                                            f"NOTE: Individual Q&A rows not available "
                                            f"(Evaluation_sheet failed to load).\n"
                                            f"===== END =====\n"
                                        )
                        system = HOPPR_SYSTEM
                        if extra:
                            system += f"\n\n=== DETAILED DATA FOR MENTIONED SELLERS ===\n{extra}"
                        ai = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                        result = ai.messages.create(
                            model="claude-sonnet-4-6",
                            max_tokens=2048,
                            system=system,
                            messages=[{"role": m["role"], "content": m["content"]}
                                      for m in st.session_state.hoppr_chat[-20:]],
                        )
                        response = result.content[0].text
                    except Exception as e:
                        response = f"Error calling AI: {e}"
                st.markdown(response)
                st.session_state.hoppr_chat.append({"role": "assistant", "content": response})

        if st.session_state.hoppr_chat:
            if st.button("🗑️ Clear chat", key="clear_hoppr_chat"):
                st.session_state.hoppr_chat = []
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — MCP BETA
#   Renders services/mcp_beta_view.py inline. Kept as a sub-tab (not its own
#   sidebar page) because audience + warehouse overlap with Hoppr.
# ══════════════════════════════════════════════════════════════════════════════

with tab_mcp:
    from services.mcp_beta_view import render as _render_mcp_beta
    _render_mcp_beta()
