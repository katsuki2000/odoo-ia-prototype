import ast, io, re, sys, tokenize
FR = re.compile(r"\b(le|la|les|des|une|pour|est|que|avec|dans|sur|pas|aux|du|ce|cette|sont|plus|mais|donc|chaque|sans|lorsque|ainsi|aussi|nous|vous|ou|et le|et la)\b", re.I)
ACC = re.compile(r"[àâçéèêëîïôùûü]", re.I)
def french(t):
    words = FR.findall(t)
    return bool(ACC.search(t)) and len(words) >= 1 or len(words) >= 3
files = [l.strip() for l in open("/tmp/prod_files.txt") if l.strip().endswith(".py")]
hits = {}
for f in files:
    if f.startswith(("scripts/", "odoo_addons/custom_", "odoo_addons/miro_ai_discuss")): continue
    try: src = open(f, encoding="utf-8").read()
    except Exception: continue
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT and french(tok.string):
                hits.setdefault(f, []).append((tok.start[0], tok.string.strip()[:110]))
        tree = ast.parse(src)
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                d = ast.get_docstring(n, clean=False)
                if d and french(d):
                    ln = n.body[0].lineno
                    hits.setdefault(f, []).append((ln, "DOCSTRING: " + d.strip().splitlines()[0][:100]))
    except SyntaxError: pass
tot = 0
for f, hs in sorted(hits.items()):
    print(f"{len(hs):3d} {f}")
    tot += len(hs)
print("TOTAL", tot, "in", len(hits), "files")
if "-v" in sys.argv:
    for f, hs in sorted(hits.items()):
        for ln, t in sorted(hs): print(f"{f}:{ln}: {t}")
