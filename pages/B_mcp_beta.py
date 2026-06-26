"""MCP Beta Usage — Graas warehouse exposed via Claude / GPT.

Tracks early adoption of the MCP integration: who's connecting, what
they ask, what tools they hit, error rates. Reads from the MCP Dashboard
sheet (env var MCP_BETA_SHEET_ID, defaults to the beta sheet ID).

Data sources:
  • Questions Log — one row per question (TS, SELLER_ID, USER_EMAIL,
    QUESTION_TEXT, TOOL_NAME, STATUS, ERROR_CATEGORY, SQL_QUERY).
    Everything quantitative is derived from this — it's the source of
    truth.
  • Tool Calls — aggregated tool-level CALLS / ERRORS / AVG_MS. Used
    for the tool-mix breakdown.
"""

import os
import sys
from pathlib import Path
from datetime import datetime as _dt, timedelta

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

_env_path = str(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(_env_path, override=True)

from services.question_classifier import classify_question

st.set_page_config(page_title="MCP Beta | Graas", page_icon="🔌", layout="wide")
st.markdown("## 🔌 MCP Beta Usage")
st.caption(
    "Sellers asking questions on Claude / GPT via the Graas MCP integration. "
    "Same warehouse as Hoppr, different surface."
)

MCP_SHEET_ID = os.getenv(
    "MCP_BETA_SHEET_ID",
    "1dqo-liMiDq2Etqy_jOGxyg_8lSzRtctXJ59Nt0Cz56Q",
)


# ── Loaders ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=1800)
def load_questions_log():
    from services.sheets_client import fetch_sheet_tab
    try:
        df = fetch_sheet_tab(MCP_SHEET_ID, "Questions Log")
        if df.empty:
            return pd.DataFrame(), None
        df = df.copy()
        df["_ts"] = pd.to_datetime(df.get("TS"), errors="coerce")
        df["_date"] = df["_ts"].dt.date.astype("datetime64[ns]")
        for c in ("SELLER_ID", "USER_EMAIL", "QUESTION_TEXT", "TOOL_NAME",
                  "STATUS", "ERROR_CATEGORY"):
            if c in df.columns:
                df[c] = df[c].astype(str).str.strip()
        df = df.dropna(subset=["_ts"]).reset_index(drop=True)
        return df, None
    except Exception as e:
        return pd.DataFrame(), str(e)


@st.cache_data(ttl=1800)
def load_tool_calls():
    from services.sheets_client import fetch_sheet_tab
    try:
        df = fetch_sheet_tab(MCP_SHEET_ID, "Tool Calls")
        if df.empty:
            return pd.DataFrame(), None
        df = df.copy()
        for c in ("CALLS", "ERRORS", "AVG_MS"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
        return df, None
    except Exception as e:
        return pd.DataFrame(), str(e)


questions_log, _err_q = load_questions_log()
tool_calls,    _err_t = load_tool_calls()

if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()


# ── Data health: single banner at the top ────────────────────────────────────
from services.data_health import render_banner as _data_health_banner
_data_health_banner([
    {
        "name": "MCP Questions Log",
        "df": questions_log,
        "powers": [
            "All KPIs (Questions / Active Sellers / SQL Queries / Error rate)",
            "Time-series chart",
            "What Sellers Are Asking About bar chart",
            "Per-seller table",
        ],
        "required_cols": ["TS", "SELLER_ID", "QUESTION_TEXT"],
        "tab_hint": "Questions Log",
    },
    {
        "name": "MCP Tool Calls",
        "df": tool_calls,
        "powers": ["Tool usage breakdown + error-rate per tool"],
        "tab_hint": "Tool Calls",
    },
])

if questions_log.empty:
    st.stop()


# ── Period selector ──────────────────────────────────────────────────────────
period = st.radio(
    "Period", ["1W", "1M", "3M", "All"], index=1, horizontal=True, key="mcp_period",
)
_PERIOD_LABEL = {"1W": "7d", "1M": "30d", "3M": "90d", "All": "all-time"}
_period_suffix = _PERIOD_LABEL.get(period, period)

today_ts = questions_log["_ts"].max()
if period == "All":
    qsl = questions_log
else:
    days = {"1W": 7, "1M": 30, "3M": 90}[period]
    qsl = questions_log[questions_log["_ts"] >= today_ts - pd.Timedelta(days=days)]


# ── KPI strip ────────────────────────────────────────────────────────────────
_HDR_STYLE = (
    "font-size:0.82rem;color:#4B5563;font-weight:600;"
    "letter-spacing:0.02em;padding-bottom:4px;"
)
_VAL_STYLE = (
    "font-size:2rem;font-weight:600;color:#111827;line-height:1.1;"
)

# Questions: every row in the log is one question
q_total = len(qsl)
# SQL queries: rows where SQL_QUERY column is non-blank, OR sum from Tool Calls
# (the cheap proxy is to count rows whose SQL_QUERY is non-empty)
sql_total = int((qsl.get("SQL_QUERY", pd.Series(dtype=str)).astype(str).str.strip() != "").sum())
active_sellers = qsl["SELLER_ID"].dropna().astype(str).pipe(
    lambda s: s[(s != "") & (s != "nan")]
).nunique()
err_count = int((qsl.get("STATUS", pd.Series(dtype=str)).astype(str).str.lower() != "ok").sum())
err_rate_str = f"{(err_count / q_total * 100):.0f}%" if q_total else "—"

k = st.columns(4)
labels = [
    (f"Questions ({_period_suffix})", f"{q_total:,}"),
    (f"Active Sellers ({_period_suffix})", f"{active_sellers:,}"),
    (f"SQL Queries ({_period_suffix})", f"{sql_total:,}"),
    (f"Error Rate ({_period_suffix})", err_rate_str),
]
for col, (lbl, val) in zip(k, labels):
    with col:
        st.markdown(f"<div style='{_HDR_STYLE}'>{lbl}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='{_VAL_STYLE}'>{val}</div>", unsafe_allow_html=True)


# ── Time-series chart ────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("#### 📈 Daily Activity")

daily = (qsl.assign(_d=qsl["_ts"].dt.normalize())
         .groupby("_d")
         .agg(questions=("QUESTION_TEXT", "count"),
              sellers=("SELLER_ID", "nunique"),
              sql=("SQL_QUERY", lambda s: int((s.astype(str).str.strip() != "").sum())))
         .reset_index())

if not daily.empty:
    # Reindex to a continuous daily range so days with zero questions
    # render as 0-height bars instead of letting Plotly interpolate
    # sub-day ticks across the gap.
    full_range = pd.date_range(daily["_d"].min(), daily["_d"].max(), freq="D")
    daily = (daily.set_index("_d").reindex(full_range, fill_value=0)
                  .rename_axis("_d").reset_index())

    fig = go.Figure()
    fig.add_trace(go.Bar(x=daily["_d"], y=daily["sellers"],
                         name="Active Sellers", marker_color="#7C3AED", opacity=0.5))
    fig.add_trace(go.Scatter(x=daily["_d"], y=daily["questions"],
                             mode="lines+markers", name="Questions",
                             line=dict(color="#4F46E5", width=2)))
    fig.add_trace(go.Scatter(x=daily["_d"], y=daily["sql"],
                             mode="lines+markers", name="SQL Queries",
                             line=dict(color="#10B981", dash="dot")))
    fig.update_layout(
        height=320, template="plotly_dark",
        margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        xaxis=dict(type="date", dtick="D1", tickformat="%b %-d"),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── What sellers are asking about ────────────────────────────────────────────
st.markdown("---")
st.markdown("#### 📊 What Sellers Are Asking About")
st.caption("Same bucket taxonomy as the Hoppr Accounts page (shared classifier).")

bucket_counts = {}
for q in qsl["QUESTION_TEXT"].dropna().astype(str):
    for tag in classify_question(q):
        bucket_counts[tag] = bucket_counts.get(tag, 0) + 1

if bucket_counts:
    bc = (pd.DataFrame(
        [{"bucket": k, "count": v} for k, v in bucket_counts.items()]
    ).sort_values("count", ascending=True))

    fig_b = go.Figure(go.Bar(
        x=bc["count"], y=bc["bucket"], orientation="h",
        text=bc["count"], textposition="outside",
        marker_color="#4F46E5",
    ))
    fig_b.update_layout(
        height=max(280, len(bc) * 28), template="plotly_dark",
        margin=dict(l=10, r=60, t=10, b=20),
        xaxis_title="Questions", yaxis_title="",
    )
    st.plotly_chart(fig_b, use_container_width=True)


# ── Tool usage breakdown ─────────────────────────────────────────────────────
if not tool_calls.empty:
    st.markdown("---")
    st.markdown("#### 🛠 Tool Usage (all-time, from Tool Calls tab)")
    tc = tool_calls.copy()
    if "CALLS" in tc.columns and "ERRORS" in tc.columns:
        tc["error_rate"] = (tc["ERRORS"] / tc["CALLS"].clip(lower=1) * 100).round(0).astype(int).astype(str) + "%"
    tc_display = tc.rename(columns={
        "TOOL_NAME": "Tool", "CALLS": "Calls", "ERRORS": "Errors",
        "AVG_MS": "Avg ms", "error_rate": "Error %",
    })
    st.dataframe(tc_display, use_container_width=True, hide_index=True)


# ── Per-seller table ─────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("#### 👥 Per-Seller Activity")

today_d = _dt.now().date()
per_seller = (qsl.groupby("SELLER_ID", dropna=True)
              .agg(
                  email=("USER_EMAIL", lambda s: s.dropna().astype(str).iloc[0] if not s.dropna().empty else ""),
                  questions=("QUESTION_TEXT", "count"),
                  sql=("SQL_QUERY", lambda s: int((s.astype(str).str.strip() != "").sum())),
                  errors=("STATUS", lambda s: int((s.astype(str).str.lower() != "ok").sum())),
                  last_active=("_ts", "max"),
              )
              .reset_index()
              .sort_values("questions", ascending=False))

if not per_seller.empty:
    per_seller["days_silent"] = (
        pd.Timestamp(today_d) - per_seller["last_active"].dt.normalize()
    ).dt.days
    per_seller["last_active"] = per_seller["last_active"].dt.strftime("%Y-%m-%d")
    per_seller = per_seller.rename(columns={
        "SELLER_ID": "Seller ID",
        "email": "Email",
        "questions": "Questions",
        "sql": "SQL Queries",
        "errors": "Errors",
        "last_active": "Last Active",
        "days_silent": "Days Silent",
    })
    st.dataframe(per_seller, use_container_width=True, hide_index=True)


# ── Recent questions (collapsed) ─────────────────────────────────────────────
with st.expander(f"📋 Recent questions ({min(50, len(qsl))} most recent)"):
    recent = (qsl.sort_values("_ts", ascending=False)
              .head(50)
              [["_ts", "SELLER_ID", "USER_EMAIL", "TOOL_NAME", "STATUS", "QUESTION_TEXT"]]
              .rename(columns={
                  "_ts": "When",
                  "SELLER_ID": "Seller",
                  "USER_EMAIL": "Email",
                  "TOOL_NAME": "Tool",
                  "STATUS": "Status",
                  "QUESTION_TEXT": "Question",
              }))
    recent["When"] = recent["When"].dt.strftime("%Y-%m-%d %H:%M")
    st.dataframe(recent, use_container_width=True, hide_index=True)
