"""Bounded LLM arbitration over a closed list of candidate Odoo models."""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

_logger = logging.getLogger(__name__)

ARBITRATION_SELECTED = "selected"
ARBITRATION_NONE = "none"
ARBITRATION_OUT_OF_LIST = "out_of_list"
ARBITRATION_CALL_FAILED = "call_failed"
ARBITRATION_NO_LLM = "no_llm"


@dataclass(frozen=True)
class ArbitrationTrace:
    choice: Optional[str]
    status: str
    raw: Optional[str] = None

_ARBITRATION_SYSTEM_PROMPT = (
    "Tu es un composant de résolution de symboles techniques Odoo. "
    "Tu dois choisir, parmi une liste fermée de modèles techniques candidats, "
    "celui qui correspond le mieux à la question métier posée ou indiquer "
    "qu'aucun ne convient. Tu ne dois JAMAIS proposer un nom de modèle en "
    "dehors de la liste fournie, même s'il te semble plus pertinent."
)

def _build_arbitration_prompt(
    query_text: str,
    candidates: List[str],
    candidate_contexts: Optional[Dict[str, str]] = None,
) -> str:
    """Build bounded arbitration prompt for selecting a candidate model."""
    candidates_block = "\n".join(
        f"- {candidate}" + (
            f" — {candidate_contexts[candidate]}"
            if candidate_contexts and candidate_contexts.get(candidate) else ""
        )
        for candidate in candidates
    )
    return (
        f'Question métier utilisateur : "{query_text}"\n\n'
        f"Modèles techniques Odoo candidats (extraits par correspondance approximative, "
        f"scores proches, ambigus) :\n{candidates_block}\n\n"
        "Réponds UNIQUEMENT avec le nom technique exact d'UN SEUL de ces modèles "
        "s'il correspond clairement à la question, ou UNIQUEMENT le mot NONE si "
        "aucun ne correspond clairement. Pas d'explication, pas de ponctuation, "
        "pas de modèle hors de cette liste."
    )


def _llm_arbitrate(
    query_text: str,
    candidates: List[str],
    llm,
    candidate_contexts: Optional[Dict[str, str]] = None,
) -> ArbitrationTrace:
    """Bounded LLM candidate selection over a closed list, with the raw answer kept."""
    if llm is None:
        _logger.warning("LLM arbitration requested but no llm client was provided; skipping.")
        return ArbitrationTrace(None, ARBITRATION_NO_LLM)

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        from core.llm.llm_client import get_chat_llm, invoke_with_rate_limit

        prompt = _build_arbitration_prompt(query_text, candidates, candidate_contexts)
        messages = [
            SystemMessage(content=_ARBITRATION_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        def _rebuild_arbitration_llm():
            return get_chat_llm(temperature=0.0, max_retries=0)

        response, _wait = invoke_with_rate_limit(
            llm, messages, rebuild_llm=_rebuild_arbitration_llm,
        )
        raw = (response.content or "").strip()
    except Exception:
        _logger.exception("LLM arbitration call failed for query=%r candidates=%r", query_text, candidates)
        return ArbitrationTrace(None, ARBITRATION_CALL_FAILED)

    if raw == "NONE":
        return ArbitrationTrace(None, ARBITRATION_NONE, raw)
    if raw in candidates:
        return ArbitrationTrace(raw, ARBITRATION_SELECTED, raw)

    _logger.warning("LLM arbitration returned an out-of-list value: %r (candidates=%r)", raw, candidates)
    return ArbitrationTrace(None, ARBITRATION_OUT_OF_LIST, raw)


__all__ = [
    "ARBITRATION_CALL_FAILED",
    "ARBITRATION_NONE",
    "ARBITRATION_NO_LLM",
    "ARBITRATION_OUT_OF_LIST",
    "ARBITRATION_SELECTED",
    "ArbitrationTrace",
    "_ARBITRATION_SYSTEM_PROMPT",
    "_build_arbitration_prompt",
    "_llm_arbitrate",
]
