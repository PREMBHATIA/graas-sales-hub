"""Ask Hoppr — AI analyst for Hoppr usage & seller intelligence."""

import streamlit as st
import pandas as pd
from pathlib import Path
from collections import Counter
import sys
import re
import os
from datetime import datetime as _dt

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"), override=True)

st.set_page_config(page_title="Ask Hoppr | Graas", page_icon="💬", layout="wide")

# ── Keys ──────────────────────────────────────────────────────────────────────
try:
    ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

try:
    HOPPR_SHEET_ID = st.secrets["HOPPR_SHEET_ID"]
except Exception:
    HOPPR_SHEET_ID = os.getenv("HOPPR_SHEET_ID", "1IR6KuRhPMRj_JsF261ZEUjLlHXu6UZ33diZQRw2MqJM")

st.markdown("## 💬 Ask Hoppr")
st.caption("Ask anything about seller usage, query trends, data quality, or account health.")

# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADERS
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=1800)
def load_eval():
    from services.sheets_client import fetch_sheet_tab
    try:
        df = fetch_sheet_tab(HOPPR_SHEET_ID, "Evaluation_sheet")
        return (df if not df.empty else pd.DataFrame()), None
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl=1800)
def load_user_state():
    from services.sheets_client import fetch_sheet_tab
    try:
        df = fetch_sheet_tab(HOPPR_SHEET_ID, "User_State")
        return (df if not df.empty else pd.DataFrame()), None
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl=3600)
def load_daily():
    from services.sheets_client import fetch_sheet_tab
    try:
        df = fetch_sheet_tab(HOPPR_SHEET_ID, "Hoppr__Anaysis")
        return (df if not df.empty else pd.DataFrame()), None
    except Exception as e:
        return pd.DataFrame(), str(e)

raw_eval,       _err_eval  = load_eval()
raw_user_state, _err_us    = load_user_state()
raw_daily_raw,  _err_daily = load_daily()

col_r, _ = st.columns([1, 9])
with col_r:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# ACCURACY KEYWORDS & CLASSIFICATION
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

# ── Prompt quality scoring (mirror of 7_hoppr.py) ─────────────────────────────
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
    if q is None or (isinstance(q, float) and pd.isna(q)):
        return {"score": 0, "tier": "Empty"}
    text = str(q).strip()
    ql = text.lower()
    if ql in ("", "loading...", "loading", "nan"):
        return {"score": 0, "tier": "Empty"}
    word_count = len(text.split())
    has_metric  = any(kw in ql for kw in SCORE_METRIC_WORDS)
    has_time    = any(kw in ql for kw in SCORE_TIME_WORDS)
    has_entity  = any(kw in ql for kw in SCORE_ENTITY_WORDS)
    has_compare = any(kw in ql for kw in SCORE_COMPARISON_WORDS)
    is_followup = (word_count <= 5
                   and any(p in ql for p in SCORE_FOLLOWUP_PHRASES))
    is_too_short = word_count < 4
    score = 0
    if word_count >= 6:   score += 15
    elif word_count >= 4: score += 5
    if has_metric:  score += 30
    if has_time:    score += 25
    if has_entity:  score += 20
    if has_compare: score += 10
    if is_followup:   score = min(score, 25)
    if is_too_short:  score = min(score, 25)
    score = max(0, min(score, 100))
    if   score >= 70: tier = "Strong"
    elif score >= 45: tier = "Decent"
    elif score >= 20: tier = "Weak"
    else:             tier = "Vague"
    return {"score": score, "tier": tier}

# ══════════════════════════════════════════════════════════════════════════════
# PROCESS EVAL SHEET
# ══════════════════════════════════════════════════════════════════════════════

eval_processed = pd.DataFrame()
sid_col_e = email_col_e = date_col_e = q_col_e = a_col_e = None

if not raw_eval.empty:
    edf = raw_eval.copy()
    ecols = [str(c).strip() for c in edf.columns]
    edf.columns = ecols

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

    if sid_col_e and date_col_e and q_col_e:
        edf["_date"]     = pd.to_datetime(edf[date_col_e], errors="coerce")
        edf["_seller"]   = edf[sid_col_e].astype(str).str.strip()
        edf["_email"]    = edf[email_col_e].astype(str).str.strip() if email_col_e else ""
        edf["_question"] = edf[q_col_e].astype(str)
        edf["_answer"]   = edf[a_col_e].astype(str) if a_col_e else ""
        edf = edf.dropna(subset=["_date"])

        # Filter "Loading..." log noise — see 7_hoppr.py for rationale
        _q_clean = edf["_question"].astype(str).str.strip().str.lower()
        edf = edf[~_q_clean.isin(["loading...", "loading", "", "nan"])]

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
        email = vals[2] if len(vals) > 2 else ""
        last_seen = vals[3] if len(vals) > 3 else ""
        try:    q_total = int(float(vals[4])) if len(vals) > 4 and vals[4] else 0
        except: q_total = 0
        try:    q_7d = int(float(vals[5])) if len(vals) > 5 and vals[5] else 0
        except: q_7d = 0
        days_silent = 999
        if last_seen:
            try: days_silent = (_today - _dt.strptime(last_seen, "%Y-%m-%d").date()).days
            except: pass
        bucket = vals[7] if len(vals) > 7 else ""
        bl = bucket.lower()
        if "sales" in bl or "ready" in bl: cls = "Sales-Ready"
        elif "power" in bl:               cls = "Power User"
        elif "explor" in bl:              cls = "Explorer"
        elif "block" in bl:               cls = "Blocked"
        else:                             cls = "Low Usage"
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

# Enrich with all emails from eval
if not eval_processed.empty and sellers:
    _ev = eval_processed[["_seller", "_email", "_date"]].copy()
    _ev = _ev[_ev["_seller"].notna() & _ev["_email"].notna()]
    _ev = _ev[(_ev["_seller"] != "nan") & (_ev["_email"] != "nan") & (_ev["_email"] != "")]
    for sid, grp in _ev.groupby("_seller", sort=False):
        seller_users_map[sid] = {}
        for em, eg in grp.groupby("_email", sort=False):
            seller_users_map[sid][em] = {"count": len(eg)}

    _scored_only = eval_processed[eval_processed["_prompt_tier"] != "Empty"]
    _seller_avg = (_scored_only.groupby("_seller")["_prompt_score"]
                   .mean().round(0).astype(int).to_dict()) if not _scored_only.empty else {}

    for s in sellers:
        sid = s["seller_id"]
        if sid in seller_users_map:
            s["user_count"] = len(seller_users_map[sid])
            s["all_emails"] = list(seller_users_map[sid].keys())
        else:
            s.setdefault("user_count", 1)
            s.setdefault("all_emails", [s["email"]])
        s["prompt_quality"] = _seller_avg.get(sid, None)
else:
    for s in sellers:
        s.setdefault("user_count", 1)
        s.setdefault("all_emails", [s.get("email", "")])
        s.setdefault("prompt_quality", None)

# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC METRICS
# ══════════════════════════════════════════════════════════════════════════════

_eval_rows = len(eval_processed)
_diag = st.columns(4)
with _diag[0]:
    st.metric("Sellers loaded", len(sellers), help="From User_State tab")
with _diag[1]:
    st.metric("Q&A rows loaded", _eval_rows, help="From Evaluation_sheet tab")
with _diag[2]:
    st.metric("Eval columns", "OK" if q_col_e and a_col_e else "MISSING")
with _diag[3]:
    if _err_eval:
        st.error(f"Eval error: {_err_eval[:80]}")
    elif not _eval_rows and not _err_eval:
        st.warning("Eval sheet: empty or col mismatch")
    else:
        st.success("Eval sheet: OK")

if q_col_e or a_col_e:
    st.caption(f"Columns: question=`{q_col_e}` | answer=`{a_col_e}` | "
               f"seller=`{sid_col_e}` | date=`{date_col_e}`")
elif not raw_eval.empty:
    st.warning(f"Columns found: `{list(raw_eval.columns)}`")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# ASK HOPPR CHAT
# ══════════════════════════════════════════════════════════════════════════════

if not ANTHROPIC_API_KEY:
    st.warning("Add `ANTHROPIC_API_KEY` to secrets to enable Ask Hoppr.")
    st.stop()

# ── Build context ─────────────────────────────────────────────────────────────
def _build_context(sellers_list, eval_df):
    lines = []
    if sellers_list:
        sdf = pd.DataFrame(sellers_list)
        lines.append(f"SELLERS: {len(sdf)} total | "
                     f"Active ≤7d: {len(sdf[sdf['days_silent'] <= 7])} | "
                     f"Power Users: {len(sdf[sdf['classification'] == 'Power User'])} | "
                     f"Sales-Ready: {len(sdf[sdf['classification'] == 'Sales-Ready'])} | "
                     f"Going Quiet: {len(sdf[sdf['trend'] == 'Going Quiet'])} | "
                     f"Churned: {len(sdf[sdf['trend'] == 'Churned'])}")
        lines.append("\nALL SELLERS (seller_id | email | total_Q | Q_7d | class | trend | days_silent | PromptQ/100 | topics | answer_quality | action):")
        lines.append("PromptQ score 0-100: Strong ≥70 (clear metric+timeframe+entity), Decent 45-69, Weak 20-44, Vague <20 (short / pure followup / missing context).")
        for _, r in sdf.sort_values("q_total", ascending=False).iterrows():
            qs  = str(r.get("q_summary", "")).strip()
            aq  = str(r.get("a_summary", "")).strip()
            act = str(r.get("action", "")).strip()
            pq  = r.get("prompt_quality", None)
            pq_str = (f" | PromptQ {int(pq)}/100"
                      if pq is not None and not pd.isna(pq) else "")
            line = (f"  {r['seller_id']} | {r['email']} | {r['q_total']}Q | "
                    f"{r['q_recent']}Q(7d) | {r['classification']} | "
                    f"{r['trend']} | {r['days_silent']}d{pq_str}")
            if qs and qs != "nan":
                line += f"\n    Topics: {qs[:250]}"
            if aq and aq != "nan":
                line += f"\n    Answer quality: {aq[:200]}"
            if act and act != "nan":
                line += f"\n    Action: {act[:150]}"
            lines.append(line)
    if not eval_df.empty and "_buckets" in eval_df.columns:
        all_b = [b for bl in eval_df["_buckets"] for b in bl]
        lines.append("\nQUESTION TYPES:")
        for bucket, cnt in Counter(all_b).most_common(10):
            lines.append(f"  {bucket}: {cnt}")
    if not eval_df.empty and "_is_accuracy" in eval_df.columns:
        acc = int(eval_df["_is_accuracy"].sum())
        tot = len(eval_df)
        lines.append(f"\nDATA ACCURACY ISSUES: {acc}/{tot} ({acc/tot*100:.1f}%)")
        if acc:
            for sid, cnt in eval_df[eval_df["_is_accuracy"]]["_seller"].value_counts().head(10).items():
                lines.append(f"  {sid}: {cnt}")
    return "\n".join(lines)

ctx = _build_context(sellers, eval_processed)

eval_status = (f"✅ {_eval_rows} Q&A rows loaded" if _eval_rows
               else "⚠️ Individual Q&A not available — seller summaries only")

SYSTEM = f"""You are Ask Hoppr — an AI analyst for the Graas Sales Hub.

CRITICAL RULES:
- All data is PRE-LOADED below. You already have it.
- NEVER say you cannot access Google Sheets or URLs.
- NEVER ask the user to paste data.
- If a URL is pasted, acknowledge it but answer from the data you already have.
- To match a company name to a seller ID: look at email domains in the ALL SELLERS list.
  Example: "paula's choice" → paulaschoice → @paulaschoice.vn → AAIDF.

Data status: {eval_status}

=== DATA SNAPSHOT ===
{ctx}
=== END ==="""

def _get_detail(seller_id: str) -> str:
    if eval_processed.empty or "_seller" not in eval_processed.columns:
        return ""
    rows = eval_processed[eval_processed["_seller"] == seller_id].sort_values("_date")
    if rows.empty:
        return ""
    out = [f"\n===== Q&A LOG: {seller_id} ({len(rows)} queries) ====="]
    for email, grp in rows.groupby("_email", sort=False):
        em = str(email)
        if not em or em == "nan":
            continue
        out.append(f"\n  USER: {em} ({len(grp)} queries)")
        for _, r in grp.sort_values("_date").iterrows():
            dt  = str(r["_date"])[:10]
            q   = str(r["_question"])
            a   = str(r.get("_answer", "")) if "_answer" in r.index else ""
            acc = " [ACCURACY ISSUE]" if is_accuracy(q) else ""
            out.append(f"\n    [{dt}]{acc}")
            out.append(f"    Q: {q}")
            out.append(f"    A: {a[:1200] if a and a.strip() and a != 'nan' else '(no response recorded)'}")
    out.append("\n===== END =====")
    return "\n".join(out)

def _detect(text: str) -> list:
    text_upper = text.upper()
    text_norm  = re.sub(r"[^a-z0-9]", "", text.lower())
    found = set()
    for s in sellers:
        sid = s["seller_id"]
        if len(sid) >= 3 and sid in text_upper:
            found.add(sid); continue
        for em in [s.get("email", "")] + s.get("all_emails", []):
            if em and "@" in em:
                dp = re.sub(r"[^a-z0-9]", "", em.split("@")[1].split(".")[0].lower())
                if len(dp) >= 4 and dp in text_norm:
                    found.add(sid); break
    return list(found)

def _detect_from_history(msg: str, history: list) -> list:
    all_text = msg + " " + " ".join(m["content"] for m in history[-10:])
    return _detect(all_text)

# ── Chat UI ───────────────────────────────────────────────────────────────────
if "ask_hoppr_chat" not in st.session_state:
    st.session_state.ask_hoppr_chat = []

st.markdown("**Try asking:**")
ex_cols = st.columns(4)
for i, ep in enumerate([
    "Show all AAIDF (Paula's Choice) queries in the last 30 days",
    "Which sellers are going quiet?",
    "Top question types across all sellers",
    "Who are the top 5 sellers by total queries?",
]):
    with ex_cols[i]:
        if st.button(ep, key=f"ahq_{i}", use_container_width=True):
            st.session_state["ask_hoppr_prefill"] = ep

for msg in st.session_state.ask_hoppr_chat:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_q = st.chat_input("Ask about Hoppr sellers, queries, or trends…")
if "ask_hoppr_prefill" in st.session_state:
    user_q = st.session_state.pop("ask_hoppr_prefill")

if user_q:
    st.session_state.ask_hoppr_chat.append({"role": "user", "content": user_q})
    with st.chat_message("user"):
        st.markdown(user_q)
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                import anthropic as _anthropic
                mentioned = _detect_from_history(user_q, st.session_state.ask_hoppr_chat)
                extra = ""
                for sid in mentioned[:3]:
                    detail = _get_detail(sid)
                    if detail:
                        extra += detail
                    else:
                        s_info = next((s for s in sellers if s["seller_id"] == sid), None)
                        if s_info:
                            extra += (
                                f"\n===== SELLER: {sid} =====\n"
                                f"Email: {s_info.get('email','')}\n"
                                f"All users: {s_info.get('all_emails',[])}\n"
                                f"Total queries: {s_info.get('q_total',0)}\n"
                                f"Recent (7d): {s_info.get('q_recent',0)}\n"
                                f"Classification: {s_info.get('classification','')}\n"
                                f"Trend: {s_info.get('trend','')}\n"
                                f"Last active: {s_info.get('last_active','')}\n"
                                f"Topics: {s_info.get('q_summary','')}\n"
                                f"Answer quality: {s_info.get('a_summary','')}\n"
                                f"Action: {s_info.get('action','')}\n"
                                f"NOTE: Detailed Q&A not available (Evaluation_sheet not loaded).\n"
                                f"===== END =====\n"
                            )
                system = SYSTEM + (f"\n\n=== DETAILED DATA ===\n{extra}" if extra else "")
                ai = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                result = ai.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2048,
                    system=system,
                    messages=[{"role": m["role"], "content": m["content"]}
                              for m in st.session_state.ask_hoppr_chat[-20:]],
                )
                response = result.content[0].text
            except Exception as e:
                response = f"Error: {e}"
        st.markdown(response)
        st.session_state.ask_hoppr_chat.append({"role": "assistant", "content": response})

if st.session_state.ask_hoppr_chat:
    if st.button("🗑️ Clear chat", key="clear_ask_hoppr"):
        st.session_state.ask_hoppr_chat = []
        st.rerun()
