import sys
sys.path.insert(0, "/media/donnee/projets/odoo-ia-prototype")

from code_intelligence.graph.loader import get_code_intelligence_graph
from code_intelligence.agent.tool_helpers import (
    set_graph_ref, set_current_question, find_model_source_filepaths,
    _sort_filepaths_custom_first,
)
from pathlib import Path

question = ("Quelles regles empechent de supprimer une commande d'achat ou une de ses lignes selon leur etat, "
            "et quelle contrainte SQL distincte s'applique sur les lignes elles-memes ?")

G = get_code_intelligence_graph()
set_graph_ref(G)
set_current_question(question)

from code_intelligence.rules.security import analyze_python_security_locks
from code_intelligence.rules.security_evidence import format_security_locks_summary, assemble_security_lock_blocks
from code_intelligence.agent.context import PER_TOOL_OBSERVATION_CAPS

for model_name in ["purchase.order"]:
    filepaths = find_model_source_filepaths(G, model_name)
    sorted_fp = _sort_filepaths_custom_first(filepaths)
    print(f"=== {model_name}: {len(sorted_fp)} filepaths (sorted custom-first) ===")
    summaries = []
    for fp in sorted_fp:
        p = Path(fp)
        if not p.exists():
            print(f"  MISSING: {fp}")
            continue
        code = p.read_text(encoding="utf-8")
        analysis = analyze_python_security_locks(code, fp)
        summary = format_security_locks_summary(analysis, code, fp)
        summaries.append(summary)
        print(f"  [{len(summary)} chars] {fp}")
    total = sum(len(s) for s in summaries)
    print(f"  TOTAL unbudgeted = {total} chars, budget = {PER_TOOL_OBSERVATION_CAPS['analyze_security_locks']}")
    final = assemble_security_lock_blocks(summaries, PER_TOOL_OBSERVATION_CAPS["analyze_security_locks"])
    print(f"  FINAL assembled = {len(final)} chars")
    print("--- does final contain the delete-condition message? ---")
    print("'you must cancel it first' in final:", "you must cancel it first" in final)
    print("'_unlink_if_cancelled' in final:", "_unlink_if_cancelled" in final)
