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
from datetime import datetime as _dt

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

st.markdown("## 📊 Hoppr")


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
    from services.sheets_client import fetch_sheet_tab
    try:
        df = fetch_sheet_tab(HOPPR_SHEET_ID, "Evaluation_sheet")
        return df if not df.empty else pd.DataFrame(), None
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl=1800)
def load_user_state():
    from services.sheets_client import fetch_sheet_tab
    try:
        df = fetch_sheet_tab(HOPPR_SHEET_ID, "User_State")
        return df if not df.empty else pd.DataFrame(), None
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl=3600)
def load_funnel():
    from services.sheets_client import fetch_sheet_tab
    try:
        df = fetch_sheet_tab(HOPPR_SHEET_ID, "Final Funnel")
        return df if not df.empty else pd.DataFrame(), None
    except Exception as e:
        return pd.DataFrame(), str(e)

# ── Fetch ─────────────────────────────────────────────────────────────────────

raw_daily,      _err_daily      = load_hoppr_daily()
raw_eval,       _err_eval       = load_evaluation_sheet()
raw_user_state, _err_user_state = load_user_state()
raw_funnel,     _err_funnel     = load_funnel()

# ── Data status ───────────────────────────────────────────────────────────────
with st.expander("🔍 Data Status (click to hide)", expanded=True):
    def _status(label, df, err, extra=""):
        if err:
            st.error(f"❌ **{label}**: {err}")
        elif df.empty:
            st.warning(f"⚠️ **{label}**: loaded but empty")
        else:
            st.success(f"✅ **{label}**: {len(df)} rows, {len(df.columns)} cols{extra}")
    _status("Hoppr__Anaysis (daily)",  raw_daily,      _err_daily)
    _status("Evaluation_sheet (Q&A)",  raw_eval,       _err_eval,
            f" | cols: {list(raw_eval.columns[:10])}" if not raw_eval.empty else "")
    _status("User_State (accounts)",   raw_user_state, _err_user_state)
    _status("Final Funnel",            raw_funnel,     _err_funnel)
    st.caption(f"Sheet ID: `{HOPPR_SHEET_ID}`")
    if "_loading_rows_filtered" in st.session_state:
        n_load = st.session_state["_loading_rows_filtered"]
        if n_load > 0:
            st.caption(f"🚫 Filtered out **{n_load}** 'Loading…' rows "
                       f"(Hoppr logged before response completed — noise, "
                       f"excluded from analytics & charts)")
    if "eval_col_debug" in st.session_state:
        st.code(st.session_state["eval_col_debug"], language=None)

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


# ══════════════════════════════════════════════════════════════════════════════
# QUESTION CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

ACCURACY_KEYWORDS = [
    "wrong", "incorrect", "inaccurate", "not matching", "doesn't match",
    "mismatch", "missing data", "no data", "data not", "data accuracy",
    "data quality", "data issue", "different from", "discrepancy",
    "not available", "not showing", "showing wrong", "can't find",
    "cannot find", "not found",
]

QUESTION_BUCKETS = {
    # ── 4 meta-categories the team tracks ─────────────────────────────────────
    "Revenue & GMV/NMV": [
        "gmv", "nmv", "revenue", "sales", "orders", "gross merchandise",
        "net merchandise", "nett merchandise", "gross revenue", "net revenue",
        "gross sales", "net sales", "aov", "average order value", "conversion",
        "checkout", "purchase", "transaction", "top line", "topline",
        "income", "earning", "profit", "margin", "growth", "selling",
        "total sales", "total revenue", "monthly sales", "daily sales",
        "weekly sales", "sale performance", "sales performance",
        "cancellation", "cancellations", "cancelled", "canceled",
        "refund", "refunds", "refunded", "return rate", "returned order",
    ],
    "Ads, Traffic & ROAS": [
        "roas", "return on ad", "campaign", "paid", "advertisement",
        " ad ", " ads ", "cpc", "cpa", "ctr", "click-through",
        "traffic", "visitor", "visit", "session", "pageview", "page view",
        "impression", "reach", "ad spend", "budget", "marketing spend",
        "facebook ads", "google ads", "tiktok ads", "meta ads", "shopee ads",
        "lazada ads", "sponsored", "search ads", "display ads",
    ],
    "SKU & Products": [
        "sku", "product", "listing", "catalogue", "catalog", "item",
        "variant", "inventory", "stock", "category", "brand",
        "bestseller", "best seller", "best selling", "top product",
        "top selling", "top sku", "hero product", "slow moving",
        "new product", "out of stock",
        "units", "units sold", "quantity sold", "qty sold", "sold",
        "pieces sold", "pcs sold",
    ],
    "Downloads & Exports": [
        "download", "export", "excel", "csv", "spreadsheet", "sheet",
        "file", "data export", "extract", "pull data", "get data",
        "raw data", "data download", "generate report", "download report",
        "export data", "download data",
    ],
    # ── Supporting buckets to absorb common "General" content ──────────────────
    "Performance & Trends": [
        "trend", "trending", "drop", "decline", "fell", "decreased", "decreasing",
        "increase", "increased", "increasing", "grow", "growing", "growth",
        "yesterday", "last week", "this week", "last month", "this month", "today",
        "last 7 days", "last 30 days", "past week", "past month",
        "week on week", "week-on-week", "wow", "month on month", "month-on-month",
        "mom", "yoy", "year on year", "year-on-year", "last year",
        "how is", "how was", "how are", "how's", "how am i",
        "why did", "why is", "why are", "what happened", "what's happening",
        "performance", "performing", "recent", "lately", "over time", "historical",
    ],
    "Channels & Marketplaces": [
        "shopee", "lazada", "tiktok shop", "tiktok", "tokopedia", "amazon",
        "qoo10", "blibli", "bukalapak", "shopify", "woocommerce", "magento",
        "marketplace", "marketplaces", "channel", "channels", "platform",
    ],
    "Customers & Buyers": [
        "customer", "customers", "buyer", "buyers", "shopper", "shoppers",
        "audience", "consumer", "consumers", "repeat", "returning", "loyalty",
        "retention", "new customer", "user base", "demographics", "demographic",
        "age group", "gender split",
    ],
    "Affiliates & Creators": [
        "affiliate", "affiliates", "kol", "kols", "creator", "creators",
        "influencer", "influencers", "commission", "ambassador", "ambassadors",
        "livestream", "live stream", "live-stream", "live streaming",
        "livestreaming", "ugc",
    ],
    "Competitors": [
        "competitor", "competitors", "competition", "compete", "competing",
        "market share", "peer", "peers", "rival", "rivals",
        "against other", "other brand", "other brands", "vs other",
        "benchmark", "benchmarks", "industry average", "industry avg",
        "category leader", "category benchmark",
    ],
    "About the Data": [
        "what period", "what time period", "which period",
        "what date range", "what time range", "which date range",
        "what month", "which month", "what year", "which year",
        "data start", "data starts", "starts from", "start from",
        "data range", "date range", "time range",
        "how recent", "how current", "how old", "how fresh",
        "up to date", "up-to-date", "last updated", "freshness",
        "give me insights", "give insights", "any insights",
        "create chart", "make chart", "show me chart", "show me a chart",
        "build chart", "draw chart", "plot chart",
        "about the data", "about this data", "what data",
        "which data", "data you have", "data you analyze",
        "data available", "what's available",
    ],
    # ── Additional signal ──────────────────────────────────────────────────────
    "Data Accuracy":    ACCURACY_KEYWORDS,
}

def classify_question(q: str) -> list:
    ql = q.lower()
    tags = [b for b, kws in QUESTION_BUCKETS.items() if any(kw in ql for kw in kws)]
    return tags if tags else ["General"]

def is_accuracy(q: str) -> bool:
    return any(kw in q.lower() for kw in ACCURACY_KEYWORDS)


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
# PRE-PROCESS EVAL SHEET
# ══════════════════════════════════════════════════════════════════════════════

eval_processed = pd.DataFrame()
sid_col_e = email_col_e = date_col_e = q_col_e = a_col_e = None

if not raw_eval.empty:
    edf = raw_eval.copy()
    ecols = [str(c).strip() for c in edf.columns]
    edf.columns = ecols

    # ── Named column detection (broad) ────────────────────────────────────────
    sid_col_e = (
        next((c for c in ecols if "seller" in c.lower() and "id" in c.lower()), None)
        or next((c for c in ecols if c.lower() in ("seller", "seller_id", "account")), None)
    )
    email_col_e = next((c for c in ecols if "email" in c.lower()), None)
    date_col_e = (
        next((c for c in ecols if c.strip().lower() == "date"), None)
        or next((c for c in ecols if "date" in c.lower() or "timestamp" in c.lower()), None)
    )
    q_col_e = (
        next((c for c in ecols if "question" in c.lower()), None)
        or next((c for c in ecols if "query" in c.lower() and "count" not in c.lower()), None)
        or next((c for c in ecols if "user_input" in c.lower() or "user_message" in c.lower()), None)
        or next((c for c in ecols if c.lower() in ("input", "message", "prompt")), None)
    )
    a_col_e = (
        next((c for c in ecols if "answer" in c.lower()), None)
        or next((c for c in ecols if "response" in c.lower() or "reply" in c.lower()), None)
        or next((c for c in ecols if "output" in c.lower() or "bot_message" in c.lower()), None)
        or next((c for c in ecols if "ai" in c.lower() and "response" not in c.lower()
                 and c.lower() not in ("ai",)), None)
    )

    # ── Positional / content fallback — if named detection failed ─────────────
    # Use MAX length (not avg) — many "Loading..." rows drag avg down for response col.
    # The Hoppr response is always multi-KB markdown, so its max is always highest.
    if q_col_e is None or a_col_e is None:
        known = {c for c in [sid_col_e, email_col_e, date_col_e, q_col_e] if c}
        str_cols = []
        for c in ecols:
            if c in known:
                continue
            try:
                max_len = edf[c].astype(str).str.len().max()
                if max_len > 30:  # skip truly short / numeric cols
                    str_cols.append((c, max_len))
            except Exception:
                pass
        str_cols.sort(key=lambda x: x[1])  # ascending max length
        if len(str_cols) >= 2 and q_col_e is None:
            q_col_e = str_cols[-2][0]   # 2nd-longest max = query
        if len(str_cols) >= 1 and a_col_e is None:
            a_col_e = str_cols[-1][0]   # longest max = Hoppr response

    # ── Index fallback — user confirmed: col F (idx 5) = question, col G (idx 6) = answer
    if q_col_e is None and len(ecols) > 5:
        q_col_e = ecols[5]
    if a_col_e is None and len(ecols) > 6:
        a_col_e = ecols[6]

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
        eval_processed = edf


# ══════════════════════════════════════════════════════════════════════════════
# PARSE SELLERS FROM USER_STATE
# ══════════════════════════════════════════════════════════════════════════════

sellers = []
seller_users_map = {}

if not raw_user_state.empty:
    _today = _dt.now().date()
    for idx in range(len(raw_user_state)):
        row  = raw_user_state.iloc[idx]
        vals = [str(v).strip() if pd.notna(v) else "" for v in row.values]
        sid  = vals[0]
        if not sid or sid in ("user_key", "") or not re.match(r'^[A-Z0-9]{2,10}$', sid):
            continue
        email     = vals[2] if len(vals) > 2 else ""
        last_seen = vals[3] if len(vals) > 3 else ""
        try:    q_total = int(float(vals[4])) if len(vals) > 4 and vals[4] else 0
        except: q_total = 0
        try:    q_7d = int(float(vals[5])) if len(vals) > 5 and vals[5] else 0
        except: q_7d = 0
        days_silent = 999
        if last_seen:
            try:    days_silent = (_today - _dt.strptime(last_seen, "%Y-%m-%d").date()).days
            except: pass
        bucket = vals[7] if len(vals) > 7 else ""
        bl = bucket.lower()
        if "sales" in bl or "ready" in bl: cls = "Sales-Ready"
        elif "power" in bl:                cls = "Power User"
        elif "explor" in bl:               cls = "Explorer"
        elif "block" in bl:                cls = "Blocked"
        else:                              cls = "Low Usage"
        if days_silent <= 1:    trend = "Highly Active"
        elif days_silent <= 7:  trend = "Active"
        elif days_silent <= 30: trend = "Going Quiet"
        else:                   trend = "Churned"
        sellers.append({
            "seller_id": sid, "email": email,
            "q_recent": q_7d, "q_total": q_total,
            "last_active": last_seen, "days_silent": days_silent,
            "trend": trend, "classification": cls,
            "q_summary": vals[6] if len(vals) > 6 else "",
            "a_summary": vals[9] if len(vals) > 9 else "",
            "action":    vals[8] if len(vals) > 8 else "",
        })

if not eval_processed.empty and sellers and "_email" in eval_processed.columns:
    _ev = eval_processed[["_seller", "_email", "_date"]].copy()
    _ev = _ev[_ev["_seller"].notna() & _ev["_email"].notna()]
    _ev = _ev[(_ev["_seller"] != "nan") & (_ev["_email"] != "nan") & (_ev["_email"] != "")]
    for sid, grp in _ev.groupby("_seller", sort=False):
        seller_users_map[sid] = {}
        for em, eg in grp.groupby("_email", sort=False):
            dates = eg["_date"].dropna().dt.strftime("%Y-%m-%d").tolist()
            seller_users_map[sid][em] = {"count": len(eg), "dates": dates}

    # Per-seller avg prompt quality (excluding Empty rows)
    _scored_only = eval_processed[eval_processed["_prompt_tier"] != "Empty"]
    _seller_avg = (_scored_only.groupby("_seller")["_prompt_score"]
                   .mean().round(0).astype(int).to_dict()) if not _scored_only.empty else {}

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
else:
    for s in sellers:
        s.setdefault("user_count", 1)
        s.setdefault("all_emails", [s.get("email", "")])
        s.setdefault("prompt_quality", None)


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
                  "3M": today_ts - pd.Timedelta(days=90)}
    if period in cutoffs:
        return df[df[date_col] >= max(cutoffs[period], data_start)]
    return df


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_home, tab_accounts, tab_ask = st.tabs(["🏠 Home", "👥 Accounts", "💬 Ask Hoppr"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — HOME
# ══════════════════════════════════════════════════════════════════════════════

with tab_home:

    if not daily.empty:
        today_ts  = daily["date"].max()
        this_week = daily[daily["date"] >= today_ts - pd.Timedelta(days=7)]
        last_week = daily[(daily["date"] >= today_ts - pd.Timedelta(days=14)) &
                          (daily["date"] <  today_ts - pd.Timedelta(days=7))]

        def safe_delta(a, b):
            return f"{((a - b) / b * 100):+.0f}%" if b else None

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            tw, lw = this_week["total_queries"].sum(), last_week["total_queries"].sum()
            st.metric("Queries (7d)", f"{tw:,}", safe_delta(tw, lw))
        with c2:
            tw, lw = this_week["unique_users"].sum(), last_week["unique_users"].sum()
            st.metric("Unique Users (7d)", f"{tw:,}", safe_delta(tw, lw))
        with c3:
            tw, lw = this_week["unique_sellers"].sum(), last_week["unique_sellers"].sum()
            st.metric("Unique Sellers (7d)", f"{tw:,}", safe_delta(tw, lw))
        with c4:
            tw, lw = this_week["new_signups"].sum(), last_week["new_signups"].sum()
            st.metric("New Signups (7d)", f"{tw:,}", safe_delta(tw, lw))

    period = st.radio("Period", ["1W", "1M", "3M", "All"], index=1, horizontal=True, key="hoppr_period")

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
                                 mode="lines+markers", name="Queries",
                                 line=dict(color="#4F46E5", width=2)))
        fig.add_trace(go.Bar(x=daily_f["date"], y=daily_f["unique_sellers"],
                             name="Unique Sellers", marker_color="#7C3AED", opacity=0.5))
        fig.add_trace(go.Scatter(x=daily_f["date"], y=daily_f["new_signups"],
                                 mode="lines+markers", name="New Signups",
                                 line=dict(color="#10B981", dash="dot")))
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
        st.markdown("### 📊 What Sellers Are Asking About")
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

    # ── Acquisition funnel ────────────────────────────────────────────────────
    if not raw_funnel.empty:
        with st.expander("🔄 Acquisition Funnel", expanded=False):
            def _si(df, r, c):
                try: return int(float(str(df.iloc[r, c]).replace(",", "").strip()))
                except: return 0
            sv = [(s, v) for s, v in zip(
                ["Chat Visits", "Unique Users", "Signups", "Connect Flow", "Connected"],
                [_si(raw_funnel, 1, 7), _si(raw_funnel, 4, 8), _si(raw_funnel, 9, 7),
                 _si(raw_funnel, 13, 6), _si(raw_funnel, 17, 5)]
            ) if v > 0]
            if sv:
                ss, vv = zip(*sv)
                fig_f = go.Figure(go.Funnel(
                    y=list(ss), x=list(vv), textinfo="value+percent initial",
                    marker=dict(color=["#4F46E5", "#6366F1", "#7C3AED", "#8B5CF6", "#10B981"]),
                ))
                fig_f.update_layout(height=300, template="plotly_dark", margin=dict(l=20, r=20, t=20, b=20))
                st.plotly_chart(fig_f, use_container_width=True)


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

        disp_cols = ["seller_id", "email", "user_count", "q_total", "q_recent",
                     "prompt_quality",
                     "last_active", "days_silent", "trend", "classification"]
        if "prompt_quality" not in filt.columns:
            filt = filt.copy()
            filt["prompt_quality"] = None
        disp = filt[disp_cols].copy()
        disp = disp.sort_values("days_silent")
        def _pq_fmt(v):
            try:
                if v is None or pd.isna(v): return "—"
                return f"{int(v)}"
            except Exception:
                return "—"

        st.dataframe(
            disp.rename(columns={
                "seller_id": "Seller", "email": "Email", "user_count": "Users",
                "q_total": "Total Q", "q_recent": "Q (7d)",
                "prompt_quality": "Prompt Q",
                "last_active": "Last Active", "days_silent": "Days Silent",
                "trend": "Trend", "classification": "Class",
            }).style.map(cls_color, subset=["Class"])
              .map(tr_color, subset=["Trend"])
              .map(pq_color, subset=["Prompt Q"])
              .format({"Prompt Q": _pq_fmt}),
            use_container_width=True, height=380, hide_index=True,
        )
        st.caption("**Prompt Q** is a 0–100 score per seller — Strong ≥70 (green) · Decent 45–69 · Weak 20–44 · Vague <20 (red). Based on whether prompts include a metric, timeframe, entity, and comparison.")

        st.markdown("---")
        st.markdown("### 🔍 Account Detail")

        dd_col1, dd_col2 = st.columns([3, 1])
        with dd_col1:
            if not eval_processed.empty:
                sq = eval_processed["_seller"].value_counts().to_dict()
                dd_opts = [f"{sid} ({sq[sid]}Q)" for sid in sorted(sq, key=lambda x: -sq[x])]
            else:
                dd_opts = [f"{s['seller_id']} ({s['q_total']}Q)"
                           for s in sorted(sellers, key=lambda x: -x.get("q_total", 0))]
            sel_dd = st.selectbox("Select account", dd_opts, key="dd_seller")
        with dd_col2:
            dd_period = st.radio("Usage period", ["1W", "1M", "3M", "All"], index=2,
                                 horizontal=False, key="dd_period")

        if sel_dd and not eval_processed.empty:
            sel_sid  = sel_dd.split(" (")[0]
            acct_rows = eval_processed[eval_processed["_seller"] == sel_sid].copy()
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

            emails    = [e for e in acct_rows["_email"].unique() if e and e != "nan"]
            all_dates = sorted(acct_rows["_date"].dropna().unique())
            first_date = str(all_dates[0])[:10]  if all_dates else "—"
            last_date  = str(all_dates[-1])[:10] if all_dates else "—"

            kk1, kk2, kk3, kk4, kk5 = st.columns(5)
            with kk1: st.metric("Total Queries", len(acct_rows))
            with kk2: st.metric("Users", len(emails))
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

                # Examples — best + worst prompts
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
                            st.markdown(
                                f"<div style='font-size:0.85rem;margin-bottom:6px'>"
                                f"<span style='color:#10B981;font-weight:600'>{int(r['_prompt_score'])}</span> "
                                f"<span style='color:#D1D5DB'>{q[:200]}</span></div>",
                                unsafe_allow_html=True,
                            )
                with col_worst:
                    st.markdown("**🔴 Vaguest prompts**")
                    worst = (scored_acct.sort_values("_prompt_score", ascending=True)
                             .drop_duplicates(subset=["_question"]).head(5))
                    if worst.empty:
                        st.caption("—")
                    else:
                        for _, r in worst.iterrows():
                            q = str(r["_question"]).strip()
                            st.markdown(
                                f"<div style='font-size:0.85rem;margin-bottom:6px'>"
                                f"<span style='color:#EF4444;font-weight:600'>{int(r['_prompt_score'])}</span> "
                                f"<span style='color:#D1D5DB'>{q[:200]}</span></div>",
                                unsafe_allow_html=True,
                            )
                st.caption("Score is based on: metric (revenue/ROAS/units), "
                           "timeframe (March, last week, YoY), entity (SKU/channel/country), "
                           "comparison (vs/growth). Pure follow-ups and very short prompts are capped.")

            st.markdown("#### 📋 Query Timeline")
            # Filter out rows where question or answer is just "Loading..." (Hoppr log noise)
            timeline_all = acct_f.sort_values("_date", ascending=False)
            loading_mask = (
                timeline_all["_question"].str.strip().str.lower().isin(["loading...", "loading", ""])
                | timeline_all["_question"].isna()
            )
            timeline_loading = timeline_all[loading_mask]
            timeline = timeline_all[~loading_mask].head(100)
            if not timeline_loading.empty:
                st.caption(f"ℹ️ {len(timeline_loading)} incomplete entries hidden (answer still loading when logged)")
            for _, qrow in timeline.iterrows():
                dt       = str(qrow["_date"])[:10]
                em       = str(qrow["_email"])
                question = str(qrow["_question"])
                answer   = str(qrow["_answer"])
                # Detect answer quality
                is_loading_ans = answer.strip().lower() in ("loading...", "loading", "", "nan")
                has_data = any(c in answer for c in ["📊", "|", "%", "table", "##"])
                failed   = any(w in answer.lower() for w in
                               ["unable", "don't have", "not available", "cannot provide", "no data"])
                acc_flag = "🔴 " if is_accuracy(question) else ""
                if is_loading_ans:
                    status = "⏳"
                elif failed:
                    status = "⚠️"
                elif has_data:
                    status = "✅"
                else:
                    status = "➡️"
                em_short = em.split("@")[0] if "@" in em else em
                # Show first 120 chars of question in expander header
                q_short = question[:120] + ("…" if len(question) > 120 else "")
                with st.expander(f"{acc_flag}{status} {dt} — **{em_short}** — {q_short}"):
                    st.markdown(f"**Q:** {question}")
                    st.markdown("**A:**")
                    if is_loading_ans:
                        st.caption(f"No answer in column `{a_col_e or '?'}` for this row — "
                                   f"check the Data Status panel if answers are missing broadly.")
                    else:
                        # Show up to 800 chars; offer expander for full text
                        ans_display = answer if answer and answer != "nan" else ""
                        if not ans_display:
                            st.caption("No answer recorded in this row.")
                        elif len(ans_display) > 800:
                            st.markdown(ans_display[:800] + "…")
                            with st.expander("Show full answer"):
                                st.markdown(ans_display)
                        else:
                            st.markdown(ans_display)
            if len(timeline) == 100 and len(timeline_all[~loading_mask]) > 100:
                st.caption(f"Showing most recent 100 of {len(timeline_all[~loading_mask])} queries.")


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
                            model="claude-sonnet-4-20250514",
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
