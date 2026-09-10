#!/usr/bin/env python3
"""
todo/contexte.txt section 497 -- Bug 3, second candidate source.

Rejoue isolement le hop 0 de la trace 667ebb31926a (analyze_security_locks
sur account.move) pour recuperer le texte COMPLET de l'observation --
captures/reasoning_trace.jsonl tronque observation_summary a 300 caracteres,
ce qui a masque ce hop entierement depuis le debut de l'investigation Bug 3
(sections 495-497, seul le hop 1 avait ete rejoue jusqu'ici).

_backfill_missing_override_chain_amount() scanne l'INTEGRALITE de
scoped_tool_output (tous les hops de la question concatenes), pas seulement
le bloc du hop qui a declenche le backfill -- un fragment "rec.xxx > 500"
cache dans ce hop 0 serait donc tout aussi capable de produire le
[FAIT DETERMINISTIQUE] "500EUR" observe que le hop 1 (deja rejoue 4x,
toujours propre).

Lecture seule : aucune mutation du graphe, aucune ecriture DB, aucun appel
LLM (analyze_security_locks est deterministe, pas d'interpretation LLM).
"""

import re
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from code_intelligence.knowledge_rules.graph import get_code_intelligence_graph
from code_intelligence.agent.ci_agent_node.context.agent_tools import find_model_source_filepaths, _sort_filepaths_custom_first
from code_intelligence.knowledge_rules.security import analyze_python_security_locks

_OVERRIDE_CHAIN_AMOUNT_RE = re.compile(r"rec\.\w+\s*>\s*(\d[\d\s]*\d)")


def main():
    print("=" * 80)
    print(" DIAG -- analyze_security_locks(account.move)")
    print("=" * 80)

    G = get_code_intelligence_graph()

    filepaths = find_model_source_filepaths(G, "account.move")
    print(f"\nFichiers source associes a 'account.move' ({len(filepaths)}) :")
    for fp in sorted(filepaths):
        print(f"  - {fp}")

    summaries = []
    for fp in _sort_filepaths_custom_first(filepaths):
        p = Path(fp)
        if p.exists():
            code = p.read_text(encoding="utf-8")
            analysis = analyze_python_security_locks(code, fp)
            summaries.append(analysis.summary_text)

    result = "\n\n".join(summaries) if summaries else "No security analysis results."

    print("\n--- TEXTE COMPLET (non tronque) ---\n")
    print(result)
    print("\n--- FIN TEXTE COMPLET ---\n")

    matches = list(_OVERRIDE_CHAIN_AMOUNT_RE.finditer(result))
    print(f"_OVERRIDE_CHAIN_AMOUNT_RE : {len(matches)} match(es)")
    for m in matches:
        start = max(0, m.start() - 100)
        end = min(len(result), m.end() + 100)
        print(f"\n  amount={m.group(1)!r}")
        print(f"  contexte: ...{result[start:end]}...")


if __name__ == "__main__":
    main()
