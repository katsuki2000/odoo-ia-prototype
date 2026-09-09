#!/usr/bin/env python3
"""
todo/contexte.txt section 495 -- Bug 3 (contamination "500EUR" dans un
[FAIT DETERMINISTIQUE] backfille par _backfill_missing_override_chain_amount).

Rejoue isolement le hop 1 de la trace 667ebb31926a
(analyze_method_override_chain sur account.move.action_valider_avoir) pour
recuperer le texte COMPLET de l'observation -- captures/reasoning_trace.jsonl
tronque observation_summary a 300 caracteres, ce qui masque la ligne
"Interpretation LLM" potentiellement en cause.

Lecture seule : aucune mutation du graphe, aucune ecriture DB. Un seul appel
LLM reel (meme cout qu'une question normale posee au widget).
"""

import re
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from code_intelligence.graph import get_code_intelligence_graph
from code_intelligence.overrides import analyze_method_override_chain
from core.llm_client import get_chat_llm

_OVERRIDE_CHAIN_AMOUNT_RE = re.compile(r"rec\.\w+\s*>\s*(\d[\d\s]*\d)")


def main():
    print("=" * 80)
    print(" DIAG -- analyze_method_override_chain(account.move, action_valider_avoir)")
    print("=" * 80)

    G = get_code_intelligence_graph()
    llm = get_chat_llm()

    result = analyze_method_override_chain(
        G, "account.move", "action_valider_avoir", llm=llm
    )

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

    if "Interpretation LLM" in result or "Interprétation LLM" in result:
        idx = result.find("Interpr")
        print("\n--- LIGNE 'Interpretation LLM' (texte libre, pas AST) ---")
        print(result[idx:])
    else:
        print("\n[INFO] Aucune ligne 'Interpretation LLM' dans ce rejeu -- "
              "le LLM peut varier d'un appel a l'autre (non-deterministe), "
              "relancer si ce script ne reproduit pas immediatement le cas.")


if __name__ == "__main__":
    main()
