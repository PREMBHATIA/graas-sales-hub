"""Smoke-exec the 3_crm.py prologue (imports → item-5 header block → styling)
with a mocked Streamlit + services, forcing the LIVE-data branch so the header
actually calls _render_segment_suggestions. Catches module-level NameErrors —
including the transitive kind (top-level call into a helper that uses a
later-defined global) that py_compile and AST linting miss, and that I can't
otherwise catch without booting the real app.

Truncates just before `st.tabs(` — every load-order bug this session has been in
the prologue, and the tab bodies need far heavier mocking to run.
"""
import os, sys, types
from unittest.mock import MagicMock

# Resolve the page relative to the repo root so this runs anywhere (hook, CI,
# by hand); allow an explicit path override as argv[1] for testing old versions.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_REPO, "pages", "3_crm.py")

# ── mock streamlit ──────────────────────────────────────────────────────────
st = MagicMock(name="streamlit")
def _cache_data(*a, **k):
    """Passthrough @st.cache_data that also survives st.cache_data.clear()."""
    if a and callable(a[0]):
        return a[0]
    return lambda f: f
_cache_data.clear = lambda *a, **k: None
st.cache_data = _cache_data
st.session_state = {}
cm = MagicMock()                      # a reusable context manager (expander/columns/...)
cm.__enter__ = MagicMock(return_value=cm)
cm.__exit__ = MagicMock(return_value=False)
st.expander.return_value = cm
st.container.return_value = cm
st.columns.side_effect = lambda spec, **k: [cm for _ in (spec if isinstance(spec, (list, tuple)) else range(spec))]
st.spinner.return_value = cm
sys.modules["streamlit"] = st
sys.modules["streamlit.components.v1"] = MagicMock()

# ── mock services so _load_segment_suggestions returns LIVE (non-empty) data,
#    forcing the header into the branch that calls _render_segment_suggestions ──
AUD = [["Company", "AI Maturity", "Email Theme"],
       ["Sinarmas SDN", "AI Exploring", "AI Readiness"],
       ["Kajaria Ceramics", "AI Laggard", "Voice — Hold Until Demo"]]
_ws = MagicMock(); _ws.get_all_values.return_value = AUD
_ss = MagicMock(); _ss.get_worksheet_by_id.return_value = _ws; _ss.worksheets.return_value = [_ws]
_client = MagicMock(); _client.open_by_key.return_value = _ss
import pandas as pd
# One realistic pipeline row so the data-loading section (parse → merge →
# playbook tagging) actually executes instead of KeyError-ing on empty frames.
_PIPE = pd.DataFrame([{
    "Lead name": "Acme Corp", "Vertical": "FMCG", "Source of lead": "Test",
    "Agents of interest": "Cartlyst", "Lead status": "4-TOF",
    "First conv date": "1 Jan 2026", "Latest conv date": "1 Aug 2026",
    "Latest Conv details": "notes", "Comments": "c",
    "Email of Key Personnel": "jane.doe@acme.com (CTO)",
    "AI Maturity": "AI Exploring", "Entity type": "Brand",
    "Who will own email outreach": "Prem",
}])
sheets = types.ModuleType("services.sheets_client")
sheets._get_client = lambda: _client
sheets.fetch_sheet_tab = lambda *a, **k: _PIPE.copy()
sheets.fetch_alle_active_presales = lambda *a, **k: _PIPE.copy()
_PIPE2 = _PIPE.copy(); _PIPE2["Lead name"] = "Dropped Co"
sheets.fetch_alle_dropped_leads = lambda *a, **k: _PIPE2
services = types.ModuleType("services")
services.__path__ = []            # mark as package so "services.X" imports resolve
services.sheets_client = sheets
sys.modules["services"] = services
sys.modules["services.sheets_client"] = sheets
# any OTHER services submodule the prologue imports → generic MagicMock
for sub in ("schema", "email_sender", "email_layout", "commerce_news"):
    m = MagicMock(name=f"services.{sub}")
    sys.modules[f"services.{sub}"] = m
    setattr(services, sub, m)

# other imports the prologue touches
for name in ("plotly.express", "dotenv"):
    sys.modules.setdefault(name, MagicMock())
sys.modules["dotenv"].load_dotenv = lambda *a, **k: None

src = open(PAGE).read()
prologue = src[: src.index("tab_contacts, tab_segments")]
ns = {"__name__": "__smoke__", "__file__": PAGE}
try:
    exec(compile(prologue, PAGE, "exec"), ns)
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"\nSMOKE FAIL: {type(e).__name__}: {e}")
    sys.exit(1)
print("SMOKE OK — prologue executes without NameError")


# ── Regression guard: module-level symbols the tab bodies depend on ──────────
# py_compile can't catch these (NameError only fires at page load) and the
# prologue exec stops at st.tabs — this list is the contract. Bit us 2026-08-26
# when a tab rebuild deleted EMAIL_TEMPLATES/_substitute wholesale.
_src_full = open(PAGE).read()
_REQUIRED = ["EMAIL_TEMPLATES = {", "def _substitute", "def _used_tokens",
             "def _row_subs", "def _missing_tokens", "def _fetch_watchers_page",
             "def _cached_log_df", "def _cached_tracking_df",
             "def _render_theme_plan", "def _load_theme_plan",
             "def _load_segment_suggestions", "def _voice_hold_companies", "def _is_voice_hold",
             "def _normalize_ai_segment", "def _normalize_company", "def _step_header"]
_missing = [r for r in _REQUIRED if r not in _src_full]
assert not _missing, f"SMOKE FAIL — definitions deleted: {_missing}"
_tab_idx = _src_full.index("with tab_compose")
_late = [r for r in _REQUIRED if _src_full.index(r) > _tab_idx]
assert not _late, f"SMOKE FAIL — defined after tab_compose (NameError at load): {_late}"
print(f"SYMBOLS OK — {len(_REQUIRED)} module-level definitions present & ordered")
