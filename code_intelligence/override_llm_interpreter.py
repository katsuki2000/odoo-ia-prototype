"""LLM-based interpretation layer for method override static analysis findings."""

import json
import logging
from typing import List, Optional

_logger = logging.getLogger(__name__)

_LLM_CONFIDENCE_CLOSED_SET = {"high", "medium", "low"}

_INTERPRETATION_SYSTEM_PROMPT = (
    "Tu es un analyste de code Odoo. Un premier passage automatique (analyse AST) a "
    "rep\u00e9r\u00e9 un appel `super()` inconditionnel apr\u00e8s une branche conditionnelle qui "
    "ne se termine pas directement par un `return`/`raise` \u00e0 son dernier statement -- "
    "CECI EST UN INDICE BRUT, PAS UN FAIT CONFIRM\u00c9. Cette heuristique statique ne "
    "v\u00e9rifie ni si la branche modifie r\u00e9ellement un champ de l'enregistrement, ni si "
    "un `raise`/`return` imbriqu\u00e9 plus loin dans la branche couvre d\u00e9j\u00e0 tous les cas -- "
    "elle peut donc se tromper. AVANT de r\u00e9sumer une cons\u00e9quence, VERIFIE toi-m\u00eame sur "
    "le code fourni : (1) la branche \u00e9crit-elle vraiment un champ de l'enregistrement "
    "(`rec.champ = ...`, `.write(...)`, etc.) sur au moins un chemin qui NE se termine PAS "
    "par un `return`/`raise` ? Si NON (ex: la branche ne fait que lever une exception ou ne "
    "rien faire), il n'y a RIEN que le `super()` puisse \u00e9craser -- dis-le explicitement, "
    "n'invente aucune cons\u00e9quence n\u00e9gative, et mets confidence \u00e0 'low'. (2) Si la "
    "pr\u00e9misse tient r\u00e9ellement, r\u00e9sume en une phrase la cons\u00e9quence m\u00e9tier concr\u00e8te "
    "(quel comportement l'utilisateur observera r\u00e9ellement). Ta r\u00e9ponse doit toujours "
    "\u00eatre coh\u00e9rente avec tout message d'erreur (UserError/ValidationError) visible dans "
    "le m\u00eame extrait de code -- si un `raise` bloque explicitement un cas, ne dis JAMAIS "
    "que ce cas est approuv\u00e9 ou que la restriction est annul\u00e9e. R\u00e9ponds STRICTEMENT en "
    "JSON, sans aucun texte avant ou apr\u00e8s, au format exact: "
    '{"summary": "...", "confidence": "high"|"medium"|"low"}. '
    "N'utilise JAMAIS une autre valeur de confidence que high, medium, ou low."
)


def interpret_override_chain_with_llm(
    model_name: str,
    method_name: str,
    warnings: List[str],
    snippets: List[str],
    llm,
) -> Optional[dict]:
    if not warnings or llm is None:
        return None

    detected = "\n".join(f"- {w}" for w in warnings)
    code_block = "\n\n".join(snippets)
    prompt = (
        f"M\u00e9thode '{model_name}.{method_name}', cha\u00eene de surcharge "
        f"(ordre d'ex\u00e9cution r\u00e9el):\n```python\n{code_block}\n```\n\n"
        f"Indice brut de l'analyse statique (AST) -- \u00e0 v\u00e9rifier, pas \u00e0 prendre pour "
        f"acquis:\n{detected}\n\n"
        "V\u00e9rifie d'abord si cet indice tient reellement (la branche mute-t-elle un champ "
        "de l'enregistrement sans que ce chemin ne se termine par return/raise ?), puis "
        "r\u00e9sume en une phrase claire le comportement m\u00e9tier r\u00e9ellement observ\u00e9 (pas le "
        "code), et indique ta confiance."
    )

    try:
        from langchain_core.messages import SystemMessage, HumanMessage

        response = llm.invoke([
            SystemMessage(content=_INTERPRETATION_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        raw = (response.content or "").strip()
    except Exception as e:
        _logger.warning(
            "LLM interpretation call failed for %s.%s: %s", model_name, method_name, e
        )
        return None

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        _logger.warning(
            "LLM interpretation returned non-JSON response for %s.%s: %r",
            model_name, method_name, raw,
        )
        return None

    if not isinstance(parsed, dict):
        return None

    summary = parsed.get("summary")
    confidence = parsed.get("confidence")

    if confidence not in _LLM_CONFIDENCE_CLOSED_SET:
        _logger.warning(
            "LLM interpretation returned out-of-set confidence for %s.%s: %r",
            model_name, method_name, confidence,
        )
        return None

    if not summary or not isinstance(summary, str):
        return None

    return {"summary": summary, "confidence": confidence}
