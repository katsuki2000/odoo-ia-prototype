"""
rag/pipeline.py

RAG (Retrieval-Augmented Generation) pipeline:
1. Takes a user query
2. Retrieves relevant document chunks from ChromaDB
3. Builds a context-enriched prompt
4. Sends prompt to LLM (Groq/Llama) for answer generation
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import LLM_PROVIDER, GROQ_API_KEY, GROQ_MODEL, OLLAMA_MODEL, OLLAMA_HOST
from vectorstore.chroma_manager import get_chroma_client, get_or_create_collection, query_collection

_llm_client = None


def get_llm_client():
    """Initialize and return the LLM client."""
    global _llm_client
    if _llm_client is not None:
        return _llm_client

    if LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama
        _llm_client = ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_HOST)
    else:
        raise ValueError(f"Unsupported LLM provider: {LLM_PROVIDER}")

    return _llm_client


SYSTEM_PROMPT = """Tu es MIRO Assistant, l'assistant IA interne de MIRO KE, une entreprise spécialisée dans l'implémentation et le support Odoo 17 à Madagascar.

Tu as accès à la base de connaissances interne de l'entreprise qui contient :
- Les procédures internes (approbation, sécurité IT, onboarding RH, gestion des stocks, processus de vente)
- Les manuels Odoo 17 (facturation, etc.)
- L'historique des tickets de support avec leurs solutions
- Les données de ventes (clients, montants, produits/services)

RÈGLES IMPORTANTES :
1. Réponds TOUJOURS en français.
2. Base tes réponses UNIQUEMENT sur les documents fournis dans le contexte.
3. Si tu ne trouves pas l'information dans le contexte, dis-le clairement : "Je n'ai pas trouvé cette information dans la base de connaissances."
4. Cite tes sources (nom du document, numéro de ticket, etc.).
5. Sois concis et professionnel.
6. Pour les questions sur les montants/ventes, donne des chiffres précis en Ariary (Ar).
"""


def build_context(results):
    """Format ChromaDB search results into a readable context string."""
    if not results or not results.get('documents') or not results['documents'][0]:
        return "No relevant documents found."

    context_parts = []
    for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
        source = meta.get('source', 'unknown')
        doc_type = meta.get('type', 'document')
        title = meta.get('title', '')

        header = f"[Source {i+1}: {doc_type.upper()} - {title or source}]"
        context_parts.append(f"{header}\n{doc}")

    return "\n\n---\n\n".join(context_parts)


def ask(question, n_results=5, where_filter=None, verbose=False):
    """
    Execute full RAG pipeline: retrieve documents, build prompt, generate answer.

    Args:
        question: User query string
        n_results: Number of documents to retrieve
        where_filter: Optional metadata filter dictionary for ChromaDB
        verbose: If True, print retrieved context details to stdout

    Returns:
        Dictionary containing 'answer', 'sources', 'context', and 'question'
    """
    client = get_chroma_client()
    collection = get_or_create_collection(client)
    results = query_collection(collection, question, n_results=n_results, where_filter=where_filter)

    context = build_context(results)

    if verbose:
        print(f"\nRetrieved {len(results['documents'][0])} documents:")
        for i, meta in enumerate(results['metadatas'][0]):
            dist = results['distances'][0][i] if results.get('distances') else 0.0
            print(f"  [{i+1}] {meta.get('type', 'unknown')} | {meta.get('title', meta.get('source', 'unknown'))} | distance: {dist:.4f}")

    user_prompt = f"""Voici les documents pertinents de la base de connaissances :

{context}

---

Question de l'utilisateur : {question}

Réponds de manière précise et professionnelle en te basant sur les documents ci-dessus."""

    llm = get_llm_client()

    if LLM_PROVIDER == "ollama":
        from langchain_core.messages import SystemMessage, HumanMessage
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        answer = response.content
    else:
        answer = "Error: LLM provider not supported."

    sources = []
    if results.get('metadatas') and results['metadatas'][0]:
        for i, meta in enumerate(results['metadatas'][0]):
            doc_text = results['documents'][0][i] if results.get('documents') and len(results['documents'][0]) > i else ""
            snippet = (doc_text[:150] + "...") if len(doc_text) > 150 else doc_text

            title = meta.get('title', '')
            if not title:
                if meta.get('type') == 'sale':
                    title = f"SALE #{meta.get('sale_id', '?')} - {meta.get('client', '')} ({meta.get('produit', '')})"
                elif meta.get('type') == 'ticket':
                    title = f"TICKET #{meta.get('ticket_id', '?')} - {meta.get('client', '')}"
                else:
                    title = meta.get('source', 'unknown')

            sources.append({
                "source": meta.get('source', 'unknown'),
                "type": meta.get('type', 'unknown'),
                "title": title,
                "snippet": snippet,
            })

    return {
        "answer": answer,
        "sources": sources,
        "context": context,
        "question": question,
    }


if __name__ == "__main__":
    print("MIRO Assistant - Interactive Test Mode")
    print("Type 'quit' or 'exit' to stop.\n")

    while True:
        try:
            question = input("Your question: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if question.lower() in ('quit', 'exit', 'q'):
            print("Goodbye.")
            break
        if not question:
            continue

        print("\nSearching and generating answer...\n")
        result = ask(question, verbose=True)
        print(f"\nAnswer:\n{result['answer']}\n")
        print("-" * 60)
