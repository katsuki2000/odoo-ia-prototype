"""
code_intelligence/overrides/prompts.py

System prompts and prompt builders for LLM interpretation of method override findings.
"""

from typing import List
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage


_OVERRIDE_INTERPRETATION_SYSTEM_PROMPT = (
    "Tu es un analyste de code Odoo. Un premier passage automatique (analyse AST) a "
    "repéré un appel `super()` inconditionnel après une branche conditionnelle qui "
    "ne se termine pas directement par un `return`/`raise` à son dernier statement -- "
    "CECI EST UN INDICE BRUT, PAS UN FAIT CONFIRMÉ. Cette heuristique statique ne "
    "vérifie ni si la branche modifie réellement un champ de l'enregistrement, ni si "
    "un `raise`/`return` imbriqué plus loin dans la branche couvre déjà tous les cas -- "
    "elle peut donc se tromper. AVANT de résumer une conséquence, VERIFIE toi-même sur "
    "le code fourni : (1) la branche écrit-elle vraiment un champ de l'enregistrement "
    "(`rec.champ = ...`, `.write(...)`, etc.) sur au moins un chemin qui NE se termine PAS "
    "par un `return`/`raise` ? Si NON (ex: la branche ne fait que lever une exception ou ne "
    "rien faire), il n'y a RIEN que le `super()` puisse écraser -- dis-le explicitement, "
    "n'invente aucune conséquence négative, et mets confidence à 'low'. (2) Si la "
    "prémisse tient réellement, résume en une phrase la conséquence métier concrète "
    "(quel comportement l'utilisateur observera réellement). Ta réponse doit toujours "
    "être cohérente avec tout message d'erreur (UserError/ValidationError) visible dans "
    "le même extrait de code -- si un `raise` bloque explicitement un cas, ne dis JAMAIS "
    "que ce cas est approuvé ou que la restriction est annulée. Réponds STRICTEMENT en "
    "JSON, sans aucun texte avant ou après, au format exact: "
    '{"summary": "...", "confidence": "high"|"medium"|"low"}. '
    "N'utilise JAMAIS une autre valeur de confidence que high, medium, ou low."
)


def build_override_interpretation_prompt(
    model_name: str,
    method_name: str,
    warnings: List[str],
    snippets: List[str],
) -> str:
    """Build the bounded user prompt for method override chain interpretation."""
    detected = "\n".join(f"- {w}" for w in warnings)
    code_block = "\n\n".join(snippets)
    return (
        f"Méthode '{model_name}.{method_name}', chaîne de surcharge "
        f"(ordre d'exécution réel):\n```python\n{code_block}\n```\n\n"
        f"Indice brut de l'analyse statique (AST) -- à vérifier, pas à prendre pour "
        f"acquis:\n{detected}\n\n"
        "Vérifie d'abord si cet indice tient reellement (la branche mute-t-elle un champ "
        "de l'enregistrement sans que ce chemin ne se termine par return/raise ?), puis "
        "résume en une phrase claire le comportement métier réellement observé (pas le "
        "code), et indique ta confiance."
    )


def build_override_interpretation_messages(
    model_name: str,
    method_name: str,
    warnings: List[str],
    snippets: List[str],
) -> List[BaseMessage]:
    """Construct the full message list for method override LLM interpretation."""
    return [
        SystemMessage(content=_OVERRIDE_INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=build_override_interpretation_prompt(model_name, method_name, warnings, snippets)),
    ]


__all__ = [
    "_OVERRIDE_INTERPRETATION_SYSTEM_PROMPT",
    "build_override_interpretation_prompt",
    "build_override_interpretation_messages",
]
