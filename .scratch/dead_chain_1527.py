"""Section 1527 probe (read-only): which module-level names become unreferenced once the 4 retired stages go."""
import ast, re, subprocess, sys
from pathlib import Path

TARGETS = {
    "code_intelligence/agent/access_guards.py": ["_backfill_missing_required_groups", "_strip_core_only_group_mentions"],
    "code_intelligence/rules/security_locks.py": ["_backfill_missing_security_lock_amount", "_correct_security_lock_threshold_contradictions"],
}
ROOT = Path(".")
prod_files = [p for p in ROOT.rglob("*.py") if not any(x in p.parts for x in (".venv", ".scratch", "tests", "__pycache__", ".git", "captures")) and not p.name.startswith("test_")]

def toplevel_defs(tree):
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            out[node.name] = (node.lineno, node.end_lineno)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = (node.lineno, node.end_lineno)
    return out

PROTECT = {"_backfill_missing_group_escalation_note", "_backfill_missing_approval_guard_facts", "_backfill_fiscal_lock_scope_fact"}
removed = {}  # module -> set of names removed
for mod, names in TARGETS.items():
    removed[mod] = set(names)

changed = True
while changed:
    changed = False
    for mod in TARGETS:
        src = Path(mod).read_text(encoding="utf-8")
        tree = ast.parse(src)
        defs = toplevel_defs(tree)
        lines = src.split("\n")
        removed_ranges = [defs[n] for n in removed[mod] if n in defs]
        def in_removed(lineno):
            return any(a <= lineno <= b for a, b in removed_ranges)
        for name, (a, b) in defs.items():
            if name in removed[mod] or name.startswith("__"):
                continue
            # references anywhere in production (other than the definition itself and removed ranges of this module)
            refs = 0
            pat = re.compile(r"\b" + re.escape(name) + r"\b")
            for p in prod_files:
                text = p.read_text(encoding="utf-8", errors="replace").split("\n")
                for i, line in enumerate(text, 1):
                    if not pat.search(line):
                        continue
                    if str(p) == mod and (a <= i <= b or in_removed(i)):
                        continue
                    if str(p) == "core/graph/graph_compat.py":
                        continue  # re-export list, handled separately
                    refs += 1
            if refs == 0 and name not in PROTECT and (name.startswith("_") or name.isupper()):
                removed[mod].add(name)
                changed = True

for mod, names in removed.items():
    src = Path(mod).read_text(encoding="utf-8")
    defs = toplevel_defs(ast.parse(src))
    print(mod)
    for n in sorted(names, key=lambda x: defs.get(x, (0, 0))[0]):
        a, b = defs.get(n, (0, 0))
        print(f"   {n:55} lignes {a}-{b} ({b - a + 1})")
