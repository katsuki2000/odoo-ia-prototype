"""
rag/graph.py

LangGraph RAG pipeline skeleton.
Flow: retrieve -> generate -> format_output
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
from rag.schemas import AssistantResponse, SourceReference, LLMResponse
from vectorstore.search import quick_retrieve

logger = logging.getLogger(__name__)


# ── State Definition ──────────────────────────────────────────────────────────

class RAGState(TypedDict):
    question: str
    chat_history: List[BaseMessage]
    retrieved_chunks: List[dict]
    raw_answer: str
    response: Optional[AssistantResponse]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def retrieve(state: RAGState) -> dict:
    """Retrieve relevant documents for the query."""
    question = state["question"]
    logger.info("Node [retrieve]: Fetching documents for: %s", question)
    
    # Using the existing retrieve from Step 3
    try:
        chunks = quick_retrieve(query=question, top_k=5, use_reranker=True)
    except Exception as e:
        logger.error("Error during retrieval: %s", e)
        chunks = []
        
    return {"retrieved_chunks": chunks}


def generate(state: RAGState) -> dict:
    """Generate structured answer using Groq."""
    question = state["question"]
    chunks = state["retrieved_chunks"]
    logger.info("Node [generate]: Building prompt and calling LLM")

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
        logger.error("LLM Generation failed: %s", e)
        response = AssistantResponse(
            answer=f"Désolé, une erreur s'est produite lors de la génération. Détails: {str(e)}",
            sources=[],
            confidence=0.0
        )
        
    return {"response": response, "raw_answer": response.answer if response else ""}


def format_output(state: RAGState) -> dict:
    """Format and clean up the final output (e.g. OCR warnings)."""
    logger.info("Node [format_output]: Formatting final response")
    # Day 1: we just pass through. OCR logic comes in Day 3.
    
    response = state.get("response")
    chunks = state.get("retrieved_chunks", [])
    
    if response and chunks:
        # For now, let's just make sure sources are populated if LLM missed them or we want to enrich them
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
    """Build and compile the RAG LangGraph."""
    workflow = StateGraph(RAGState)
    
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("generate", generate)
    workflow.add_node("format_output", format_output)
    
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", "format_output")
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
