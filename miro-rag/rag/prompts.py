"""
rag/prompts.py

System prompts and template building logic for the RAG pipeline.
"""

from typing import List
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage

SYSTEM_PROMPT = """Tu es MIRO Assistant, l'assistant IA interne de MIRO KE, une entreprise spécialisée dans l'implémentation et le support Odoo 17 à Madagascar.

RÈGLES IMPORTANTES :
1. Réponds TOUJOURS en français dans le champ 'answer'.
2. Base tes réponses UNIQUEMENT sur les documents fournis dans le contexte ci-dessous.
3. Si la question est complètement hors de ton périmètre (ex: recette de cuisine, sport), mets exactement ce texte dans 'answer' : "Cette question ne fait pas partie de mon périmètre. Je suis spécialisé dans l'assistance Odoo et les procédures internes de MIRO KE." et mets 'confidence' à 0.0.
4. Évalue ta confiance de 0.0 à 1.0 dans le champ 'confidence'. Si la réponse est très claire dans le texte, mets une confiance haute (ex: 0.9).
5. Ne fournis pas d'informations hors contexte. Si le contexte ne contient pas de réponse, n'invente rien.

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
