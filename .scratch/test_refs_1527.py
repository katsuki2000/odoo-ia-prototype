import ast, re, sys
from pathlib import Path
NAMES = ["_SENTENCE_SPLIT_RE","_grounded_core_only_groups","_strip_core_only_group_mentions","_extract_required_groups_for_amount","_BLOCK_FILE_LINK_RE","_block_is_custom_module_file","_restrict_blocks_to_custom_modules","_backfill_missing_required_groups","_SECURITY_LOCK_MESSAGES_MARKER","_extract_security_lock_condition_amounts","_backfill_missing_security_lock_amount","_correct_security_lock_threshold_contradictions"]
pat = re.compile(r"\b(" + "|".join(NAMES) + r")\b")
for f in sys.argv[1:]:
    src = Path(f).read_text(encoding="utf-8")
    lines = src.split("\n")
    tree = ast.parse(src)
    print("==", f, f"({len(lines)} lignes)")
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            seg = "\n".join(lines[node.lineno-1:node.end_lineno])
            hits = sorted(set(pat.findall(seg)))
            if isinstance(node, ast.ClassDef):
                tests = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test")]
                tests_hit = [n.name for n in tests if pat.search("\n".join(lines[n.lineno-1:n.end_lineno]))]
                if hits:
                    print(f"  class {node.name} L{node.lineno}-{node.end_lineno} : {len(tests_hit)}/{len(tests)} tests concernes ; noms : {', '.join(h.replace('_','',1)[:28] for h in hits)}")
            elif hits:
                print(f"  def {node.name} L{node.lineno}-{node.end_lineno} ; noms : {', '.join(hits)}")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            seg = "\n".join(lines[node.lineno-1:node.end_lineno])
            if pat.search(seg):
                print(f"  import L{node.lineno}-{node.end_lineno}")
