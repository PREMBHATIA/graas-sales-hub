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


if __name__ == "__main__":
    sys.exit(main())
