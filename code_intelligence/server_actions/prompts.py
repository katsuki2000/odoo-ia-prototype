"""
code_intelligence/server_actions/prompts.py

System prompts and prompt builders for LLM interpretation of server action security findings.
"""

from typing import TYPE_CHECKING, List
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage

if TYPE_CHECKING:
    from code_intelligence.server_actions.analyzer import ServerActionCodeAnalysis

_SERVER_ACTION_INTERPRETATION_SYSTEM_PROMPT = (
    "Tu es un analyste de sécurité pour du code Odoo ir.actions.server (server actions). "
    "Un premier passage automatique (regex) a déjà détecté des patterns de sécurité dans ce "
    "code -- ta tâche est UNIQUEMENT d'interpréter et résumer en une phrase ce que fait "
    "concrètement ce code du point de vue métier/sécurité, et d'indiquer ta confiance dans "
    "cette interprétation. Réponds STRICTEMENT en JSON, sans aucun texte avant ou après, "
    'au format exact: {"summary": "...", "confidence": "high"|"medium"|"low"}. '
    "N'utilise JAMAIS une autre valeur de confidence que high, medium, ou low."
)


def _build_interpretation_prompt(analysis: "ServerActionCodeAnalysis", code: str) -> str:
    """Build the bounded user prompt for server action security interpretation."""
    detected = "\n".join(f"- {w}" for w in analysis.security_warnings)
    return (
        f"Code de l'action serveur '{analysis.action_xml_id}':\n"
        f"```python\n{code}\n```\n\n"
        f"Patterns déjà détectés par analyse statique (regex):\n{detected}\n\n"
        "Résume en une phrase claire ce que fait ce code du point de vue métier/sécurité, "
        "et indique ta confiance dans cette interprétation."
    )


def build_server_action_messages(analysis: "ServerActionCodeAnalysis", code: str) -> List[BaseMessage]:
    """Construct the full message list for server action LLM interpretation."""
    return [
        SystemMessage(content=_SERVER_ACTION_INTERPRETATION_SYSTEM_PROMPT),
        HumanMessage(content=_build_interpretation_prompt(analysis, code)),
    ]


__all__ = [
    "_SERVER_ACTION_INTERPRETATION_SYSTEM_PROMPT",
    "_build_interpretation_prompt",
    "build_server_action_messages",
]
