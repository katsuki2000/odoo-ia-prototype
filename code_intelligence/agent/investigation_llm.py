"""
code_intelligence/investigation/prompts.py

System prompts and template construction for bounded LLM intent classification.
"""

from typing import List
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage


_INTENT_CLASSIFICATION_SYSTEM_PROMPT = (
    "Tu es un classifieur d'intention pour MIRO, un assistant Odoo destiné aux utilisateurs métiers. "
    "Classe la question selon le besoin métier exprimé, pas selon un mot technique isolé. "
    "Le périmètre prioritaire couvre : qui approuve ou a accès ; comment effectuer une action dans Odoo ; "
    "pourquoi une opération est bloquée ou un état ou montant change ; et l’état courant des ventes, stocks, "
    "commandes et factures. Une question « pourquoi » portant sur un blocage métier reste une question métier "
    "et doit être classée selon son mécanisme probable. Réserve les catégories techniques aux demandes "
    "qui sollicitent explicitement l’analyse du code, des classes, des méthodes ou de l’architecture. "
    "Classe la question dans EXACTEMENT une des catégories suivantes :\n"
    "- governance_security : acces, permissions, droits, regles de visibilite, verrous, approbation\n"
    "- workflow_state : etapes, statuts, transitions, boutons de validation\n"
    "- calculation_logic : champs calculés, formules, montants, dépendances de calcul\n"
    "- inheritance_structure : héritage de modèles, surcharges Python, chaîne MRO\n"
    "- automation_action : actions automatiques, crons, déclencheurs\n"
    "- erp_data_query : donnees ERP en direct (listes, comptages, agrégations, chiffres)\n"
    "- documentary_policy : politique générale, document ou procédure écrite à citer, question générale ou de courtoisie\n"
    "- navigation_howto : comment réaliser une action dans l'interface Odoo (créer, saisir, confirmer, valider...), ou où se trouve un écran, un menu, un onglet\n"
    "- general_code_inquiry : autre inspection technique du code, ne correspondant a aucune categorie ci-dessus\n"
    "Reponds uniquement avec la catégorie choisie, jamais une catégorie hors de cette liste."
)


def build_intent_classification_prompt(question: str) -> str:
    """Format user question for structured intent classification."""
    return f'Question utilisateur : "{question}"'


def build_intent_classification_messages(question: str) -> List[BaseMessage]:
    """Build the message list for structured intent classification."""
    return [
        SystemMessage(content=_INTENT_CLASSIFICATION_SYSTEM_PROMPT),
        HumanMessage(content=build_intent_classification_prompt(question)),
    ]


__all__ = [
    "_INTENT_CLASSIFICATION_SYSTEM_PROMPT",
    "build_intent_classification_prompt",
    "build_intent_classification_messages",
]

# ── LLM Classifier ──────────────────────────────────────────────────────

"""
code_intelligence/investigation_plan_llm.py

Bounded LLM intent classification and orchestration with fallback.
Bloc P1 (todo/contexte.txt section 394+).
"""

from dataclasses import dataclass
from typing import Any, Optional
import logging
import re

from pydantic import BaseModel, ConfigDict, Field

from code_intelligence.agent.resolver import ResolvedConcept
from code_intelligence.agent.investigation_classifier import (
    _ERP_DATA_PATTERNS,
    _fold_accents,
    classify_question_intent,
    has_documentary_anchor,
)
from code_intelligence.agent.investigation_schemas import QuestionIntent

logger = logging.getLogger(__name__)


class IntentClassificationLLMResponse(BaseModel):
    """Bounded structured output for classify_question_intent_llm() -- a
    single QuestionIntent value, never free text.
    """
    model_config = ConfigDict(strict=False)

    intent: QuestionIntent = Field(
        ...,
        description="Classified semantic intent of the user question, exactly one of the closed QuestionIntent vocabulary",
    )




def classify_question_intent_llm(question: str) -> Optional[QuestionIntent]:
    """
    Bounded LLM intent classification (Bloc P1, todo/contexte.txt section 394+).

    Single-shot, structured-output LLM call constrained to the closed
    QuestionIntent vocabulary -- same with_structured_output pattern as
    document_rag/generate_node.py::generate(). Never raises: any failure
    (timeout, rate limit, malformed structured output, or any other
    exception) is caught and reported as None. Callers MUST fall back to
    the deterministic classify_question_intent() on None.

    max_retries=1 (single attempt, no rate-limit key rotation/wait loop) is
    a deliberate departure from business_resolver._llm_arbitrate's default:
    this classifier always has classify_question_intent() ready to take
    over immediately.
    """
    if not question or not question.strip():
        return None

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        from core.llm.llm_client import get_chat_llm, invoke_with_rate_limit

        def _make_structured_llm():
            base_llm = get_chat_llm(temperature=0.0, max_retries=0)
            return base_llm.with_structured_output(IntentClassificationLLMResponse, method="json_schema")

        structured_llm = _make_structured_llm()
        messages = build_intent_classification_messages(question)
        result, _wait = invoke_with_rate_limit(
            structured_llm, messages, max_retries=1, rebuild_llm=_make_structured_llm
        )
        intent = getattr(result, "intent", None)
        if isinstance(intent, QuestionIntent):
            return intent
        return None
    except Exception:
        logger.warning("classify_question_intent_llm failed for question=%r", question, exc_info=True)
        return None


@dataclass
class IntentResolution:
    """Result of resolve_question_intent(): which QuestionIntent was chosen
    and by which mechanism, so callers/logs can distinguish an LLM-classified
    turn from a fallback-classified one.
    """
    intent: QuestionIntent
    source: str  # "llm" | "fallback_keyword"
    fallback_reason: Optional[str] = None


def resolve_question_intent(
    question: str,
    resolved_concept: Optional[ResolvedConcept] = None,
    G: Optional[Any] = None,
) -> IntentResolution:
    """
    Orchestrates intent resolution for a single question.

    Deterministic doc-anchor override (DOC-08): when the question carries an
    explicit documentary anchor (wiki/procedure/documentation...) AND is not
    simultaneously an ERP aggregation query, short-circuit to DOCUMENTARY_POLICY
    before the LLM even runs.

    Otherwise: attempts the bounded LLM classifier first, falls back to the
    deterministic classify_question_intent() on any LLM failure.
    """
    folded = _fold_accents(question)
    if has_documentary_anchor(folded) and not any(re.search(p, folded) for p in _ERP_DATA_PATTERNS):
        return IntentResolution(intent=QuestionIntent.DOCUMENTARY_POLICY, source="deterministic_semantic")

    import sys
    ip_mod = sys.modules.get("code_intelligence.agent.investigation_planner")
    llm_classifier = getattr(ip_mod, "classify_question_intent_llm", classify_question_intent_llm) if ip_mod else classify_question_intent_llm
    kw_classifier = getattr(ip_mod, "classify_question_intent", classify_question_intent) if ip_mod else classify_question_intent

    llm_intent = llm_classifier(question)
    if llm_intent is not None:
        return IntentResolution(intent=llm_intent, source="llm")

    fallback_intent = kw_classifier(question, resolved_concept, G)
    reason = "LLM classification unavailable or failed -- see prior warning log"
    logger.warning(
        "INTENT_FALLBACK reason=%s question=%r resolved_intent=%s",
        reason, question, fallback_intent.value,
    )
    return IntentResolution(intent=fallback_intent, source="fallback_keyword", fallback_reason=reason)
