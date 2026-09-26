"""Graas Sales Hub — homepage."""

import streamlit as st

st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #4F46E5, #7C3AED);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 1rem;
        color: #9CA3AF;
        margin-top: -10px;
        margin-bottom: 28px;
    }
    .section-label {
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #6B7280;
        margin-bottom: 8px;
        margin-top: 4px;
    }
    .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

st.markdown('<p class="main-header">Graas Sales Hub</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Pipeline, All-e & Hoppr — shared team view</p>', unsafe_allow_html=True)

# ── Email outreach snapshot ───────────────────────────────────────────────────
# The campaign table, on the landing page. It is the thing people actually open
# the Hub to check, and it was three clicks deep. Per campaign, never a rolling
# average — campaigns sent weeks apart don't average into anything meaningful.
# Read-only and fail-quiet: the homepage must never break because a sheet read
# timed out.


@st.cache_data(ttl=300, show_spinner=False)
def _outreach_snapshot():
    """(rows, error) — one row per tracked campaign, newest first."""
    import pandas as pd
    try:
        from services.email_sender import recent_sends, fetch_tracking_events
        snd = recent_sends(1000)
        trk = fetch_tracking_events()
        if snd is None or snd.empty:
            return [], None
        if trk is None:                       # read FAILED (vs genuinely empty)
            return [], "tracking"
        snd.columns = [c.strip() for c in snd.columns]
        snd["_ts"] = pd.to_datetime(snd["timestamp_utc"], errors="coerce", utc=True)
        snd = snd[snd["_ts"].notna() & (snd["status"] == "sent")]
        snd = snd[~snd["company"].astype(str).str.contains(
            r"\[INTERNAL WATCHER\]|\[TEST\]", regex=True, na=False)]
        snd = snd[~snd["template"].astype(str).str.contains(
            r"\(test\)|\(internal copy\)", regex=True, na=False)]
        snd["subject"] = snd["subject"].astype(str).str.strip()
        snd["tid"] = snd["tracking_id"].astype(str).str.strip()
        snd = snd[snd["subject"].ne("") & snd["tid"].ne("") & snd["tid"].ne("nan")]
        if snd.empty:
            return [], None

        trk.columns = [c.strip() for c in trk.columns]
        trk["event"] = trk["event"].astype(str).str.strip().str.lower()
        trk["tracking_id"] = trk["tracking_id"].astype(str).str.strip()
        trk["_ev"] = pd.to_datetime(trk["ts_utc"], errors="coerce", utc=True)
        op = trk[trk["event"] == "open"].merge(
            snd[["tid", "_ts"]], left_on="tracking_id", right_on="tid", how="inner")
        op["_lag"] = (op["_ev"] - op["_ts"]).dt.total_seconds()

        rows = []
        for sub, g in snd.groupby("subject"):
            n = len(g)
            if n < 3:
                continue
            e = op[op["tracking_id"].isin(set(g["tid"])) & (op["_lag"] > 60)]
            # A burst = a 10-min window holding 10%+ of this campaign's list:
            # a gateway sweeping, not people. Detected per campaign.
            first = e.groupby("tracking_id")["_ev"].min().to_frame("t")
            real = 0
            if len(first):
                first["w"] = first["t"].dt.floor("10min")
                cnt = first.groupby("w").size()
                burst = set(cnt[cnt >= max(3, int(n * 0.10))].index)
                real = int((~first["w"].isin(burst)).sum())
            machine = int((op[op["tracking_id"].isin(set(g["tid"]))]
                           .groupby("tracking_id")["_lag"].min() <= 60).sum())
            rows.append({
                "Campaign": sub[:46] + ("…" if len(sub) > 46 else ""),
                "Sent": n,
                "Real reads": f"{round(real / n * 100)}%",
                "Machine": f"{round(machine / n * 100)}%",
                "When": g["_ts"].min().strftime("%d %b"),
                "_o": g["_ts"].min(),
            })
        rows.sort(key=lambda r: r["_o"], reverse=True)
        for r in rows:
            r.pop("_o", None)
        return rows[:4], None
    except Exception:
        return [], "read"


st.markdown('<p class="section-label">Email outreach</p>', unsafe_allow_html=True)
_rows, _err = _outreach_snapshot()
if _err:
    st.caption("Outreach figures couldn't be read just now — they're unavailable, "
               "not zero. Open **Emails & Segments** for the live view.")
elif not _rows:
    st.caption("No tracked campaigns yet.")
else:
    import pandas as _pd
    st.dataframe(_pd.DataFrame(_rows), use_container_width=True, hide_index=True,
                 height=min(220, 80 + 35 * len(_rows)))
    st.caption(
        "**Real reads** = opened more than 60 seconds after sending, excluding "
        "synchronised gateway sweeps. **Machine** = opened within 60 seconds, which "
        "is scanning software, not a reader. Per campaign — never averaged."
    )
_hl, _hr, _ = st.columns([1, 1, 2])
with _hl:
    st.page_link("pages/3_crm.py", label="Open Emails & Segments →")
with _hr:
    st.markdown(
        "[Outreach log (Google Sheet) ↗]"
        "(https://docs.google.com/spreadsheets/d/"
        "1Vcu7ZkAjGbzpKH2CUGoSuLUGIfwYBT-GlpNN0zMKJMY/edit)"
    )
st.markdown("---")

# ── Cross-Product ─────────────────────────────────────────────────────────────

st.markdown('<p class="section-label">Cross-Product</p>', unsafe_allow_html=True)

xc1, xc2, _ = st.columns([1, 1, 2])
with xc1:
    st.markdown("### 📋 Pipeline")
    st.markdown("Meetings & proposals — All-e + Hoppr")
    st.page_link("pages/1_pipeline.py", label="Open Pipeline →")
with xc2:
    st.markdown("### 💬 Ask Graas")
    st.markdown("Cross-product Q&A — All-e, Extract, MOR, Hoppr")
    st.page_link("pages/4_ask_graas.py", label="Ask Graas →")

st.markdown("---")

# ── All-e ─────────────────────────────────────────────────────────────────────

st.markdown('<p class="section-label">All-e</p>', unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown("### 🤖 All-e")
    st.markdown("Presales pipeline & deals")
    st.page_link("pages/2_alle.py", label="Open All-e →")

with c2:
    st.markdown("### 📋 Prospect Brief")
    st.markdown("Pre-call two-pager research")
    st.page_link("pages/9_prospect_brief.py", label="Create Brief →")

with c3:
    st.markdown("### 📧 CRM")
    st.markdown("Contacts & email outreach")
    st.page_link("pages/3_crm.py", label="Open CRM →")

with c4:
    st.markdown("### 📚 Resources")
    st.markdown("Key decks & docs")
    st.page_link("pages/5_resources.py", label="Open Resources →")

st.markdown("---")

# ── Hoppr ─────────────────────────────────────────────────────────────────────

st.markdown('<p class="section-label">Hoppr</p>', unsafe_allow_html=True)

h1, _ = st.columns([1, 3])
with h1:
    st.markdown("### 📊 Hoppr")
    st.markdown("Usage, accounts & Ask Hoppr")
    st.page_link("pages/7_hoppr.py", label="Open Hoppr →")

st.markdown("---")
st.markdown("💡 **Tip:** Use the sidebar to navigate between dashboards.")
