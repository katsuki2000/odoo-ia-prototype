"""
rag/prompts.py

System prompts and template building logic for the RAG pipeline.
"""

from typing import List
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage

SYSTEM_PROMPT = """Tu es MIRO Assistant, l'assistant IA interne de MIRO KE, une entreprise spécialisée dans l'implémentation et le support Odoo 17 à Madagascar.

RÈGLES IMPORTANTES :
1. Réponds en français par défaut, mais tu peux répondre en anglais (ou une autre langue) si l'utilisateur te le demande ou te parle dans cette langue.
2. Base tes réponses techniques et métiers UNIQUEMENT sur les documents fournis dans le contexte ci-dessous ou sur tes outils Odoo.
3. Tu es autorisé à répondre poliment aux salutations (Bonjour, Hello, do you speak English ?, etc.) et à expliquer ton rôle (Odoo ERP).
4. Si la question est une question de culture générale ou personnelle complètement hors de ton périmètre professionnel (ex: recette de cuisine, sport), mets exactement ce texte dans 'answer' : "Cette question ne fait pas partie de mon périmètre. Je suis spécialisé dans l'assistance et les procédures internes" et mets 'confidence' à 0.0.
5. Évalue ta confiance de 0.0 à 1.0 dans le champ 'confidence'.

Contexte :
{context}
"""


def build_messages(question: str, context_text: str, chat_history: List[BaseMessage] = None) -> List[BaseMessage]:
    """Build the full message list including system prompt, history, and current question."""
    if chat_history is None:
        chat_history = []
        
    messages = []
    
    # 1. System message with dynamically injected context
    system_msg = SystemMessage(content=SYSTEM_PROMPT.format(context=context_text))
    messages.append(system_msg)
    
    # 2. History (keep only the last 10 messages = 5 exchanges)
    if len(chat_history) > 10:
        chat_history = chat_history[-10:]
        
    messages.extend(chat_history)
    
    # 3. Current question
    messages.append(HumanMessage(content=question))
    
    return messages


# ── Data Intent Extraction Prompt ─────────────────────────────────────────────

DATA_INTENT_PROMPT = """Tu es un analyseur de requêtes. Tu dois extraire l'intention de la question posée par l'utilisateur.

SOURCES DISPONIBLES :
- "sales" : données de ventes. Champs : id, client, produit, montant, devise, date, statut (valeurs possibles : "facturé", "en cours", "annulé")
- "tickets" : tickets de support. Champs : id, titre, client, description, solution, statut (valeurs possibles : "résolu", "en cours"), date

OPÉRATIONS DISPONIBLES :
- "sum" : additionner un champ numérique (nécessite target_field, ex: "montant")
- "count" : compter le nombre d'enregistrements
- "filter" ou "list" : lister les enregistrements correspondants
- "max" : trouver la valeur maximale d'un champ (nécessite target_field)
- "min" : trouver la valeur minimale d'un champ (nécessite target_field)

RÈGLES :
1. Choisis la bonne data_source ("sales" ou "tickets") selon la question.
2. Choisis l'opération la plus appropriée.
3. Extrais les filtres pertinents à partir de la question (client, statut, etc.).
4. Spécifie target_field si l'opération est "sum", "max" ou "min".

EXEMPLES :
- "Combien de ventes Société Dupont ?" → data_source="sales", operation="count", filters={"client": "Société Dupont"}
- "Montant total des ventes en cours" → data_source="sales", operation="sum", filters={"statut": "en cours"}, target_field="montant"
- "Tickets résolus" → data_source="tickets", operation="count", filters={"statut": "résolu"}
- "Quel est le ticket le plus récent de Madagascar Tech ?" → data_source="tickets", operation="filter", filters={"client": "Madagascar Tech"}
"""


def build_data_intent_messages(question: str) -> list[BaseMessage]:
    """Build messages for extracting a DataQueryIntent from a user question."""
    return [
        SystemMessage(content=DATA_INTENT_PROMPT),
        HumanMessage(content=question),
    ]

