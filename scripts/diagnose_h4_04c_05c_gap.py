#!/usr/bin/env python3
"""
scripts/diagnose_h4_04c_05c_gap.py

Diagnostic script, isolated rejeu -- section 129, suite.

Migrated (Bloc P1 Jour 3-4): uses concept_suggests_code_intelligence_v2()
and classify_question_intent() instead of the removed
GOVERNANCE_SIGNAL_TERMS / _concept_suggests_code_intelligence.

Read-only with respect to the pipeline itself: calls resolve_business_term
directly (llm=None, same as route()) and query_graph() (real full
pipeline) -- writes nothing to disk.
"""

import logging
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from core.graph.graph import query_graph
from core.routing.routing import _fold_accents
from code_intelligence.agent.investigation_classifier import (
    concept_suggests_code_intelligence_v2,
    classify_question_intent,
)
from code_intelligence.agent.resolver import resolve_business_term
from code_intelligence.graph.loader import get_code_intelligence_graph

QUESTIONS = [
    (
        "H4-04b",
        "Dans le modèle custom.purchase.request, quelles sont toutes "
        "les conditions vérifiées par action_valider ?",
    ),
    (
        "H4-04c",
        "Un utilisateur membre du groupe purchase_manager peut-il, à "
        "lui seul, valider n'importe quelle demande d'achat quel que "
        "soit son montant ?",
    ),
    (
        "H4-05a",
        "Pourquoi je n'arrive pas à démarrer une mise à disposition de "
        "matériel dont je suis à la fois le demandeur d'achat et le "
        "bénéficiaire ?",
    ),
    (
        "H4-05c",
        "Si une mise à disposition de matériel n'est reliée à aucune "
        "demande d'achat, la règle de séparation des rôles "
        "(bénéficiaire différent du demandeur) s'applique-t-elle quand "
        "même, quel que soit le montant du matériel ?",
    ),
]


def diagnose_one(qid: str, question: str):
    print("=" * 80)
    print(f" {qid}")
    print("=" * 80)
    print(f"Question: {question}\n")

    G = get_code_intelligence_graph()
    resolved = resolve_business_term(question, G, llm=None)

    print(f"resolved_concept.is_resolved   : {getattr(resolved, 'is_resolved', None)}")
    print(f"resolved_concept.resolved_models: {getattr(resolved, 'resolved_models', None)}")
    print(f"resolved_concept.confidence    : {getattr(resolved, 'confidence', None)}")
    print(f"resolved_concept.source_step   : {getattr(resolved, 'source_step', None)}")

    intent = classify_question_intent(question, resolved, G)
    print(f"classify_question_intent       : {intent.value}")

    gate_result = concept_suggests_code_intelligence_v2(question, resolved, G)
    print(f"concept_suggests_code_intelligence_v2 -> {gate_result}")

    if not getattr(resolved, "is_resolved", False):
        print("[DIAGNOSIS] concept unresolved -- gate cannot fire.")
    elif not gate_result:
        print("[DIAGNOSIS] concept resolved but intent classified as non-CI (documentary/ERP).")
    else:
        print("[DIAGNOSIS] Gate PASSES -- routes to CODE_INTELLIGENCE.")

    print("\n--- full pipeline (query_graph) ---")
    response = query_graph(question=question, user_groups=[])
    answer = response.answer if response else "(no response)"
    print(f"Réponse:\n{answer}\n")


def main():
    for qid, question in QUESTIONS:
        diagnose_one(qid, question)


if __name__ == "__main__":
    main()
