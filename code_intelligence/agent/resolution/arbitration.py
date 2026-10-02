"""Bounded LLM arbitration over a closed list of candidate Odoo models."""

import logging
from typing import Dict, List, Optional

_logger = logging.getLogger(__name__)

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
) -> Optional[str]:
    """Bounded LLM candidate selection over a closed list."""
    if llm is None:
        _logger.warning("LLM arbitration requested but no llm client was provided; skipping.")
        return None

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
        return None

    if raw == "NONE":
        return None
    if raw in candidates:
        return raw

    _logger.warning("LLM arbitration returned an out-of-list value: %r (candidates=%r)", raw, candidates)
    return None


__all__ = [
    "_ARBITRATION_SYSTEM_PROMPT",
    "_build_arbitration_prompt",
    "_llm_arbitrate",
]
