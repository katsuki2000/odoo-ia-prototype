"""
rag/graph.py

LangGraph RAG pipeline with hybrid routing.
Flow:
  retrieve → route → [documentaire]  → generate   → format_output → END
                    → [donnees_erp]  → data_query  → format_output → END
"""

import logging
import os
import sys
from typing import TypedDict, List, Optional, Any

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END

from config.settings import LLM_PROVIDER, GROQ_API_KEY, GROQ_MODEL
from rag.schemas import (
    AssistantResponse, SourceReference, LLMResponse,
    QueryRoute, DataQueryIntent,
)
from vectorstore.search import get_retriever, retrieve as search_retrieve

logger = logging.getLogger(__name__)

# ERP metadata types that trigger the data_query branch
ERP_TYPES = {"sale", "ticket"}

OUT_OF_SCOPE_ANSWER = (
    "Cette question ne fait pas partie de mon périmètre. "
    "Je suis spécialisé dans l'assistance et les procédures internes"
)

OUT_OF_SCOPE_TERMS = {
    "blague",
    "gâteau",
    "gateau",
    "recette",
    "coupe du monde",
    "poème",
    "poeme",
    "lune",
}


# ── State Definition ──────────────────────────────────────────────────────────

class RAGState(TypedDict):
    question: str
    chat_history: List[BaseMessage]
    retrieved_chunks: List[dict]
    raw_answer: str
    route: Optional[str]
    response: Optional[AssistantResponse]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def retrieve(state: RAGState) -> dict:
    """Retrieve relevant documents for the query."""
    question = state["question"]
    logger.info("Node [retrieve]: Fetching documents for: %s", question)
    
    try:
        chroma_manager, bm25_index = get_retriever()
        chunks = search_retrieve(
            query=question, 
            top_k=10, 
            chroma_manager=chroma_manager,
            bm25_index=bm25_index,
            use_reranker=True
        )
    except Exception as e:
        logger.error("Error during retrieval: %s", e)
        chunks = []
        
    return {"retrieved_chunks": chunks}


def _is_out_of_scope(question: str) -> bool:
    """Reject obvious non-work questions before the LLM can improvise."""
    normalized_question = question.lower().strip()
    if not normalized_question:
        return False

    return any(term in normalized_question for term in OUT_OF_SCOPE_TERMS)


def route(state: RAGState) -> dict:
    """Classify the query as documentaire or donnees_erp based on chunk metadata and query keywords."""
    chunks = state.get("retrieved_chunks", [])
    question = state.get("question", "").lower()
    logger.info("Node [route]: Classifying query type from %d chunks", len(chunks))

    # Keyword check: if the question explicitly asks for ERP data counts/sums/lists
    erp_keywords = [
        "combien de ventes", "montant total", "combien de tickets", 
        "ticket de support le plus récent", "quel produit a été vendu", 
        "tickets de support encore en cours", "toutes périodes confondues",
        "ventes en cours", "tickets sont résolus", "facturé à ce jour"
    ]
    if any(kw in question for kw in erp_keywords):
        logger.info("Node [route]: Query matched explicit ERP keywords → DONNEES_ERP branch")
        return {"route": QueryRoute.DONNEES_ERP.value}

    if not chunks:
        logger.info("Node [route]: No chunks → defaulting to documentaire")
        return {"route": QueryRoute.DOCUMENTAIRE.value}

    # Count how many chunks come from ERP data sources
    erp_count = 0
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        chunk_type = meta.get("type", "").lower().strip()
        if chunk_type in ERP_TYPES:
            erp_count += 1

    erp_ratio = erp_count / len(chunks) if len(chunks) > 0 else 0
    logger.info("Node [route]: ERP ratio = %d/%d (%.0f%%)", erp_count, len(chunks), erp_ratio * 100)

    # Route to DONNEES_ERP if high ratio and contains basic data terms
    data_terms = ["combien", "montant", "ticket", "vente", "statut", "liste", "résolu", "en cours"]
    if erp_ratio >= 0.6 and any(term in question for term in data_terms):
        logger.info("Node [route]: High ERP ratio + data terms → DONNEES_ERP branch")
        return {"route": QueryRoute.DONNEES_ERP.value}
    else:
        logger.info("Node [route]: → DOCUMENTAIRE branch")
        return {"route": QueryRoute.DOCUMENTAIRE.value}


def route_decision(state: RAGState) -> str:
    """Return the routing key for conditional edges."""
    return state.get("route", QueryRoute.DOCUMENTAIRE.value)


def generate(state: RAGState) -> dict:
    """Generate structured answer using Groq (documentary branch)."""
    question = state["question"]
    chunks = state["retrieved_chunks"]
    logger.info("Node [generate]: Building prompt and calling LLM")

    if _is_out_of_scope(question):
        logger.info("Node [generate]: Deterministic out-of-scope refusal.")
        response = AssistantResponse(
            answer=OUT_OF_SCOPE_ANSWER,
            sources=[],
            confidence=0.0,
        )
        return {"response": response, "raw_answer": response.answer}

    # Fallback if no relevant chunks are found
    if not chunks:
        logger.info("Node [generate]: No chunks retrieved, falling back.")
        response = AssistantResponse(
            answer="Je n'ai pas de source fiable pour répondre à cette question.",
            sources=[],
            confidence=0.0
        )
        return {"response": response, "raw_answer": response.answer}

    from rag.prompts import build_messages

    # Build context text
    context_text = ""
    for i, chunk in enumerate(chunks):
        doc_text = chunk.get("document", "")
        # Coding rule: dict.get for metadata
        metadata = chunk.get("metadata") or {}
        source = metadata.get("source", "unknown")
        context_text += f"[Source {i+1}: {source}]\n{doc_text}\n\n"

    # Build memory + prompt
    chat_history = state.get("chat_history", [])
    messages = build_messages(question, context_text, chat_history)

    try:
        llm = ChatGroq(model=GROQ_MODEL, temperature=0.3, max_tokens=1024)
        # Enforce structured output to match our schema
        structured_llm = llm.with_structured_output(LLMResponse)
        
        llm_resp = structured_llm.invoke(messages)
        response = AssistantResponse(
            answer=llm_resp.answer,
            confidence=llm_resp.confidence,
            sources=[]
        )
    except Exception as e:
        logger.warning("Structured LLM Generation failed (%s) → falling back to raw invoke", e)
        try:
            llm = ChatGroq(model=GROQ_MODEL, temperature=0.3, max_tokens=1024)
            raw_resp = llm.invoke(messages)
            response = AssistantResponse(
                answer=raw_resp.content,
                confidence=0.85,
                sources=[]
            )
        except Exception as e2:
            logger.error("Raw LLM Generation also failed: %s", e2)
            response = AssistantResponse(
                answer=f"Désolé, une erreur s'est produite lors de la génération. Détails: {str(e2)}",
                sources=[],
                confidence=0.0
            )
        
    return {"response": response, "raw_answer": response.answer if response else ""}


def data_query(state: RAGState) -> dict:
    """Execute a deterministic data query on structured ERP data (data branch)."""
    question = state["question"]
    logger.info("Node [data_query]: Extracting intent for: %s", question)

    from rag.prompts import build_data_intent_messages
    from rag.data_tool import DataQueryEngine

    try:
        # Step 1: Use LLM to extract the structured intent
        llm = ChatGroq(model=GROQ_MODEL, temperature=0.0, max_tokens=256)
        structured_llm = llm.with_structured_output(DataQueryIntent)

        messages = build_data_intent_messages(question)
        intent = structured_llm.invoke(messages)
        logger.info("Node [data_query]: Extracted intent → %s", intent)

        # Step 2: Execute the intent deterministically in Python
        engine = DataQueryEngine()
        result_text = engine.execute(intent)

        # Step 3: Build AssistantResponse
        source_name = f"fake_data/{intent.data_source}.json"
        response = AssistantResponse(
            answer=result_text,
            confidence=0.95,
            sources=[SourceReference(
                source=source_name,
                doc_type=intent.data_source,
                title=f"Données {intent.data_source}",
                snippet=f"Opération: {intent.operation}, Filtres: {intent.filters}",
            )]
        )

    except Exception as e:
        logger.error("Data query failed: %s — falling back to generate", e)
        # Fallback: run the documentary generate path instead
        return generate(state)

    return {"response": response, "raw_answer": response.answer}


def format_output(state: RAGState) -> dict:
    """Format and clean up the final output (e.g. OCR warnings)."""
    logger.info("Node [format_output]: Formatting final response")
    
    response = state.get("response")
    chunks = state.get("retrieved_chunks", [])
    
    if response and chunks:
        # OCR Warning Logic
        has_low_ocr = any(chunk.get("metadata", {}).get("ocr_quality") == "low" for chunk in chunks)
        if has_low_ocr:
            response.ocr_warning = True
            response.answer += "\n\n⚠️ *Cette information provient d'un document numérisé dont la qualité de lecture est limitée.*"

        # Populate sources from chunks if not already set (documentary branch)
        if not response.sources:
            sources = []
            for chunk in chunks:
                meta = chunk.get("metadata") or {}
                doc = chunk.get("document", "")
                snippet = doc[:100] + "..." if len(doc) > 100 else doc
                
                sources.append(SourceReference(
                    source=meta.get("source", "unknown"),
                    doc_type=meta.get("type", "document"),
                    title=meta.get("title", meta.get("source", "unknown")),
                    snippet=snippet
                ))
            response.sources = sources

    return {"response": response}


# ── Graph Construction ────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Build and compile the RAG LangGraph with hybrid routing."""
    workflow = StateGraph(RAGState)
    
    # Add nodes
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("route", route)
    workflow.add_node("generate", generate)
    workflow.add_node("data_query", data_query)
    workflow.add_node("format_output", format_output)
    
    # Edges
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "route")
    
    # Conditional routing
    workflow.add_conditional_edges("route", route_decision, {
        QueryRoute.DOCUMENTAIRE.value: "generate",
        QueryRoute.DONNEES_ERP.value: "data_query",
    })
    
    workflow.add_edge("generate", "format_output")
    workflow.add_edge("data_query", "format_output")
    workflow.add_edge("format_output", END)
    
    return workflow.compile()


def query_graph(question: str, chat_history: Optional[List[BaseMessage]] = None) -> AssistantResponse:
    """
    Public API to query the graph.
    """
    if chat_history is None:
        chat_history = []
        
    app = build_graph()
    initial_state = {
        "question": question,
        "chat_history": chat_history,
        "retrieved_chunks": [],
        "raw_answer": "",
        "route": None,
        "response": None
    }
    
    try:
        final_state = app.invoke(initial_state)
        return final_state["response"]
    except Exception as e:
        logger.error("Graph execution failed: %s", e)
        return AssistantResponse(
            answer="Une erreur interne s'est produite lors de l'exécution du pipeline.",
            sources=[],
            confidence=0.0
        )
