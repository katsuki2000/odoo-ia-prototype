"""
code_intelligence/investigation/prompts.py

System prompts and template construction for bounded LLM intent classification.
"""

from typing import List
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage


_INTENT_CLASSIFICATION_SYSTEM_PROMPT = (
    "Tu es un classifieur d'intention pour un assistant Odoo. Classe la question "
    "utilisateur dans EXACTEMENT une des categories suivantes :\n"
    "- governance_security : acces, permissions, droits, regles de visibilite, verrous, approbation\n"
    "- workflow_state : etapes, statuts, transitions, boutons de validation\n"
    "- calculation_logic : champs calculés, formules, montants, dépendances de calcul\n"
    "- inheritance_structure : héritage de modèles, surcharges Python, chaîne MRO\n"
    "- automation_action : actions automatiques, crons, déclencheurs\n"
    "- erp_data_query : donnees ERP en direct (listes, comptages, agrégations, chiffres)\n"
    "- documentary_policy : politique générale, guide utilisateur, procédure documentée, question générale ou de courtoisie\n"
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
