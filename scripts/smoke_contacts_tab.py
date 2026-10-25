#!/usr/bin/env python3
"""Execute the WHOLE 3_crm.py page headlessly against live data.

smoke_analytics_tab.py runs only the analytics body, so a break anywhere
else on the page stayed invisible to the gates. Two did: the Ankit's-tab
concat left last_contact as an object column and `pd.Timestamp.now() -
last_contact` took the page down at import time, and the watchers helper
was defined ~650 lines below the dashboard that now calls it — a NameError
on deploy that py_compile and the AST order check both pass.

This runs the page top to bottom with a stubbed streamlit: prologue,
derived fields, and every tab body. Buttons/checkboxes return False, so no
send, no write, no sheet mutation — the stub has no credentials to do it
with anyway.
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

calls = {"dataframe": 0, "error": 0, "metric": 0}


class Ctx:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class ColCfg:
    def __getattr__(self, name):
        return lambda *a, **k: None


class St(types.SimpleNamespace):
    column_config = ColCfg()
    session_state = {}
    secrets = {}

    def container(self, **k): return Ctx()
    def expander(self, *a, **k): return Ctx()
    def form(self, *a, **k): return Ctx()
    def spinner(self, *a, **k): return Ctx()
    def status(self, *a, **k): return Ctx()
    def popover(self, *a, **k): return Ctx()
    def sidebar(self): return Ctx()

    def columns(self, spec, **k):
        n = len(spec) if isinstance(spec, (list, tuple)) else spec
        return [Ctx() for _ in range(n)]

    def tabs(self, labels, **k):
        return [Ctx() for _ in labels]

    def cache_data(self, *a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

    def segmented_control(self, label, options, **k):
        return k.get("default", options[0] if options else None)

    def selectbox(self, label, options, **k):
        return options[0] if options else None

    def radio(self, label, options, **k):
        return options[0] if options else None

    def checkbox(self, *a, **k): return False
    def toggle(self, *a, **k): return False
    def button(self, *a, **k): return False
    def form_submit_button(self, *a, **k): return False
    def download_button(self, *a, **k): return False
    def text_input(self, *a, **k): return ""
    def text_area(self, *a, **k): return ""
    def multiselect(self, *a, **k): return []
    def file_uploader(self, *a, **k): return None
    def number_input(self, *a, **k): return 0
    def slider(self, *a, **k): return 0
    def date_input(self, *a, **k): return datetime.now().date()

    def data_editor(self, df, **k):
        # Returns the EDITED frame in Streamlit; the generic None fallback made
        # the composer look broken (`NoneType has no attribute iterrows`).
        return df

    def metric(self, label, value, **k):
        calls["metric"] += 1

    def dataframe(self, df, **k):
        calls["dataframe"] += 1
        data = getattr(df, "data", df)          # unwrap Styler
        assert hasattr(data, "shape"), "non-frame passed to st.dataframe"

    def exception(self, e, **k):
        # _tab_guard hands the real traceback here; without printing it a
        # broken tab shows up only as an anonymous banner count.
        if os.getenv("SMOKE_VERBOSE"):
            import traceback
            print("  ---- tab traceback ----")
            print("  ", type(e).__name__, ":", e)
            traceback.print_exception(type(e), e, e.__traceback__)
            print("  -----------------------")

    def error(self, *a, **k):
        calls["error"] += 1
        # An error banner is not automatically a failure (the page shows one
        # for genuine data conditions, e.g. send failures in the log), but a
        # silent count is useless when one appears. SMOKE_VERBOSE=1 shows it.
        if os.getenv("SMOKE_VERBOSE"):
            print("  ERROR BANNER:", str(a[0])[:400] if a else "<empty>")

    def stop(self):
        raise SystemExit("st.stop")

    def rerun(self):
        raise SystemExit("st.rerun")

    def __getattr__(self, name):
        return lambda *a, **k: None


def main():
    st = St()
    sys.modules['streamlit'] = st
    # the page imports these submodules by name
    for sub in ('streamlit.components.v1',):
        m = types.ModuleType(sub)
        m.html = lambda *a, **k: None
        m.iframe = lambda *a, **k: None
        sys.modules[sub] = m
    comp = types.ModuleType('streamlit.components')
    comp.v1 = sys.modules['streamlit.components.v1']
    sys.modules['streamlit.components'] = comp
    st.components = comp

    # Unlock the auth gate for this headless pass — require_unlock() st.stop()s
    # otherwise and we never reach the page body this gate exists to test.
    import services.auth_gate as _ag
    st.session_state[_ag._SESSION_KEY] = True

    src = open('views/3_crm.py').read()
    ns = {'__name__': 'crm_smoke',
          '__file__': os.path.abspath('views/3_crm.py')}

    try:
        exec(compile(src, '3_crm.py', 'exec'), ns)
    except SystemExit as e:
        # st.stop()/st.rerun() is a legitimate end for a render pass, but an
        # auth gate firing means we never reached the body worth testing.
        if 'rerun' not in str(e):
            print(f"CONTACTS SMOKE FAIL — page called st.stop(): {e}")
            return 1
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nCONTACTS SMOKE FAIL — {type(e).__name__}: {e}")
        return 1

    # The thing that actually broke twice: contacts must exist, carry usable
    # dates, and the watcher helper must be callable from the dashboard.
    contacts = ns.get('contacts')
    if contacts is None or not hasattr(contacts, 'shape'):
        print("CONTACTS SMOKE FAIL — page did not build a contacts frame")
        return 1
    if 'days_silent' not in contacts.columns:
        print("CONTACTS SMOKE FAIL — days_silent missing (date coercion gone?)")
        return 1
    if '_list' not in contacts.columns:
        print("CONTACTS SMOKE FAIL — _list missing; audit BCC cannot route")
        return 1
    bad = set(contacts['_list'].astype(str).unique()) - {'pipeline', 'ankit'}
    if bad:
        print(f"CONTACTS SMOKE FAIL — unexpected _list values: {bad}")
        return 1
    if not callable(ns.get('_fetch_watchers_page')):
        print("CONTACTS SMOKE FAIL — _fetch_watchers_page not defined")
        return 1

    n_ankit = int((contacts['_list'] == 'ankit').sum())
    n_pipe = int((contacts['_list'] == 'pipeline').sum())
    print(f"CONTACTS SMOKE OK — whole page executed: {len(contacts)} contacts "
          f"({n_pipe} pipeline / {n_ankit} ankit), {calls['metric']} metrics, "
          f"{calls['dataframe']} tables, {calls['error']} error banners")
    return 0


if __name__ == '__main__':
    sys.exit(main())
