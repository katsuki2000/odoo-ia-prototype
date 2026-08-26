#!/usr/bin/env python3
"""
scripts/diagnose_h4_04c_05c_gap.py

Diagnostic script, isolated rejeu --  section 129, suite.

Section 129 confirmed the root cause for  (custom.asset.loan,
"quelles sont toutes les conditions verifiees par action_demarrer"):
resolved_concept.is_resolved=True but no GOVERNANCE_SIGNAL_TERMS hit ->
falls through to the documentaire fallback -> clean "no source" answer.

This script isolates the 4 questions NOT yet checked individually this way
(04b, 04c, 05a, 05c) to determine, for each, exactly which volet of the
AND-gate in core/routing.py::_concept_suggests_code_intelligence fails (if
any) -- volet 1 (resolved_concept.is_resolved) or volet 2 (a
GOVERNANCE_SIGNAL_TERMS hit) -- and to capture the route() log line plus
the resolved_concept dict for each, before comparing against the actual
full-pipeline answer (clean refusal vs hallucination with fabricated
sources).

Read-only with respect to the pipeline itself: calls resolve_business_term
directly (llm=None, same as route()) and query_graph() (real full
pipeline) -- writes nothing to disk, no mandate needed to run this, only
to act on what it finds.
"""

import logging
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from core.graph import query_graph
from core.routing import (
    GOVERNANCE_SIGNAL_TERMS_FOLDED,
    _concept_suggests_code_intelligence,
    _fold_accents,
)
from code_intelligence.business_resolver import resolve_business_term
from code_intelligence.ci_graph_loader import get_code_intelligence_graph

QUESTIONS = [
    (
        "",
        "Dans le modèle custom.purchase.request, quelles sont toutes "
        "les conditions vérifiées par action_valider ?",
    ),
    (
        "",
        "Un utilisateur membre du groupe purchase_manager peut-il, à "
        "lui seul, valider n'importe quelle demande d'achat quel que "
        "soit son montant ?",
    ),
    (
        "",
        "Pourquoi je n'arrive pas à démarrer une mise à disposition de "
        "matériel dont je suis à la fois le demandeur d'achat et le "
        "bénéficiaire ?",
    ),
    (
        "",
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
    question_folded = _fold_accents(question.lower())

    print(f"resolved_concept.is_resolved   : {getattr(resolved, 'is_resolved', None)}")
    print(f"resolved_concept.resolved_models: {getattr(resolved, 'resolved_models', None)}")
    print(f"resolved_concept.confidence    : {getattr(resolved, 'confidence', None)}")
    print(f"resolved_concept.source_step   : {getattr(resolved, 'source_step', None)}")

    hit_terms = [t for t in GOVERNANCE_SIGNAL_TERMS_FOLDED if t in question_folded]
    print(f"GOVERNANCE_SIGNAL_TERMS hit(s) : {hit_terms or '(none)'}")

    gate_result = _concept_suggests_code_intelligence(question_folded, resolved)
    print(f"_concept_suggests_code_intelligence -> {gate_result}")

    if not getattr(resolved, "is_resolved", False):
        print("[DIAGNOSIS] Volet 1 FAILS (is_resolved=False) -- gate can never fire regardless of terms.")
    elif not hit_terms:
        print("[DIAGNOSIS] Volet 2 FAILS (no governance term) -- same class as 05b (section 129).")
    else:
        print("[DIAGNOSIS] Both volets PASS at the route()-level gate -- if full pipeline still misroutes "
              "or hallucinates, the cause is downstream of this gate (not this AND-gate itself).")

    print("\n--- full pipeline (query_graph) ---")
    response = query_graph(question=question, user_groups=[])
    answer = response.answer if response else "(no response)"
    print(f"Réponse:\n{answer}\n")


def main():
    for qid, question in QUESTIONS:
        diagnose_one(qid, question)


if __name__ == "__main__":
    main()
