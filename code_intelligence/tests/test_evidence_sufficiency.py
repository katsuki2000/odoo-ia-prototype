"""
code_intelligence/tests/test_evidence_sufficiency.py

Tranche 1 (todo/contexte.txt section 405/406): isolated tests for
core/evidence_sufficiency.py::assess_evidence_sufficiency(). Not wired into
graph.py yet -- this only exercises the primitive on its own.
"""

import pytest

from core.evidence_sufficiency import (
    EvidenceSufficiencyStatus,
    assess_evidence_sufficiency,
)
from code_intelligence.deterministic_tools import NOT_FOUND_MARKER


def test_canned_no_data_answer_is_insufficient():
    result = assess_evidence_sufficiency(
        tool_observations=["some observation"],
        hop_count=1,
        final_answer="Je n'ai pas de données disponibles dans le graphe de connaissances.",
    )
    assert result.status is EvidenceSufficiencyStatus.INSUFFICIENT


def test_out_of_scope_model_answer_is_insufficient():
    result = assess_evidence_sufficiency(
        tool_observations=[],
        hop_count=0,
        final_answer="Ce modele n'est pas present dans le corpus indexe par cet outil.",
    )
    assert result.status is EvidenceSufficiencyStatus.INSUFFICIENT


def test_no_observations_is_insufficient():
    result = assess_evidence_sufficiency(
        tool_observations=[],
        hop_count=0,
        final_answer="Reponse quelconque.",
    )
    assert result.status is EvidenceSufficiencyStatus.INSUFFICIENT
    assert result.total_observation_count == 0


def test_zero_hop_count_with_observations_is_insufficient():
    # Defensive guard: hop_count == 0 wins even if observations is non-empty.
    result = assess_evidence_sufficiency(
        tool_observations=["stray observation"],
        hop_count=0,
        final_answer="Reponse quelconque.",
    )
    assert result.status is EvidenceSufficiencyStatus.INSUFFICIENT


def test_all_observations_not_found_marker_is_insufficient():
    result = assess_evidence_sufficiency(
        tool_observations=[f"Field 'x' {NOT_FOUND_MARKER}."],
        hop_count=1,
        final_answer="Reponse quelconque.",
    )
    assert result.status is EvidenceSufficiencyStatus.INSUFFICIENT
    assert result.relevant_observation_count == 0
    assert result.total_observation_count == 1


def test_all_observations_execution_error_is_insufficient():
    result = assess_evidence_sufficiency(
        tool_observations=["Error executing analyze_security_locks: timeout"],
        hop_count=1,
        final_answer="Reponse quelconque.",
    )
    assert result.status is EvidenceSufficiencyStatus.INSUFFICIENT
    assert result.relevant_observation_count == 0


def test_indeterminate_fact_marker_is_insufficient_not_conflicting():
    # Core regression for the Stagiaire correction (contexte.txt section 405):
    # an indeterminate/unresolved verdict must map to INSUFFICIENT, never
    # CONFLICTING.
    result = assess_evidence_sufficiency(
        tool_observations=["can_view_amount_v2() = indeterminate: dynamic getattr on field"],
        hop_count=2,
        final_answer="Le resultat de can_view_amount_v2() = indeterminate pour ce cas.",
    )
    assert result.status is EvidenceSufficiencyStatus.INSUFFICIENT
    assert result.status is not EvidenceSufficiencyStatus.CONFLICTING


def test_dynamic_uncertainty_marker_is_insufficient():
    result = assess_evidence_sufficiency(
        tool_observations=["method dispatches via getattr on a runtime value"],
        hop_count=2,
        final_answer="Je ne peux pas classifier avec certitude ce chemin d'execution.",
    )
    assert result.status is EvidenceSufficiencyStatus.INSUFFICIENT


def test_relevant_observation_with_clean_answer_is_sufficient():
    result = assess_evidence_sufficiency(
        tool_observations=["group_purchase_manager has write access to purchase.request"],
        hop_count=1,
        final_answer="Le groupe Purchase Manager a acces en ecriture.",
    )
    assert result.status is EvidenceSufficiencyStatus.SUFFICIENT
    assert result.relevant_observation_count == 1
    assert result.total_observation_count == 1


def test_mixed_relevant_and_irrelevant_observations_counts_correctly():
    result = assess_evidence_sufficiency(
        tool_observations=[
            f"Field 'y' {NOT_FOUND_MARKER}.",
            "group_purchase_manager has write access to purchase.request",
            "No server actions (ir.actions.server) found for model x",
        ],
        hop_count=3,
        final_answer="Le groupe Purchase Manager a acces en ecriture.",
    )
    assert result.status is EvidenceSufficiencyStatus.SUFFICIENT
    assert result.relevant_observation_count == 1
    assert result.total_observation_count == 3


def test_to_display_dict_matches_result_fields():
    result = assess_evidence_sufficiency(
        tool_observations=["group_x has access"],
        hop_count=1,
        final_answer="Reponse etayee.",
    )
    display = result.to_display_dict()
    assert display == {
        "status": "sufficient",
        "reasons": result.reasons,
        "relevant_observation_count": 1,
        "total_observation_count": 1,
    }


def test_conflicting_status_never_returned_even_with_contradiction_wording():
    # CONFLICTING is part of the contract but not produced yet: synthesis-
    # level contradictions are already neutralized upstream (ci_helpers.py)
    # before this function ever sees the final answer.
    result = assess_evidence_sufficiency(
        tool_observations=["group_x has access", "group_x does not have access"],
        hop_count=2,
        final_answer="Deux resultats contradictoires ont ete trouves.",
    )
    assert result.status is not EvidenceSufficiencyStatus.CONFLICTING
