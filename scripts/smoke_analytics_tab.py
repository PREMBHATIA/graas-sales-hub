#!/usr/bin/env python3
"""Execute the ENTIRE analytics tab body headlessly against live data.

Why this exists: three prior gates (py_compile, prologue smoke, tab-order
AST check) all stayed green while the deployed tab died twice — once on a
section reorder (NameError: _exp) and once when a refactor silently deleted
_log_integrity. Both were execution-order/existence bugs that only running
the code catches. This runs it, with a stubbed streamlit and the real
Sheets data when credentials are available (falls back to synthetic frames
in CI/sandbox).
"""
import os
import sys
import types
import re as _re
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.exists('.env'):
    for line in open('.env'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k, v.strip())

import pandas as pd  # noqa: E402

calls = {"dataframe": 0, "error": 0}


class Ctx:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class ColCfg:
    @staticmethod
    def Column(*a, **k): return None
    @staticmethod
    def LinkColumn(*a, **k): return None
    @staticmethod
    def TextColumn(*a, **k): return None


class St(types.SimpleNamespace):
    column_config = ColCfg()
    session_state = {}

    def container(self, **k): return Ctx()
    def expander(self, *a, **k): return Ctx()

    def columns(self, spec, **k):
        n = len(spec) if isinstance(spec, (list, tuple)) else spec
        return [Ctx() for _ in range(n)]

    def segmented_control(self, label, options, **k):
        return k.get("default", options[0] if options else None)

    def selectbox(self, label, options, **k):
        return options[0] if options else None

    def checkbox(self, *a, **k): return False
    def button(self, *a, **k): return False
    def text_input(self, *a, **k): return ""
    def text_area(self, *a, **k): return ""
    def radio(self, label, options, **k):
        return options[0] if options else None
    def multiselect(self, *a, **k): return []
    def file_uploader(self, *a, **k): return None
    def number_input(self, *a, **k): return 0

    def dataframe(self, df, **k):
        calls["dataframe"] += 1
        data = getattr(df, "data", df)          # unwrap Styler
        assert hasattr(data, "shape"), "non-frame passed to st.dataframe"

    def error(self, *a, **k):
        calls["error"] += 1

    def stop(self):
        raise SystemExit("st.stop")

    def __getattr__(self, name):
        return lambda *a, **k: None


def synthetic():
    now = pd.Timestamp.utcnow()
    sends = pd.DataFrame({
        "timestamp_utc": [(now - pd.Timedelta(hours=h)).isoformat() for h in range(6)],
        "to_email": [f"u{i}@x.com" for i in range(6)],
        "to_name": [f"U{i}" for i in range(6)],
        "company": ["Acme"] * 3 + ["Beta"] * 3,
        "bucket": [""] * 6, "template": ["Custom"] * 6,
        "subject": ["Camp A"] * 3 + ["Camp B"] * 3,
        "body": ["<p>x</p>"] * 6, "status": ["sent"] * 6,
        "error_msg": [""] * 6,
        "tracking_id": [f"tid{i}" for i in range(6)],
        "sender_label": ["Prem"] * 6, "from_email": ["i@g"] * 6,
        "reply_to": ["p@g"] * 6,
    })
    track = pd.DataFrame({
        "ts_utc": [(now - pd.Timedelta(minutes=m)).isoformat() for m in (5, 10)],
        "tracking_id": ["tid0", "tid3"],
        "event": ["open", "open"], "dest_url": ["", ""],
    })
    return sends, track


def main():
    st = St()
    src = open('pages/3_crm.py').read()
    lines = src.split('\n')
    start = next(i for i, l in enumerate(lines) if 'with tab_analytics' in l)
    body = lines[start + 1:]
    end = next((i for i, l in enumerate(body)
                if l.strip() and not l.startswith((' ', '\t'))), len(body))
    body = '\n'.join(l[4:] if l.startswith('    ') else l for l in body[:end])

    ns = {'st': st, 'pd': pd, 'datetime': datetime, 're': _re}
    exec(src[src.index('_OPEN_PREFETCH_SEC = 60'):
             src.index('def _inbox_scan_results')], ns)

    try:
        from services.email_sender import recent_sends, fetch_tracking_events
        sends = recent_sends(1000)
        track = fetch_tracking_events()
        assert sends is not None and not sends.empty
        source = "live sheet"
    except Exception:
        sends, track = synthetic()
        source = "synthetic fixtures"
    sends.columns = [c.strip() for c in sends.columns]

    ns['_inbox_scan_results'] = lambda: {"bounces": [], "unsubs": [], "at": None}
    ns['_cached_log_df'] = lambda: sends
    ns['_cached_tracking_df'] = lambda: track
    ns['_fetch_suppressions'] = lambda: pd.DataFrame(columns=['email', 'reason'])
    ns['_get_weekly_cap'] = lambda: 300
    ns['_add_to_suppression'] = lambda *a, **k: True
    ns['a_pre_err'] = None
    ns['contacts'] = pd.DataFrame({
        'email': sends['to_email'].astype(str),
        'company': sends['company'].astype(str),
        'ai_segment': 'AI Exploring', 'has_email': True})

    try:
        exec(compile(body, 'analytics_tab', 'exec'), ns)
    except SystemExit:
        print(f"ANALYTICS SMOKE FAIL — st.stop fired against {source} "
              f"(integrity gate tripped?)")
        return 1
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nANALYTICS SMOKE FAIL — {type(e).__name__}: {e}")
        return 1
    if calls["dataframe"] < 1:
        print("ANALYTICS SMOKE FAIL — executed but rendered no tables")
        return 1
    print(f"ANALYTICS SMOKE OK — full tab executed against {source}: "
          f"{calls['dataframe']} tables, {calls['error']} error banners")
    return 0


if __name__ == "__main__":
    sys.exit(main())
