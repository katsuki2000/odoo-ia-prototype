"""
code_intelligence/tests/test_intent_llm_classifier_and_resolution.py

Bloc P1 -- classifieur LLM unique (routing), Tranche 3 (todo/contexte.txt
section 394+): couverture dediee pour classify_question_intent_llm() et
resolve_question_intent(), ni l'un ni l'autre couverts par
test_bloc_p1_j1_2_investigation_plan.py (qui ne teste que
classify_question_intent(), le filet deterministe, inchange).

Patron de mock aligne sur test_business_resolver.py (seul autre appel LLM
borne du projet) : mock construit a la main, jamais un vrai client Groq.
Ici la forme est with_structured_output().invoke(messages) -> objet portant
.intent, et non llm.invoke(messages) -> objet portant .content -- deux
fonctions differentes sont patchees en consequence : get_chat_llm() est
remplace par un mock dont with_structured_output() renvoie un second mock
dont invoke() est controle par le test ; invoke_with_rate_limit() est
laisse INTACT dans tous les tests (il n'est qu'un wrapper fin autour de
structured_llm.invoke(), voir core/llm_client.py) -- max_retries=1 passe
par classify_question_intent_llm() garantit qu'un echec simule via
side_effect ne declenche qu'un seul essai avant de remonter, sans attente
de rate-limit reelle.
"""

from unittest.mock import Mock, patch

import pytest

from code_intelligence.agent.business_resolver import ResolvedConcept
from code_intelligence.agent.investigation import (
    IntentResolution,
    QuestionIntent,
    classify_question_intent,
    classify_question_intent_llm,
    resolve_question_intent,
)


def _mock_structured_llm(intent: QuestionIntent) -> Mock:
    """Build a minimal LangChain-shaped mock for the
    llm.with_structured_output(...).invoke(messages) -> IntentClassificationLLMResponse
    call chain used by classify_question_intent_llm()."""
    structured_llm = Mock()
    structured_llm.invoke.return_value = Mock(intent=intent)
    return structured_llm


def _mock_get_chat_llm(structured_llm: Mock):
    """Build the get_chat_llm() replacement: a bare llm mock whose
    with_structured_output() returns the given structured_llm mock."""
    llm = Mock()
    llm.with_structured_output.return_value = structured_llm
    return Mock(return_value=llm)


# ── classify_question_intent_llm() -- success case ───────────────────────────

def test_llm_classifier_returns_intent_on_success():
    structured_llm = _mock_structured_llm(QuestionIntent.GOVERNANCE_SECURITY)
    with patch(
        "core.llm_client.get_chat_llm",
        _mock_get_chat_llm(structured_llm),
    ):
        result = classify_question_intent_llm("Qui peut voir un avoir de 80 000€ ?")

    assert result == QuestionIntent.GOVERNANCE_SECURITY
    structured_llm.invoke.assert_called_once()


def test_llm_classifier_passes_the_question_to_the_llm():
    """The question text must reach the LLM call, not be silently dropped."""
    structured_llm = _mock_structured_llm(QuestionIntent.WORKFLOW_STATE)
    question = "Quelles sont les étapes du workflow de validation ?"
    with patch(
        "core.llm_client.get_chat_llm",
        _mock_get_chat_llm(structured_llm),
    ):
        classify_question_intent_llm(question)

    messages = structured_llm.invoke.call_args[0][0]
    assert any(question in getattr(m, "content", "") for m in messages)


# ── classify_question_intent_llm() -- failure cases (never raise, always None) ──

def test_llm_classifier_returns_none_on_generic_exception():
    """Any unexpected exception (network error, provider outage, etc.) must
    be swallowed and reported as None -- never propagated to the caller."""
    structured_llm = Mock()
    structured_llm.invoke.side_effect = RuntimeError("simulated API failure")
    with patch(
        "core.llm_client.get_chat_llm",
        _mock_get_chat_llm(structured_llm),
    ):
        result = classify_question_intent_llm("Qui peut voir un avoir de 80 000€ ?")

    assert result is None


def test_llm_classifier_returns_none_on_timeout():
    """A timeout (e.g. requests.exceptions.Timeout or an equivalent transport
    error) must degrade to None just like any other failure -- Tranche 1
    deliberately treats every failure mode uniformly (single try/except),
    rather than special-casing timeouts for a different outcome."""
    structured_llm = Mock()
    structured_llm.invoke.side_effect = TimeoutError("simulated network timeout")
    with patch(
        "core.llm_client.get_chat_llm",
        _mock_get_chat_llm(structured_llm),
    ):
        result = classify_question_intent_llm("Qui peut voir un avoir de 80 000€ ?")

    assert result is None


def test_llm_classifier_returns_none_on_malformed_structured_output():
    """with_structured_output() raises when the model's output cannot be
    coerced into the closed IntentClassificationLLMResponse schema (e.g. the
    model emitted a value outside the QuestionIntent enum, or free text) --
    this must degrade to None exactly like any other failure, never raise."""
    structured_llm = Mock()
    structured_llm.invoke.side_effect = ValueError(
        "1 validation error for IntentClassificationLLMResponse\n"
        "intent\n  Input should be 'governance_security', 'workflow_state', ... "
        "[type=enum, input_value='not_a_real_intent', input_type=str]"
    )
    with patch(
        "core.llm_client.get_chat_llm",
        _mock_get_chat_llm(structured_llm),
    ):
        result = classify_question_intent_llm("Qui peut voir un avoir de 80 000€ ?")

    assert result is None


def test_llm_classifier_returns_none_on_empty_question_without_calling_llm():
    """Guard clause: an empty/whitespace-only question must short-circuit
    before ever building an LLM client -- no wasted call for a question
    with nothing to classify."""
    with patch("core.llm_client.get_chat_llm") as mock_get_chat_llm:
        result = classify_question_intent_llm("   ")

    assert result is None
    mock_get_chat_llm.assert_not_called()


def test_llm_classifier_logs_a_warning_on_failure(caplog):
    structured_llm = Mock()
    structured_llm.invoke.side_effect = RuntimeError("simulated API failure")
    with patch(
        "core.llm_client.get_chat_llm",
        _mock_get_chat_llm(structured_llm),
    ):
        with caplog.at_level("WARNING"):
            classify_question_intent_llm("Qui peut voir un avoir de 80 000€ ?")

    assert any(
        "classify_question_intent_llm" in record.message
        for record in caplog.records
    )


# ── resolve_question_intent() -- orchestration: LLM first, fallback second ──

def test_resolve_uses_llm_result_when_available():
    structured_llm = _mock_structured_llm(QuestionIntent.CALCULATION_LOGIC)
    with patch(
        "core.llm_client.get_chat_llm",
        _mock_get_chat_llm(structured_llm),
    ):
        resolution = resolve_question_intent("Comment le montant total est-il calculé ?")

    assert isinstance(resolution, IntentResolution)
    assert resolution.intent == QuestionIntent.CALCULATION_LOGIC
    assert resolution.source == "llm"
    assert resolution.fallback_reason is None


@pytest.mark.parametrize("failure", [
    RuntimeError("simulated API failure"),
    TimeoutError("simulated network timeout"),
    ValueError("simulated malformed structured output"),
])
def test_resolve_falls_back_to_keyword_classifier_on_any_llm_failure(failure):
    """Whatever the failure mode, resolve_question_intent() must fall back
    to the untouched deterministic classify_question_intent() and report
    source='fallback_keyword' -- never propagate the LLM's exception, never
    silently return a wrong/default intent."""
    question = "Qui a le droit d'approuver un avoir de 25 000€ ?"
    expected_fallback_intent = classify_question_intent(question)

    structured_llm = Mock()
    structured_llm.invoke.side_effect = failure
    with patch(
        "core.llm_client.get_chat_llm",
        _mock_get_chat_llm(structured_llm),
    ):
        resolution = resolve_question_intent(question)

    assert resolution.intent == expected_fallback_intent
    assert resolution.source == "fallback_keyword"
    assert resolution.fallback_reason is not None


def test_resolve_fallback_logs_intent_fallback_warning(caplog):
    question = "Qui a le droit d'approuver un avoir de 25 000€ ?"
    structured_llm = Mock()
    structured_llm.invoke.side_effect = RuntimeError("simulated API failure")
    with patch(
        "core.llm_client.get_chat_llm",
        _mock_get_chat_llm(structured_llm),
    ):
        with caplog.at_level("WARNING"):
            resolve_question_intent(question)

    assert any(
        "INTENT_FALLBACK" in record.message
        for record in caplog.records
    )


def test_resolve_passes_resolved_concept_and_graph_to_fallback_only():
    """resolved_concept/G are only ever consumed by the deterministic
    fallback (classify_question_intent_llm() takes no such arguments) --
    confirms the fallback path still receives them correctly when the LLM
    fails, rather than losing them in the orchestration."""
    import networkx as nx

    G = nx.DiGraph()
    G.add_node(
        "model:hr.leave", node_type="Model", name="hr.leave",
        behavioral_tags=["workflow_rule"],
    )
    resolved_concept = ResolvedConcept(
        user_term="congé",
        resolved_models=["hr.leave"],
        confidence=1.0,
        source_step="static_alias",
        is_resolved=True,
    )
    question = "et pour les congés, comment ça se passe ?"
    expected_fallback_intent = classify_question_intent(question, resolved_concept, G)

    structured_llm = Mock()
    structured_llm.invoke.side_effect = RuntimeError("simulated API failure")
    with patch(
        "core.llm_client.get_chat_llm",
        _mock_get_chat_llm(structured_llm),
    ):
        resolution = resolve_question_intent(question, resolved_concept, G)

    assert resolution.intent == expected_fallback_intent
    assert resolution.source == "fallback_keyword"
