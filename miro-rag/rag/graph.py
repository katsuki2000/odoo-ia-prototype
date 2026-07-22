"""
rag/graph.py

LangGraph RAG pipeline with hybrid routing.
Flow:
  retrieve → route → [documentaire]  → generate         → format_output → END
                   → [donnees_erp]   → orm_agent_loop   → format_output → END
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


# Max ReAct iterations before forced stop (per implementation plan)
REACT_RECURSION_LIMIT = 6

# ── State Definition ──────────────────────────────────────────────────────────

class RAGState(TypedDict):
    question: str
    chat_history: List[BaseMessage]
    uid: Optional[int]
    skills: Optional[dict]
    timing: dict
    retrieved_chunks: List[dict]
    raw_answer: str
    route: Optional[str]
    response: Optional[AssistantResponse]
    uid: Optional[int]  # Odoo user uid for RBAC passthrough


# ── Nodes ─────────────────────────────────────────────────────────────────────

def retrieve(state: RAGState) -> dict:
    """Retrieve relevant documents for the query."""
    import time
    start_time = time.time()
    question = state["question"]
    logger.info("Node [retrieve]: Fetching documents for: %s", question)
    
    try:
        chroma_manager, bm25_index = get_retriever()
        chunks = search_retrieve(
            query=question, 
            top_k=10, 
            chroma_manager=chroma_manager,
            bm25_index=bm25_index,
            use_reranker=False
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
    import time
    start_time = time.time()
    chunks = state.get("retrieved_chunks", [])
    question = state.get("question", "").lower()
    logger.info("Node [route]: Classifying query type from %d chunks", len(chunks))

    # Explicit ERP keywords list
    erp_keywords = [
        "combien de", "montant total", "total des", "chiffre d'affaires",
        "statut de la", "statut commande", "factures impayées", "factures payées",
        "quantité disponible", "produit en rupture", "le plus récent",
        "tickets résolus", "tickets en cours", "tickets de support", "tickets", "ticket", "rechercher client", "coordonnées",
        "toutes périodes confondues", "ce mois", "cette année", "moyenne", 
        "stock", "quel produit", "montant moyen"
    ]
    doc_keywords = ["comment", "procédure", "qui peut", "qui doit", "quel fichier", "quelle classe", "quel est le rôle", "quels sont les modèles", "dans quel fichier", "procédure de validation"]
    data_terms = ["combien", "montant", "ticket", "vente", "statut", "liste", "résolu", "en cours", "stock", "facture", "commande", "client", "chiffre"]

    # Hybrid check MUST come first to avoid overriding mixed questions that contain both procedure and data keywords
    is_hybrid = any(kw in question for kw in doc_keywords) and any(term in question for term in data_terms)

    if is_hybrid:
        logger.info("Node [route]: Query is hybrid → HYBRIDE branch")
        route_decision = QueryRoute.HYBRIDE.value
    elif any(kw in question for kw in doc_keywords):
        logger.info("Node [route]: Query matched explicit doc keywords → DOCUMENTAIRE branch")
        route_decision = QueryRoute.DOCUMENTAIRE.value
    elif any(kw in question for kw in erp_keywords):
        logger.info("Node [route]: Query matched explicit ERP keywords → DONNEES_ERP branch")
        route_decision = QueryRoute.DONNEES_ERP.value
    elif not chunks:
        logger.info("Node [route]: No chunks → defaulting to documentaire")
        route_decision = QueryRoute.DOCUMENTAIRE.value
    else:
        # Count how many chunks come from ERP data sources
        erp_count = 0
        for chunk in chunks:
            meta = chunk.get("metadata") or {}
            chunk_type = meta.get("type", "").lower().strip()
            if chunk_type in ERP_TYPES:
                erp_count += 1

        erp_ratio = erp_count / len(chunks) if len(chunks) > 0 else 0
        logger.info("Node [route]: ERP ratio = %d/%d (%.0f%%)", erp_count, len(chunks), erp_ratio * 100)

        if erp_ratio >= 0.6 and any(term in question for term in data_terms):
            logger.info("Node [route]: High ERP ratio + data terms → DONNEES_ERP branch")
            route_decision = QueryRoute.DONNEES_ERP.value
        else:
            logger.info("Node [route]: → DOCUMENTAIRE branch")
            route_decision = QueryRoute.DOCUMENTAIRE.value

    timing = state.get("timing", {}).copy()
    timing["routing_time"] = time.time() - start_time
    return {"route": route_decision, "timing": timing}


def route_decision(state: RAGState) -> str:
    """Return the routing key for conditional edges."""
    return state.get("route", QueryRoute.DOCUMENTAIRE.value)


def generate(state: RAGState) -> dict:
    """Generate structured answer using Groq (documentary branch)."""
    import time
    start_time = time.time()
    question = state["question"]
    chunks = state["retrieved_chunks"]
    logger.info("Node [generate]: Building prompt and calling LLM")

    # Fast-fail for out of scope
    if _is_out_of_scope(question):
        logger.info("Node [generate]: Deterministic out-of-scope refusal.")
        response = AssistantResponse(
            answer=OUT_OF_SCOPE_ANSWER,
            sources=[],
            confidence=0.0,
        )
        timing = state.get("timing", {}).copy()
        timing["generation_time"] = time.time() - start_time
        return {"response": response, "raw_answer": response.answer, "timing": timing}

    # Fallback if no relevant chunks are found
    if not chunks:
        logger.info("Node [generate]: No chunks retrieved, falling back.")
        response = AssistantResponse(
            answer="Je n'ai pas de source fiable pour répondre à cette question.",
            sources=[],
            confidence=0.0
        )
        timing = state.get("timing", {}).copy()
        timing["generation_time"] = time.time() - start_time
        return {"response": response, "raw_answer": response.answer, "timing": timing}

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
        
    timing = state.get("timing", {}).copy()
    timing["generation_time"] = time.time() - start_time
    return {"response": response, "raw_answer": response.answer if response else "", "timing": timing}


def orm_agent_loop(state: RAGState) -> dict:
    """
    ReAct agent loop: Reason → call ORM tool → observe → repeat or answer.
    Bound to all 8 Odoo ORM tools via llm.bind_tools().
    Recursion capped at REACT_RECURSION_LIMIT iterations.
    """
    import time
    start_time = time.time()
    
    from langchain_core.messages import AIMessage, ToolMessage
    from tools.odoo_tools import (
        get_total_sales,
        get_product_stock,
        get_order_status,
        get_total_invoices,
        search_partner,
        get_recent_tickets,
        list_out_of_stock_products,
        get_period_revenue,
        get_average_sales,
        get_sale_details,
    )

    question = state["question"]
    chat_history = state.get("chat_history", [])
    logger.info("Node [orm_agent_loop]: Starting ReAct loop for: %s", question)

    if _is_out_of_scope(question):
        logger.info("Node [orm_agent_loop]: Out of scope question.")
        response = AssistantResponse(
            answer=OUT_OF_SCOPE_ANSWER,
            sources=[],
            confidence=0.0,
        )
        timing = state.get("timing", {}).copy()
        timing["generation_time"] = time.time() - start_time
        return {"response": response, "raw_answer": response.answer, "timing": timing}

    skills = state.get("skills", {})
    
    # Base tools (always available)
    all_tools = [search_partner]
    
    # Skill filtering
    if skills.get("ventes", True):
        all_tools.extend([get_total_sales, get_order_status, get_period_revenue, get_average_sales, get_sale_details])
        
    if skills.get("stocks", True):
        all_tools.extend([get_product_stock, list_out_of_stock_products])
        
    if skills.get("comptabilite", True):
        all_tools.extend([get_total_invoices])
        
    if skills.get("tickets", True):
        all_tools.extend([get_recent_tickets])

    # Re-bind tools dynamically to the LLM
    llm = ChatGroq(
        model=GROQ_MODEL,
        api_key=GROQ_API_KEY,
        temperature=0.0,
    )
    llm_with_tools = llm.bind_tools(all_tools)

    system_prompt = (
        "Tu es MIRO Assistant, l'assistant IA interne spécialisé dans les données ERP Odoo. "
        "Utilise les outils disponibles pour interroger la base de données en temps réel et réponds avec les informations exactes retournées. "
        "Indique toujours la source exacte des données à la fin de ta réponse (ex: [Source: Odoo ERP - Module ...])."
    )

    messages = [
        SystemMessage(content=system_prompt),
        *chat_history[-10:],
        HumanMessage(content=question),
    ]

    tool_observations = []
    final_answer = None

    for iteration in range(REACT_RECURSION_LIMIT):
        logger.info("Node [orm_agent_loop]: Iteration %d/%d", iteration + 1, REACT_RECURSION_LIMIT)

        # If we already executed tool calls, output clean combined answer
        if tool_observations:
            logger.info("Node [orm_agent_loop]: Tool observations collected, outputting combined answer.")
            valid_obs = [obs for obs in tool_observations if "n'existe pas" not in obs and "pas été trouvé" not in obs and "Aucune vente trouvée" not in obs]
            selected_obs = valid_obs if valid_obs else tool_observations
            final_answer = "\n".join(selected_obs)
            break

        try:
            ai_msg = llm_with_tools.invoke(messages)
        except Exception as e:
            logger.warning("LLM invoke failed at iteration %d: %s", iteration + 1, e)
            # ── Recovery: parse malformed tool calls from small models ──
            # Llama 3.1 8B sometimes generates <function=name>{"arg": "val"}
            # instead of structured JSON. Groq rejects it with a 400 containing
            # the raw text in 'failed_generation'. We parse it and continue.
            recovered = False
            err_str = str(e)
            if "failed_generation" in err_str:
                import re
                match = re.search(r'<function=(\w+)>\s*(\{.*?\})', err_str)
                if match:
                    fn_name = match.group(1)
                    try:
                        import json as _json
                        fn_args = _json.loads(match.group(2))
                        tool_map = {t.name: t for t in all_tools}
                        if fn_name in tool_map:
                            logger.info("Recovered malformed tool call: %s(%s)", fn_name, fn_args)
                            observation = tool_map[fn_name].invoke(fn_args)
                            tool_observations.append(str(observation))
                            # Feed the observation back as a HumanMessage so the LLM
                            # can use it on the next iteration (no tool_call_id needed)
                            messages.append(HumanMessage(
                                content=f"Résultat de l'outil {fn_name} : {observation}"
                            ))
                            recovered = True
                    except Exception as parse_err:
                        logger.error("Recovery parse failed: %s", parse_err)
            if not recovered:
                logger.error("Unrecoverable LLM error at iteration %d", iteration + 1)
                break
            continue  # Skip normal ai_msg processing, go to next iteration

        messages.append(ai_msg)

        # No tool calls → we have the final answer
        if not getattr(ai_msg, "tool_calls", None):
            final_answer = ai_msg.content
            logger.info("Node [orm_agent_loop]: Final answer at iteration %d", iteration + 1)
            break

        # Execute each tool call
        for tool_call in ai_msg.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]
            logger.info("Node [orm_agent_loop]: Calling tool '%s' with args %s", tool_name, tool_args)

            if tool_name not in [t.name for t in all_tools]:
                observation = f"Outil '{tool_name}' non disponible."
            else:
                try:
                    tool_map = {t.name: t for t in all_tools}
                    observation = tool_map[tool_name].invoke(tool_args)
                except Exception as e:
                    observation = f"Erreur lors de l'appel à {tool_name}: {str(e)}"
                    logger.error("Tool call error: %s", e)

            tool_observations.append(observation)
            messages.append(ToolMessage(content=str(observation), tool_call_id=tool_id))
    else:
        # Recursion limit hit — force a final synthesis
        logger.warning("Node [orm_agent_loop]: Recursion limit reached. Forcing final answer.")
        synthesis_prompt = (
            f"Question originale : {question}\n\n"
            f"Observations collectées :\n" + "\n".join(tool_observations) +
            "\n\nFournis une réponse finale et concise en français basée uniquement sur ces observations."
        )
        try:
            plain_llm = ChatGroq(model=GROQ_MODEL, temperature=0.0, max_tokens=512)
            final_resp = plain_llm.invoke([HumanMessage(content=synthesis_prompt)])
            final_answer = final_resp.content
        except Exception as e:
            logger.error("Forced synthesis failed: %s", e)
            final_answer = "Je n'ai pas pu obtenir une réponse complète. Veuillez reformuler la question."

    if not final_answer:
        final_answer = "Je n'ai pas de données disponibles pour répondre à cette question."

    # Build sources from tool observations
    sources = []
    for obs in tool_observations:
        if obs and str(obs).strip():
            sources.append(SourceReference(
                source="odoo://xmlrpc",
                doc_type="erp_data",
                title="Données ERP Odoo",
                snippet=str(obs)[:150],
            ))

    response = AssistantResponse(
        answer=final_answer,
        sources=sources,
        confidence=0.9 if tool_observations else 0.5,
    )
    
    timing = state.get("timing", {}).copy()
    timing["generation_time"] = time.time() - start_time
    return {"response": response, "raw_answer": response.answer, "timing": timing}


def hybrid_node(state: RAGState) -> dict:
    """Agent that orchestrates a hybrid query by dispatching to doc-reader and tool-caller sequentially, then combining."""
    import time
    start_time = time.time()
    logger.info("Node [hybrid_node]: Delegating to doc agent and data agent")
    
    # Run the documentaire branch to get procedures
    doc_state = state.copy()
    doc_result = generate(doc_state)
    doc_answer = doc_result.get("raw_answer", "")
    
    data_state = state.copy()
    data_state["retrieved_chunks"] = []
    data_state["question"] = state["question"]
    data_result = orm_agent_loop(data_state)
    data_answer = data_result.get("raw_answer", "")
    
    # Combine the two using a final Synthesis LLM
    from langchain_core.messages import HumanMessage
    from langchain_groq import ChatGroq
    from config.settings import GROQ_MODEL
    
    combine_prompt = (
        f"Tu es l'agent de synthèse finale.\n"
        f"La question de l'utilisateur était : '{state['question']}'\n\n"
        f"Voici ce que l'agent de documentation a trouvé sur les procédures :\n{doc_answer}\n\n"
        f"Voici ce que l'agent des données ERP a trouvé dans les chiffres :\n{data_answer}\n\n"
        f"Combine ces deux informations pour faire une seule réponse cohérente et fluide, sans mentionner l'existence des agents."
    )
    
    try:
        plain_llm = ChatGroq(model=GROQ_MODEL, temperature=0.3, max_tokens=1024)
        final_resp = plain_llm.invoke([HumanMessage(content=combine_prompt)])
        final_answer = final_resp.content
    except Exception as e:
        logger.error("Hybrid combine failed: %s", e)
        final_answer = f"{doc_answer}\n\n{data_answer}"
        
    # Combine sources safely
    sources = []
    if doc_result.get("response") and doc_result["response"].sources:
        sources.extend(doc_result["response"].sources)
    if data_result.get("response") and data_result["response"].sources:
        sources.extend(data_result["response"].sources)
        
    confidence = 0.5
    if doc_result.get("response") and data_result.get("response"):
        confidence = min(doc_result["response"].confidence, data_result["response"].confidence)
        
    response = AssistantResponse(
        answer=final_answer,
        sources=sources,
        confidence=confidence
    )
    
    timing = state.get("timing", {}).copy()
    timing["hybrid_time"] = time.time() - start_time
    return {"response": response, "raw_answer": final_answer, "timing": timing}


def format_output(state: RAGState) -> dict:
    """Format and clean up the final output (e.g. OCR warnings)."""
    logger.info("Node [format_output]: Formatting final response")
    
    response = state.get("response")
    chunks = state.get("retrieved_chunks", [])
    
    route = state.get("route")
    if response and chunks and route == QueryRoute.DOCUMENTAIRE.value:
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
            
        if response.sources and "[Source:" not in response.answer:
            main_src = response.sources[0].title or response.sources[0].source
            response.answer += f"\n\n[Source: Documentation Odoo - {main_src}]"

    return {"response": response}


# ── Graph Construction ────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Build and compile the RAG LangGraph with hybrid routing."""
    workflow = StateGraph(RAGState)

    # Add nodes
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("route", route)
    workflow.add_node("generate", generate)
    workflow.add_node("orm_agent_loop", orm_agent_loop)
    workflow.add_node("hybrid_node", hybrid_node)
    workflow.add_node("format_output", format_output)

    # Edges
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "route")

    # Conditional routing
    workflow.add_conditional_edges("route", route_decision, {
        QueryRoute.DOCUMENTAIRE.value: "generate",
        QueryRoute.DONNEES_ERP.value: "orm_agent_loop",
        QueryRoute.HYBRIDE.value: "hybrid_node",
    })

    workflow.add_edge("generate", "format_output")
    workflow.add_edge("orm_agent_loop", "format_output")
    workflow.add_edge("hybrid_node", "format_output")
    workflow.add_edge("format_output", END)

    return workflow.compile()


def query_graph(
    question: str,
    chat_history: Optional[List[BaseMessage]] = None,
    uid: Optional[int] = None,
    api_key: Optional[str] = None,
    skills: Optional[dict] = None,
) -> AssistantResponse:
    """
    Public API to query the graph.
    uid: Odoo user id for RBAC passthrough.
    api_key: Odoo user API key / password for authenticated XML-RPC calls.
    """
    import time
    import json
    start_time = time.time()
    
    if chat_history is None:
        chat_history = []
    if skills is None:
        skills = {}

    from tools.odoo_tools import odoo_uid_ctx, odoo_api_key_ctx
    # Propagate the uid and api_key to tools via contextvars
    uid_token = None
    api_key_token = None
    if uid is not None:
        uid_token = odoo_uid_ctx.set(uid)
    if api_key is not None:
        api_key_token = odoo_api_key_ctx.set(api_key)

    try:
        app = build_graph()
        initial_state = {
            "question": question,
            "chat_history": chat_history,
            "uid": uid,
            "skills": skills,
            "timing": {},
            "retrieved_chunks": [],
            "raw_answer": "",
            "route": None,
            "response": None,
        }
    
        logger.info("Invoking graph for question: '%s'", question)
        final_state = app.invoke(initial_state)
        
        # Logging structured latency
        timing = final_state.get("timing", {})
        timing["total_time"] = time.time() - start_time
        logger.info(json.dumps({"event": "request_latency", "metrics": timing}))
        
        return final_state["response"]
    except Exception as e:
        logger.error("Graph execution failed: %s", e)
        return AssistantResponse(
            answer="Une erreur interne s'est produite lors de l'exécution du pipeline.",
            sources=[],
            confidence=0.0
        )
    finally:
        if uid_token:
            odoo_uid_ctx.reset(uid_token)
        if api_key_token:
            odoo_api_key_ctx.reset(api_key_token)

