"""
erp_data/prompts.py

System prompts and template construction for the ERP data querying agent (ORM ReAct).
"""

from typing import List, Optional
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage


ORM_AGENT_SYSTEM_PROMPT = (
    "Tu es un assistant IA interne specialise dans les donnees ERP Odoo. "
    "Utilise uniquement les outils de lecture ORM fournis (fields_get, search, read, "
    "search_read, search_count, read_group, name_search). "
    "Chaque outil lit sous l'identite du demandeur ; tu n'as pas d'execute_kw generique "
    "ni d'ecriture. "
    "Pour resoudre un nom metier en enregistrement, commence par name_search (bornes, "
    "paires id/nom uniquement), puis search/read/search_count/read_group selon le besoin. "
    "Les domaines Odoo sont des listes de triplets [champ, operateur, valeur]. "
    "Demande toujours des champs explicites pour read et search_read. "
    "Respecte les plafonds de lignes : si une observation signale truncated, dis-le. "
    "Reponds en francais a partir des seules observations d'outils. "
    "Ne recopie pas les identifiants techniques ni une mention de source dans le texte : les sources sont affichees separement. "
    "Reponds en texte brut, sans syntaxe Markdown ni HTML. Utilise des paragraphes simples et des etapes numerotees en texte courant. "
    "Si aucun outil ne peut appliquer une contrainte explicite de la question, dis-le "
    "au debut puis fournis les donnees obtenues sans inventer."
)

ORM_AGENT_LEGACY_SYSTEM_PROMPT = (
    "Tu es un assistant IA interne spécialisé dans les données ERP Odoo. "
    "Utilise les outils disponibles pour interroger la base de données en temps réel et réponds avec les informations exactes retournées. "
    "Les sources sont affichees separement par l'application : ne les ajoute pas dans le texte de reponse. "
    "Redige en texte brut, sans syntaxe Markdown, tableaux, liens ou balises HTML. "
    "Exemple : Chiffre d'affaires total : 12 450 euros. "
    "IMPORTANT -- honnêteté sur la couverture de la question : si aucun outil disponible ne peut satisfaire EXACTEMENT une contrainte explicite de la question (un classement/tri demandé, une limite de nombre de résultats, un filtre de période ou de catégorie precis), n'utilise JAMAIS l'outil le plus proche pour produire un résultat approximatif présenté comme si la question était pleinement répondue. Dans ce cas, indique explicitement au début de ta réponse quelle contrainte n'a pas pu être appliquée (ex: \"Je n'ai pas d'outil pour classer par produit -- voici la liste brute des commandes, non filtrée par produit :\"), puis fournis quand même les données brutes obtenues plutôt que de refuser totalement."
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
    system_prompt: Optional[str] = None,
) -> List[BaseMessage]:
    """Construct initial message sequence for the ORM ReAct agent loop."""
    if system_prompt is None:
        from config import settings

        system_prompt = (
            ORM_AGENT_SYSTEM_PROMPT
            if settings.ORM_USE_TYPED_RUNTIME
            else ORM_AGENT_LEGACY_SYSTEM_PROMPT
        )
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
        f"Rédige en texte brut, sans syntaxe Markdown, tableau ou balise HTML. Utilise des paragraphes simples et des étapes numérotées en texte courant. "
    )


__all__ = [
    "ORM_AGENT_SYSTEM_PROMPT",
    "ORM_AGENT_LEGACY_SYSTEM_PROMPT",
    "build_orm_synthesis_prompt",
    "build_orm_agent_messages",
    "build_hybrid_combine_prompt",
]
