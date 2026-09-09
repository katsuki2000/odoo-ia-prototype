"""
erp_data/prompts.py

System prompts and template construction for the ERP data querying agent (ORM ReAct).
"""

from typing import List, Optional
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage


ORM_AGENT_SYSTEM_PROMPT = (
    "Tu es un assistant IA interne spécialisé dans les données ERP Odoo. "
    "Utilise les outils disponibles pour interroger la base de données en temps réel et réponds avec les informations exactes retournées. "
    "Indique toujours la source exacte des données à la fin de ta réponse (ex: [Source: Odoo ERP - Module ...]). "
    "Rédige ta réponse exclusivement en Markdown (**gras**, listes \"- item\", etc.) -- n'utilise JAMAIS de balise HTML brute (<strong>, <br>, <div>...), le moteur d'affichage ne les rend pas et les afficherait telles quelles. "
    "Exemple de format attendu : **Chiffre d'affaires total** : 12 450€ [Source: Odoo ERP - Module Ventes]. Aucune balise HTML dans cet exemple."
)


def build_orm_synthesis_prompt(question: str, tool_observations: List[str]) -> str:
    """Build the final synthesis prompt when the ReAct iteration budget is exhausted."""
    return (
        f"Question originale : {question}\n\n"
        f"Observations collectées :\n" + "\n".join(tool_observations) +
        "\n\nFournis une réponse finale et concise en français basée uniquement sur ces observations."
    )


def build_orm_agent_messages(
    question: str,
    chat_history: Optional[List[BaseMessage]] = None,
    system_prompt: str = ORM_AGENT_SYSTEM_PROMPT,
) -> List[BaseMessage]:
    """Construct initial message sequence for the ORM ReAct agent loop."""
    history = (chat_history or [])[-10:]
    return [
        SystemMessage(content=system_prompt),
        *history,
        HumanMessage(content=question),
    ]


def build_hybrid_combine_prompt(question: str, doc_answer: str, data_answer: str) -> str:
    """Build the final hybrid synthesis prompt combining documentary RAG and ERP ORM findings."""
    return (
        f"Tu es l'agent de synthèse finale.\n"
        f"La question de l'utilisateur était : '{question}'\n\n"
        f"Voici ce que l'agent de documentation a trouvé sur les procédures :\n{doc_answer}\n\n"
        f"Voici ce que l'agent des données ERP a trouvé dans les chiffres :\n{data_answer}\n\n"
        f"Combine ces deux informations pour faire une seule réponse cohérente et fluide, sans mentionner l'existence des agents.\n"
        f"Rédige exclusivement en Markdown (**gras**, listes \"- item\", etc.) -- aucune balise HTML brute (<strong>, <br>, <div>...), le moteur d'affichage ne les rend pas.\n"
        f"Exemple de format attendu :\n### Procédure et données\n\n1. **Étape** : description courte\n- Donnée associée : valeur\n\nAucune balise HTML dans cet exemple."
    )


__all__ = [
    "ORM_AGENT_SYSTEM_PROMPT",
    "build_orm_synthesis_prompt",
    "build_orm_agent_messages",
    "build_hybrid_combine_prompt",
]
