"""
code_intelligence/tests/test_bloc17_navigation_howto_intent.py

Bloc 17, Etage 1, Jour 4 (todo/contexte.txt section 646-647): the new
QuestionIntent.NAVIGATION_HOWTO -- additive only, must not reclassify any
existing benchmark question. Covers the heuristic classifier
(classify_question_intent, production fallback path) and the
INTENT_TO_ROUTE mapping. The LLM classifier's system prompt addition
(prompts.py) is not unit-testable without a live LLM call -- covered only
by manual/benchmark verification.
"""

import json

import pytest

from code_intelligence.agent.investigation.classifier import classify_question_intent
from code_intelligence.agent.investigation.schemas import QuestionIntent, INTENT_TO_ROUTE
from core.schemas import QueryRoute


def test_navigation_howto_maps_to_code_intelligence():
    assert INTENT_TO_ROUTE[QuestionIntent.NAVIGATION_HOWTO] == QueryRoute.CODE_INTELLIGENCE.value


@pytest.mark.parametrize("question", [
    "Ou se trouve le menu pour creer une demande d'achat ?",
    "Où se trouve le menu pour créer une demande d'achat ?",
    "Comment accéder à l'écran des factures ?",
    "Dans quel onglet se trouve le champ de référence ?",
    "Où puis-je trouver la configuration des taxes ?",
    "Comment naviguer jusqu'à la page des avoirs ?",
])
def test_navigation_vocabulary_classifies_as_navigation_howto(question):
    assert classify_question_intent(question) == QuestionIntent.NAVIGATION_HOWTO


@pytest.mark.parametrize("question", [
    "Où est le bouton pour valider la commande ?",
    "Comment passer du statut brouillon au statut confirmé ?",
])
def test_button_and_transition_vocabulary_stays_workflow_state(question):
    """'bouton'/transitions must keep firing _WORKFLOW_PATTERNS (checked
    earlier in the cascade) -- not be reclassified as navigation_howto,
    even though both ultimately route to the same CODE_INTELLIGENCE
    branch. Distinguishing them matters for the Investigation Planner
    (Bloc P1), which branches on the exact intent value."""
    assert classify_question_intent(question) == QuestionIntent.WORKFLOW_STATE


def test_governance_vocabulary_wins_over_incidental_menu_word():
    """A question that happens to contain 'menu' but is really about
    permissions must stay GOVERNANCE_SECURITY -- governance is checked
    before navigation in the cascade."""
    assert classify_question_intent(
        "Qui a le droit de voir le menu de configuration ?"
    ) == QuestionIntent.GOVERNANCE_SECURITY


class TestBenchmarkRegressionPin:
    """Section 644 identified DOC-01/02/03/04/10 as real 'comment faire
    pour' questions currently answered by RAG (documentary_policy). The
    Bloc 17 Jour 4 navigation heuristic must be purely additive: none of
    these five may be reclassified. Pinned against the actual benchmark
    text (tests/benchmark_questions.json), not a paraphrase, so a future
    edit to either file that breaks this is caught immediately."""

    @pytest.fixture(scope="class")
    def benchmark_doc_questions(self):
        with open("tests/benchmark_questions.json", encoding="utf-8") as f:
            data = json.load(f)
        by_id = {q["id"]: q["question"] for q in data["questions"]}
        return {qid: by_id[qid] for qid in ("DOC-01", "DOC-02", "DOC-03", "DOC-04", "DOC-10") if qid in by_id}

    def test_all_five_still_present_in_benchmark(self, benchmark_doc_questions):
        assert set(benchmark_doc_questions) == {"DOC-01", "DOC-02", "DOC-03", "DOC-04", "DOC-10"}

    def test_none_reclassified_away_from_documentary_policy(self, benchmark_doc_questions):
        for qid, question in benchmark_doc_questions.items():
            intent = classify_question_intent(question)
            assert intent == QuestionIntent.DOCUMENTARY_POLICY, (
                f"{qid} ({question!r}) reclassified to {intent.value} -- "
                f"Bloc 17 navigation heuristic must be purely additive."
            )
