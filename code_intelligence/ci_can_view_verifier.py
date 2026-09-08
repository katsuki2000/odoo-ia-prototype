"""
code_intelligence/ci_can_view_verifier.py

Verification, conflict detection, and contradiction resolution for can_view_amount facts.
"""

import logging
import re
from typing import Optional, List, Tuple, Dict

logger = logging.getLogger(__name__)

_CAN_VIEW_ALLOW_ASSERTION_RE = re.compile(
    r"[^.\n]*\b(?:peut\s+(?:voir|consulter|acc[ée]der)|"
    r"(?:a|dispose\s+du?)\s+(?:le\s+)?permission\s+de\s+(?:voir|consulter)|"
    r"est\s+autoris[ée]\s+[àa]\s+(?:voir|consulter|acc[ée]der))[^.\n]*\.?",
    re.IGNORECASE,
)
_CAN_VIEW_DENY_ASSERTION_RE = re.compile(
    r"[^.\n]*\bne\s+peut\s+pas\s+(?:voir|consulter|acc[ée]der)[^.\n]*\.?"
    r"|[^.\n]*n[’']a\s+pas\s+(?:le\s+)?permission\s+de\s+(?:voir|consulter)[^.\n]*\.?"
    r"|[^.\n]*n[’']est\s+pas\s+autoris[ée]\s+[àa]\s+(?:voir|consulter|acc[ée]der)[^.\n]*\.?",
    re.IGNORECASE,
)
_CAN_VIEW_FACT_VERDICT_RE = re.compile(
    r"can_view_amount\(\)\s*=\s*(True|False)\s*:\s*l.utilisateur\s+(PEUT|NE PEUT PAS)",
)
_CAN_VIEW_FACT_INDETERMINATE_MARKER = "can_view_amount_v2() = indeterminate"


def _split_before_first_fact_marker(text: str) -> str:
    """Text portion before the first '[FAIT' marker -- the free-prose synthesis."""
    idx = text.find("[FAIT")
    return text if idx == -1 else text[:idx]


def _extract_can_view_amount_verdict(final_answer: str) -> Optional[bool]:
    """True/False when the injected can_view_amount_v2 fact states a definite verdict."""
    match = _CAN_VIEW_FACT_VERDICT_RE.search(final_answer)
    if not match:
        return None
    return match.group(2) == "PEUT"


def _has_can_view_amount_fact(final_answer: str) -> bool:
    return bool(_CAN_VIEW_FACT_VERDICT_RE.search(final_answer)) or (
        _CAN_VIEW_FACT_INDETERMINATE_MARKER in final_answer
    )


def _correct_can_view_amount_contradictions(final_answer: str) -> str:
    """Detect and correct a synthesis-level inversion of the can_view_amount_v2 verdict."""
    if not _has_can_view_amount_fact(final_answer):
        return final_answer

    prose = _split_before_first_fact_marker(final_answer)
    is_indeterminate = _CAN_VIEW_FACT_INDETERMINATE_MARKER in final_answer
    verdict = _extract_can_view_amount_verdict(final_answer)

    if is_indeterminate:
        match = _CAN_VIEW_ALLOW_ASSERTION_RE.search(prose) or _CAN_VIEW_DENY_ASSERTION_RE.search(prose)
        if not match:
            return final_answer
        replacement = (
            "Le moteur de règles ne peut pas déterminer avec certitude si "
            "l'utilisateur peut voir cet enregistrement pour ce montant "
            "(voir le fait déterministe ci-dessous)."
        )
        logger.warning(
            "Node [code_intelligence_agent]: synthesis asserted a definite "
            "allow/deny while the can_view_amount_v2 verdict was indéterminé "
            "-- replacing sentence with explicit uncertainty statement."
        )
    elif verdict is True:
        match = _CAN_VIEW_DENY_ASSERTION_RE.search(prose)
        if not match:
            return final_answer
        replacement = (
            "L'utilisateur PEUT voir cet enregistrement pour ce montant "
            "(voir le fait déterministe ci-dessous)."
        )
        logger.warning(
            "Node [code_intelligence_agent]: synthesis asserted user CANNOT "
            "view record while can_view_amount_v2() computed True -- replacing."
        )
    elif verdict is False:
        match = _CAN_VIEW_ALLOW_ASSERTION_RE.search(prose)
        if not match:
            return final_answer
        replacement = (
            "L'utilisateur NE PEUT PAS voir cet enregistrement pour ce "
            "montant (voir le fait déterministe ci-dessous)."
        )
        logger.warning(
            "Node [code_intelligence_agent]: synthesis asserted user CAN "
            "view record while can_view_amount_v2() computed False -- replacing."
        )
    else:
        return final_answer

    start, end = match.span()
    return final_answer[:start] + replacement + final_answer[end:]


def _can_view_amount_candidates(
    raw_tool_output: str,
    tool_observation_models: Optional[List[str]],
    target_models: Optional[List[str]],
) -> List[Tuple[str, str]]:
    """Shared candidate-collection step for can_view_amount_v2 fact blocks."""
    if tool_observation_models is None or not target_models:
        return []
    blocks = raw_tool_output.split("\n\n")
    target_set = set(target_models)
    return [
        (block, model)
        for block, model in zip(blocks, tool_observation_models)
        if _has_can_view_amount_fact(block) and model in target_set
    ]


def _extract_can_view_amount_verdict_label(block: str) -> str:
    """Human-readable verdict label for a single can_view_amount_v2 fact block."""
    if _CAN_VIEW_FACT_INDETERMINATE_MARKER in block:
        return "indéterminé"
    match = _CAN_VIEW_FACT_VERDICT_RE.search(block)
    return match.group(2) if match else "inconnu"


def _detect_can_view_amount_model_conflict(
    raw_tool_output: str,
    tool_observation_models: Optional[List[str]] = None,
    target_models: Optional[List[str]] = None,
) -> Optional[str]:
    """Detect when 2+ resolved models produce differing can_view_amount_v2 verdicts."""
    candidates = _can_view_amount_candidates(raw_tool_output, tool_observation_models, target_models)
    if not candidates:
        return None

    verdict_by_model: Dict[str, str] = {}
    for block, model in candidates:
        verdict_by_model[model] = _extract_can_view_amount_verdict_label(block)

    distinct_verdicts = set(verdict_by_model.values())
    if len(verdict_by_model) < 2 or len(distinct_verdicts) < 2:
        return None

    detail = ", ".join(f"{model}: {verdict}" for model, verdict in sorted(verdict_by_model.items()))
    logger.warning(
        "Node [code_intelligence_agent]: %d resolved models produced DIVERGENT "
        "can_view_amount_v2 verdicts this turn (%s) -- flagging as CONFLICTING evidence.",
        len(verdict_by_model), detail,
    )
    return (
        f"{len(verdict_by_model)} modèles résolus ont produit des verdicts "
        f"can_view_amount_v2 divergents pour cette question ({detail}) -- preuves "
        f"concurrentes, aucun vainqueur choisi automatiquement."
    )


def _format_conflicting_evidence_answer(
    raw_tool_output: str,
    tool_observation_models: Optional[List[str]] = None,
    target_models: Optional[List[str]] = None,
) -> Optional[str]:
    """Deterministic final_answer exposition of conflicting evidence with NO LLM synthesis."""
    candidates = _can_view_amount_candidates(raw_tool_output, tool_observation_models, target_models)
    if not candidates:
        return None

    block_by_model: Dict[str, str] = {}
    for block, model in candidates:
        block_by_model[model] = block.strip()

    if len(block_by_model) < 2:
        return None

    evidence_sections = "\n\n".join(
        f"**Modèle `{model}`** :\n{block}"
        for model, block in sorted(block_by_model.items())
    )

    return (
        "## Preuves contradictoires détectées\n\n"
        f"{len(block_by_model)} modèles résolus produisent chacun leur propre "
        "verdict déterministe pour cette question, et ces verdicts ne sont pas "
        "d'accord entre eux. Les deux constats sont présentés ci-dessous "
        "intégralement, sans qu'aucun des deux ne soit écarté ou privilégié "
        "automatiquement :\n\n"
        f"{evidence_sections}\n\n"
        "Le moteur ne peut pas trancher entre ces preuves concurrentes à "
        "partir des éléments disponibles pour cette question. Une "
        "vérification manuelle est nécessaire pour déterminer laquelle "
        "s'applique réellement à ce cas."
    )


def _extract_can_view_amount_fact_block(
    raw_tool_output: str,
    tool_observation_models: Optional[List[str]] = None,
    target_models: Optional[List[str]] = None,
) -> Optional[str]:
    """Return the exact can_view_amount_v2 fact block if present in raw_tool_output."""
    blocks = raw_tool_output.split("\n\n")
    candidates = _can_view_amount_candidates(raw_tool_output, tool_observation_models, target_models)
    if candidates:
        distinct_models = {model for _block, model in candidates}
        if len(distinct_models) > 1:
            logger.warning(
                "Node [code_intelligence_agent]: %d distinct resolved "
                "models each produced a can_view_amount_v2 fact block (%s) -- "
                "backfilling with most recently computed one.",
                len(distinct_models), sorted(distinct_models),
            )
            return candidates[-1][0].strip()
        return candidates[0][0].strip()

    matches = [block for block in blocks if _has_can_view_amount_fact(block)]
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning(
            "Node [code_intelligence_agent]: %d can_view_amount_v2 fact "
            "blocks found with no model association -- taking first one.",
            len(matches),
        )
    return matches[0].strip()


def _backfill_missing_can_view_amount_fact(
    final_answer: str,
    raw_tool_output: str,
    tool_observation_models: Optional[List[str]] = None,
    target_models: Optional[List[str]] = None,
) -> str:
    """Append verbatim can_view_amount_v2 fact block if missing from synthesized answer."""
    if _has_can_view_amount_fact(final_answer):
        return final_answer

    block = _extract_can_view_amount_fact_block(
        raw_tool_output,
        tool_observation_models=tool_observation_models,
        target_models=target_models,
    )
    if block is None:
        return final_answer

    logger.info("Node [code_intelligence_agent]: backfilling can_view_amount_v2 fact.")
    return final_answer + "\n\n" + block


def _format_can_view_amount_fact(
    amount: float, can_view: Optional[bool], unresolved: Optional[List[str]] = None
) -> str:
    """Format deterministic can_view_amount verdict into a declarative fact block."""
    if can_view is None:
        fields_str = ", ".join(unresolved) if unresolved else "une ou plusieurs conditions non résolues"
        return (
            f"[FAIT DÉTERMINISTIQUE] Pour un montant de {amount:.0f}€, "
            f"le moteur de règles NE PEUT PAS déterminer si l'utilisateur peut voir "
            f"cet enregistrement (can_view_amount_v2() = indeterminate) : au moins une "
            f"règle applicable dépend de {fields_str}, qui ne sont pas connus dans ce "
            f"contexte. Ne pas affirmer que l'accès est autorisé ou refusé -- signaler "
            f"explicitement cette incertitude à l'utilisateur."
        )
    return (
        f"[FAIT DÉTERMINISTIQUE] Pour un montant de {amount:.0f}€, "
        f"le moteur de règles calcule can_view_amount() = {can_view} : "
        f"l'utilisateur {'PEUT' if can_view else 'NE PEUT PAS'} voir "
        f"cet enregistrement."
    )
