#!/usr/bin/env python3
"""Catch 'read before assignment' inside a Streamlit tab body.

py_compile and the prologue smoke both pass on this class of bug, because the
code is valid Python and the break is in EXECUTION ORDER, not syntax. It has
now bitten twice: moving Campaign comparison above Segments left it reading
_exp, _email_seg and _seg_order before the Segments block created them, which
takes the whole Analytics tab down at render time.

Static, no Streamlit session needed. Comprehension / lambda / for-loop targets
are ignored, since AST reports their Load before their Store.
"""
import ast
import sys

PAGE = "pages/3_crm.py"
TABS = ["tab_analytics", "tab_compose", "tab_calendar"]


def scoped_names(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for g in n.generators:
                out |= {t.id for t in ast.walk(g.target) if isinstance(t, ast.Name)}
        elif isinstance(n, ast.Lambda):
            out |= {a.arg for a in n.args.args}
        elif isinstance(n, (ast.For, ast.AsyncFor)):
            out |= {t.id for t in ast.walk(n.target) if isinstance(t, ast.Name)}
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.withitem) and n.optional_vars is not None:
            out |= {t.id for t in ast.walk(n.optional_vars) if isinstance(t, ast.Name)}
    return out


def check(lines, tab):
    start = next((i for i, l in enumerate(lines) if f"with {tab}" in l), None)
    if start is None:
        return []
    body = lines[start + 1:]
    end = next((i for i, l in enumerate(body)
                if l.strip() and not l.startswith((" ", "\t"))), len(body))
    tree = ast.parse("def _f():\n" + "\n".join("    " + l for l in body[:end]))
    skip = scoped_names(tree)
    assigned, problems = {}, []

    class V(ast.NodeVisitor):
        def visit_Name(self, n):
            nm = n.id
            if not nm.startswith("_") or nm.startswith("__") or nm in skip:
                return
            if isinstance(n.ctx, ast.Store):
                assigned.setdefault(nm, n.lineno)
            elif isinstance(n.ctx, ast.Load) and nm not in assigned:
                problems.append((nm, n.lineno))

    V().visit(tree)
    return sorted({(n, l, assigned[n]) for n, l in problems if n in assigned})


def main():
    lines = open(PAGE).read().split("\n")
    bad = False
    for tab in TABS:
        for name, read_at, assigned_at in check(lines, tab):
            print(f"✗ {tab}: {name} read at tab-line {read_at}, "
                  f"assigned at {assigned_at}")
            bad = True
    if bad:
        print("\nTAB ORDER FAIL — a section was moved above the code it depends on.")
        return 1
    print("TAB ORDER OK — no local read before assignment")
    return 0


import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))


def check_no_bare_int_sum():
    """int(<expr>.sum()) is banned in 3_crm.py — use _isum().

    An empty object-dtype Series sums to '' on the pandas Streamlit Cloud runs
    (string identity, not 0), so int() raises ValueError and takes the tab down.
    Local pandas returns 0, so no test on this machine can catch it — the only
    defence is not writing the pattern.
    """
    import re as _re
    raw = open(_os.path.join(_ROOT, 'pages', '3_crm.py'), encoding='utf-8').read()
    # Blank out comments so the helper's own docs don't trip the check.
    src = '\n'.join(_re.sub(r'#.*$', '', l) for l in raw.split('\n'))
    bad = []
    for m in _re.finditer(r'int\(\s*\(?[^\n]{0,90}?\.sum\(\)\s*\)', src):
        line = src[:m.start()].count('\n') + 1
        if 'pd.to_numeric' in m.group(0):      # the _isum helper itself
            continue
        bad.append((line, m.group(0).strip()))
    if bad:
        print("INT-SUM CHECK FAILED — use _isum(...) instead of int(....sum()):")
        for line, txt in bad:
            print(f"  3_crm.py:{line}: {txt[:90]}")
        return 1
    print("INT-SUM OK — no bare int(....sum())")
    return 0




def check_home_css():
    """Every class the homepage uses must have a CSS rule.

    Both the news and security styles were written anchored on a `.foot-tip`
    selector that had already been deleted. str.replace with no match does
    nothing and raises nothing, so the HTML shipped with no styling at all
    and looked broken in the browser while every test passed.
    """
    import re as _re
    src = open(_os.path.join(_ROOT, 'pages', '0_home.py'), encoding='utf-8').read()
    m = _re.search(r'<style>(.*?)</style>', src, _re.S)
    if not m:
        print("HOME CSS OK — no <style> block")
        return 0
    defined = set(_re.findall(r'\.([\w-]+)\s*[\{,:]', m.group(1)))
    used = set(_re.findall(r'class="([\w\s-]+)"', src))
    used = {c for group in used for c in group.split()}
    missing = sorted(used - defined)
    if missing:
        print("HOME CSS FAILED — class used with no rule: " + ", ".join(missing))
        return 1
    print(f"HOME CSS OK — {len(used)} classes, all defined")
    return 0


if __name__ == "__main__":
    sys.exit(main() or check_no_bare_int_sum() or check_home_css())
