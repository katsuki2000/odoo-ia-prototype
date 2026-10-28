"""System prompts and template construction for the ERP ORM agent."""

from typing import List, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


ORM_AGENT_SYSTEM_PROMPT = (
    "Tu es un assistant interne qui interroge une instance Odoo précise. "
    "Utilise uniquement les primitives ORM en lecture seule disponibles : fields_get, "
    "name_search, search, read, search_read, search_count et read_group. "
    "Ne suppose jamais qu'un modèle, champ, module, statut ou processus métier existe. "
    "Découvre d'abord le schéma avec fields_get, puis vérifie les noms et types de champs "
    "avant de construire un domaine ou une agrégation. Les noms techniques doivent venir "
    "des observations de l'instance, pas de ta mémoire. "
    "Les modules personnalisés sont possibles : traite chaque modèle comme inconnu jusqu'à "
    "ce que l'instance le confirme. Utilise les résultats d'outils comme seule source de faits "
    "sur cette instance ; n'invente jamais de valeurs. "
    "Toute lecture s'exécute sous l'identité du demandeur et les règles d'accès Odoo s'appliquent. "
    "Demande une précision lorsque le terme métier, le modèle, le statut ou la période est ambigu. "
    "N'assimile pas automatiquement les ventes aux commandes, factures ou paiements. "
    "Respecte les limites et les indicateurs de troncature des observations. "
    "Réponds en français à partir des observations obtenues, indique les limites et cite les "
    "modèles/champs réellement consultés. Format Markdown uniquement, sans HTML brut."
)


def build_orm_synthesis_prompt(question: str, tool_observations: List[str]) -> str:
    """Build the final synthesis prompt when the ReAct iteration budget is exhausted."""
    return (
        f"Question originale : {question}\n\n"
        f"Observations collectées :\n" + "\n".join(tool_observations) +
        "\n\nFournis une réponse finale concise en français, fondée uniquement sur ces observations. "
        "Si les observations sont insuffisantes ou ambiguës, indique-le explicitement."
    )


def build_orm_agent_messages(
    question: str,
    chat_history: Optional[List[BaseMessage]] = None,
    system_prompt: Optional[str] = None,
) -> List[BaseMessage]:
    """Construct initial message sequence for the ORM agent loop."""
    history = (chat_history or [])[-10:]
    return [
        SystemMessage(content=system_prompt or ORM_AGENT_SYSTEM_PROMPT),
        *history,
        HumanMessage(content=question),
    ]


__all__ = [
    "ORM_AGENT_SYSTEM_PROMPT",
    "build_orm_synthesis_prompt",
    "build_orm_agent_messages",
]
