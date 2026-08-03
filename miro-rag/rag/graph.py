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
import json
import threading
import time
from pathlib import Path
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

import re

# ── Groq Rate Limiting & Throttle ─────────────────────────────────────────────
_groq_call_lock = threading.Lock()
_last_groq_call_time = [0.0]
MIN_GROQ_CALL_INTERVAL = 5.0  # Enforce 5.0s minimum spacing between LLM calls


def _parse_reset_seconds(header_value: str, default: float = 20.0) -> float:
    """
    Groq's x-ratelimit-reset-* headers come as e.g. '13.42s' or '1m3.42s'.
    Parse into a plain float number of seconds.
    """
    if not header_value:
        return default
    match = re.match(r"(?:(\d+)m)?([\d.]+)s", header_value.strip())
    if not match:
        return default
    minutes = float(match.group(1)) if match.group(1) else 0.0
    seconds = float(match.group(2))
    return minutes * 60 + seconds


def _extract_rate_limit_headers(exc: Exception) -> dict:
    """
    Best-effort extraction of Groq rate-limit headers from whatever
    exception langchain_groq/groq-python raises on a 429.
    """
    for attr_path in ("response", "http_response", "resp"):
        resp = getattr(exc, attr_path, None)
        if resp is not None and hasattr(resp, "headers"):
            return dict(resp.headers)
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        resp = getattr(cause, "response", None)
        if resp is not None and hasattr(resp, "headers"):
            return dict(resp.headers)
    return {}

class _ToolCallFallback:
    """Stand-in minimal pour un AIMessage : seuls .tool_calls et .content sont lus par la boucle ReAct."""
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls
        self.content = ""


_TOOL_USE_FAILED_RE = re.compile(r"'code':\s*'tool_use_failed'.*?'failed_generation':\s*'(.*?)'\s*\}", re.DOTALL)
_FAILED_GEN_CALL_RE = re.compile(r"<function=(\w+)>(\{.*\})")


def _try_recover_tool_use_failed(exc: Exception):
    """
    llama-3.1-8b-instant régresse parfois vers un pattern texte
    '<function=NOM>{...}' au lieu d'un tool_call structuré, ce que
    l'API Groq rejette en 400 tool_use_failed. On récupère l'intention
    par regex plutôt que de perdre le tour.
    Retourne None si le payload n'est pas récupérable (laisse la place au retry).
    """
    msg = str(exc)
    if "tool_use_failed" not in msg:
        return None
    match = _TOOL_USE_FAILED_RE.search(msg)
    if not match:
        return None
    call_match = _FAILED_GEN_CALL_RE.search(match.group(1))
    if not call_match:
        return None
    fn_name, args_raw = call_match.group(1), call_match.group(2)
    try:
        args = json.loads(args_raw)
    except json.JSONDecodeError:
        return None
    logger.warning("Récupération d'un tool_call malformé via failed_generation: %s(%s)", fn_name, args)
    return _ToolCallFallback([{"name": fn_name, "args": args, "id": f"fallback_{fn_name}", "type": "tool_call"}])

def _invoke_with_rate_limit(llm_with_tools, messages, max_retries: int = 5):
    """
    Invoke le LLM Groq avec :
      - espacement minimal entre appels
      - backoff dynamique sur 429 (headers x-ratelimit-reset-tokens)
      - récupération / retry renforcé sur tool_use_failed
      - retry générique avec backoff exponentiel sur erreurs de connexion transitoires
    """
    for attempt in range(max_retries):
        with _groq_call_lock:
            elapsed = time.time() - _last_groq_call_time[0]
            if elapsed < MIN_GROQ_CALL_INTERVAL:
                time.sleep(MIN_GROQ_CALL_INTERVAL - elapsed)
            try:
                result = llm_with_tools.invoke(messages)
                _last_groq_call_time[0] = time.time()
                if hasattr(result, "response_metadata"):
                    logger.info("GROQ DIAGNOSTIC METADATA: %s", result.response_metadata)
                return result
            except Exception as e:
                _last_groq_call_time[0] = time.time()
                err_str = str(e)

                # Cas 1 : rate limit (comportement existant, inchangé)
                is_rate_limit = "429" in err_str or "rate_limit" in err_str.lower()
                if is_rate_limit and attempt < max_retries - 1:
                    headers = _extract_rate_limit_headers(e)
                    reset_raw = (
                        headers.get("x-ratelimit-reset-tokens")
                        or headers.get("x-ratelimit-reset-requests")
                    )
                    wait_time = _parse_reset_seconds(reset_raw, default=2 ** attempt * 5.0)
                    wait_time += 0.5
                    logger.warning(
                        "Groq rate limit hit (attempt %d/%d). Headers: %s. Dynamically waiting %.1fs...",
                        attempt + 1, max_retries,
                        {k: v for k, v in headers.items() if "ratelimit" in k.lower()},
                        wait_time,
                    )
                    time.sleep(wait_time)
                    continue

                # Cas 2 : tool_use_failed -- tenter la récupération, sinon retry renforcé
                if "tool_use_failed" in err_str:
                    recovered = _try_recover_tool_use_failed(e)
                    if recovered is not None:
                        return recovered
                    if attempt < max_retries - 1:
                        logger.warning(
                            "tool_use_failed non récupérable (attempt %d/%d), retry avec instruction renforcée.",
                            attempt + 1, max_retries,
                        )
                        messages = messages + [
                            SystemMessage(content=(
                                "RAPPEL STRICT : réponds UNIQUEMENT via un appel d'outil structuré "
                                "(tool_call). N'écris jamais de pseudo-appel en texte libre du type "
                                "<function=...>{...}>."
                            ))
                        ]
                        time.sleep(1.0)
                        continue
                    raise

                # Cas 3 : erreurs de connexion transitoires -- retry générique
                is_connection_error = any(
                    term in err_str.lower()
                    for term in ("connection", "timeout", "timed out", "temporarily unavailable")
                )
                if is_connection_error and attempt < max_retries - 1:
                    wait_time = 2 ** attempt * 3.0
                    logger.warning(
                        "Erreur de connexion transitoire (attempt %d/%d): %s. Retry dans %.1fs...",
                        attempt + 1, max_retries, err_str, wait_time,
                    )
                    time.sleep(wait_time)
                    continue

                raise
 
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
    code_intel_keywords = [
        "qui a accès", "qui a acces", "droit d'accès", "droit d acces", "droits d'accès",
        "droit de lecture", "droit d'écriture", "droit de modification", "droit de suppression",
        "quel groupe a accès", "quels groupes ont accès", "qui a le droit",
        "règle d'enregistrement", "regle d'enregistrement", "ir.rule", "règle de sécurité", "regle de securite",
        "action serveur", "action automati", "base.automation", "ir.actions.server", "sudo", "logique cachée",
        "verrou", "validateurs exceptionnels", "validationerror", "usererror", "dispatch dynamique", "getattr",
        "impact de la modification", "impact de modification", "si je modifie le champ",
        "changement du champ", "impact du champ", "champs calculés dépendants",
        "chemin d'exécution", "chemin execution", "bouton", "quand je clique sur",
        "action du bouton", "que fait le bouton", "modèle odoo", "modele odoo"
    ]

    # Quantitative data terms that indicate a real ERP data need (not just mentioning an ERP concept)
    quantitative_terms = ["combien", "montant", "total", "résolu", "en cours", "moyenne", "chiffre", "quel est le stock"]
    doc_keywords = ["comment", "procédure", "qui peut", "qui doit", "quel fichier", "quelle classe", "quel est le rôle", "quels sont les modèles", "dans quel fichier", "procédure de validation", "politique interne", "selon le wiki"]
    data_terms = ["combien", "montant", "ticket", "vente", "statut", "liste", "résolu", "en cours", "stock", "facture", "commande", "client", "chiffre"]

    # Hybrid check: doc keyword + quantitative ERP term (not just generic nouns like 'facture')
    is_hybrid = any(kw in question for kw in doc_keywords) and any(term in question for term in quantitative_terms)

    if any(kw in question for kw in code_intel_keywords):
        logger.info("Node [route]: Query matched Code Intelligence keywords → CODE_INTELLIGENCE branch")
        route_decision = QueryRoute.CODE_INTELLIGENCE.value
    elif is_hybrid:
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


# ── Code Intelligence Agent ───────────────────────────────────────────────────

# C.1.3: System prompt with explicit scope-first navigation strategy.
CI_SYSTEM_PROMPT = (
    "You are MIRO Code Intelligence Assistant specializing in Odoo source code and security analysis.\n"
    "NAVIGATION STRATEGY:\n"
    "1. When target models or modules are provided by [BUSINESS TERM RESOLVER S2.0], invoke the appropriate tools immediately:\n"
    "   - For approval limits, hardcoded emails (_VALIDATEURS_EXCEPTIONNELS), UserError/ValidationError strings, or dynamic getattr dispatches: ALWAYS invoke `analyser_verrous_securite`.\n"
    "   - For ir.rule record rules and group-based RECORD visibility: invoke `evaluer_regles_enregistrement` (authoritative). A `qui_a_acces_a` \"could not be resolved\" message for the same group does NOT contradict it.\n"
    "   - For automated actions, ir.actions.server, or sudo() bypasses: invoke `analyser_actions_serveur`.\n"
    "2. DO NOT make generic fallbacks. Synthesize the tool observations directly.\n"
    "3. Always cite source file links: [file.py:L12-L25](file:///path#L12-L25).\n"
    "4. When citing a rule, group, or action by its Odoo technical identifier as a "
    "sourcing claim (not just using it as ordinary vocabulary), prefix it exactly as "
    "'xml_id: module.identifier' (e.g. xml_id: custom_credit_note_visibility_rules."
    "rule_avoir_visibilite_regionale)."
)

# C.1.4: Maximum hops allowed per question.
CI_MAX_HOPS = 4

# J8 (Bloc 2): deterministic security-lock trigger.
# J7 found that the LLM does not reliably invoke analyser_verrous_securite
# on its own, even with the explicit "ALWAYS invoke" directive already in
# CI_SYSTEM_PROMPT (Q3.1: analyser_verrous_securite is correct and
# HIGH-confidence in isolation, but the LLM simply never calls it for
# approval-limit questions with a monetary amount). Rather than trying to
# word the prompt more forcefully -- which already failed once -- the
# amount is detected deterministically in code and the tool call is forced,
# removing the LLM from that decision entirely.
_AMOUNT_PATTERN = re.compile(r"\d[\d\s.,]*\d\s*(?:€|eur(?:os?)?\b)", re.IGNORECASE)
# Regression found on this same J8 patch (Q6.2, run of 2026-08-06): matching
# on amount alone forces analyser_verrous_securite even for pure ir.rule
# visibility questions ("peut voir un avoir de 80k?"), and the synthesis LLM
# then wrongly cross-attributed a Python-lock approval threshold (5000e) to
# an unrelated ir.rule rule name. Requiring an approval-intent keyword in
# addition to the amount keeps the forced dispatch scoped to what Q3.1
# actually needed (approval-limit / bypass questions), and leaves pure
# visibility questions to evaluer_regles_enregistrement alone.
_APPROVAL_PATTERN = re.compile(r"\b(?:approuv\w*|valid\w*|approbation\w*)\b", re.IGNORECASE)
# J8/J9: dedicated trigger for analyser_actions_serveur -- deliberately
# NOT reusing _APPROVAL_PATTERN alone (tested against the adversarial set:
# would fire on 6/9 questions, repolluting Python-lock questions like
# Q1.1/Q3.1/Q9.1 with irrelevant server-action noise -- same class of risk
# as the Q6.2 regression on _AMOUNT_PATTERN). Scoped to vocabulary that
# actually signals automation/bypass logic, not just "approval" in general.
# "tous les" / "toutes les" deliberately excluded: too generic in French
# (fires on unrelated questions like "tous les employés peuvent-ils...");
# "mêmes règles" alone already covers Q5.1's actual wording.
_AUTOMATION_PATTERN = re.compile(
    r"\b(?:mêmes?\s+règles?|systématiq\w*|automatiq\w*|actions?\s+serveur|bypass|contourn\w*)\b",
    re.IGNORECASE,
)


def _question_mentions_amount(question: str) -> bool:
    return bool(_AMOUNT_PATTERN.search(question))


def _question_is_approval_related(question: str) -> bool:
    return bool(_APPROVAL_PATTERN.search(question))


def _question_suggests_automation_bypass(question: str) -> bool:
    return bool(_AUTOMATION_PATTERN.search(question))


_CACHED_CODE_INTEL_GRAPH = None


def _load_module(mod_dir: Path) -> tuple:
    """Load a single Odoo module directory into a ParsedModule."""
    from code_intelligence.manifest_parser import parse_manifest
    from code_intelligence.python_extractor import extract_odoo_models_from_file
    from code_intelligence.xml_extractor import (
        parse_ir_rules_from_xml, parse_groups_from_xml,
        parse_actions_from_xml, parse_menuitems_from_xml, parse_views_from_xml,
        parse_server_actions_from_xml, parse_base_automations_from_xml,
    )
    from code_intelligence.csv_extractor import parse_access_control_csv
    from code_intelligence.cross_file_resolver import ParsedModule

    manifest_p = mod_dir / "__manifest__.py"
    manifest = parse_manifest(manifest_p) if manifest_p.exists() else None
    mod = ParsedModule(manifest=manifest)
    for py_f in mod_dir.rglob("*.py"):
        if py_f.name == "__manifest__.py":
            continue
        mod.models.extend(extract_odoo_models_from_file(py_f))
    for xml_f in mod_dir.rglob("*.xml"):
        mod.rules.extend(parse_ir_rules_from_xml(xml_f))
        mod.groups.extend(parse_groups_from_xml(xml_f))
        mod.actions.extend(parse_actions_from_xml(xml_f))
        mod.server_actions.extend(parse_server_actions_from_xml(xml_f))
        mod.base_automations.extend(parse_base_automations_from_xml(xml_f))
        mod.menuitems.extend(parse_menuitems_from_xml(xml_f))
        mod.views.extend(parse_views_from_xml(xml_f))
    for csv_f in mod_dir.rglob("*.csv"):
        mod.acl_entries.extend(parse_access_control_csv(csv_f))
    return mod_dir.name, mod


def get_code_intelligence_graph():
    """Lazy-load and cache Knowledge Graph for Code Intelligence node."""
    global _CACHED_CODE_INTEL_GRAPH
    if _CACHED_CODE_INTEL_GRAPH is not None:
        return _CACHED_CODE_INTEL_GRAPH

    from code_intelligence.utils import discover_odoo_modules
    from code_intelligence.cross_file_resolver import build_module_symbol_registry
    from code_intelligence.graph_builder import OdooGraphBuilder

    base_dir = Path(__file__).resolve().parent.parent
    corpus_root = base_dir / "fake_data" / "code"
    addons_root = Path("/home/user/odoo-17.0/addons") if Path("/home/user/odoo-17.0/addons").exists() else base_dir.parent / "addons"

    modules_dict = {}

    if corpus_root.exists():
        for mod_dir in corpus_root.iterdir():
            if mod_dir.is_dir():
                name, mod = _load_module(mod_dir)
                modules_dict[name] = mod

    miro_ai_dir = addons_root / "miro_ai"
    if miro_ai_dir.exists():
        name, mod = _load_module(miro_ai_dir)
        modules_dict[name] = mod

    # Load adversarial custom_* modules for end-to-end benchmark support
    if addons_root.exists():
        custom_modules = discover_odoo_modules(addons_root, prefix="custom_")
        for mod_name in custom_modules:
            mod_dir = addons_root / mod_name
            name, mod = _load_module(mod_dir)
            modules_dict[name] = mod

    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    _CACHED_CODE_INTEL_GRAPH = builder.build_graph()
    logger.info(
        "Knowledge Graph built: %d nodes, %d edges, %d modules",
        _CACHED_CODE_INTEL_GRAPH.number_of_nodes(),
        _CACHED_CODE_INTEL_GRAPH.number_of_edges(),
        len(modules_dict),
    )
    return _CACHED_CODE_INTEL_GRAPH


def code_intelligence_agent(state: RAGState) -> dict:
    """
    Node [code_intelligence_agent]: ReAct agent loop for Code Intelligence.

    C.1.1: LangGraph ReAct loop with 9 bound tools (5 composite + 4 auxiliary).
    C.1.2: Anti-loop guard detects duplicate tool+args calls.
    C.1.3: System prompt enforces scope-first navigation strategy.
    C.1.4: Hop counter tracks tool calls; partial response on limit.
    """
    import time
    import json as _json
    start_time = time.time()

    from langchain_core.messages import AIMessage, ToolMessage

    question = state.get("question", "").strip()
    chat_history = state.get("chat_history", [])
    logger.info("Node [code_intelligence_agent]: Starting ReAct loop for: %s", question)

    if _is_out_of_scope(question):
        logger.info("Node [code_intelligence_agent]: Out of scope question.")
        response = AssistantResponse(
            answer=OUT_OF_SCOPE_ANSWER,
            sources=[],
            confidence=0.0,
        )
        timing = state.get("timing", {}).copy()
        timing["code_intelligence_time"] = time.time() - start_time
        return {"response": response, "raw_answer": response.answer, "timing": timing}

    # Initialize the knowledge graph and inject into tool wrappers
    G = get_code_intelligence_graph()
    from code_intelligence.ci_agent_tools import ALL_CI_TOOLS, set_graph_ref, set_llm_ref
    from code_intelligence.business_resolver import resolve_business_term
    set_graph_ref(G)

    # Bind tools to LLM (C.1.1)
    llm = ChatGroq(
        model=GROQ_MODEL,
        api_key=GROQ_API_KEY,
        temperature=0.0,
        max_retries=0,  # Let _invoke_with_rate_limit handle dynamic header backoff
        max_tokens=4096,
    )
    set_llm_ref(llm)
    llm_with_tools = llm.bind_tools(ALL_CI_TOOLS)

    # Story S2.0: Business Term Resolver -- Map natural language concepts to technical Odoo models/modules
    concept = resolve_business_term(question, G, llm=llm)

    tool_observations: list = []
    final_answer = None
    hop_count = 0
    seen_calls: set = set()

    system_prompt = CI_SYSTEM_PROMPT
    if concept.is_resolved:
        resolved_info = []
        if concept.resolved_models:
            resolved_info.append(f"Target Models: {', '.join(concept.resolved_models)}")
        if concept.resolved_modules:
            resolved_info.append(f"Target Modules: {', '.join(concept.resolved_modules)}")
        confidence_tag = (
            f" (LLM-arbitrated, confidence={concept.confidence})"
            if concept.source_step == "llm_arbitration"
            else ""
        )
        system_prompt += (
            f"\n\n[BUSINESS TERM RESOLVER S2.0]\n"
            f"Query term matched: '{concept.user_term}'{confidence_tag}.\n"
            f"{' | '.join(resolved_info)}.\n"
            f"Use these exact technical identifiers when invoking composite tools."
        )

    # J8: force analyser_verrous_securite when the question both resolves to
    # a target model AND mentions a monetary amount. Only fires when a model
    # is actually available -- an unresolved concept is a Bloc 0 problem,
    # not this one.
    if (
        concept.is_resolved
        and concept.resolved_models
        and _question_mentions_amount(question)
        and _question_is_approval_related(question)
    ):
        tool_map = {t.name: t for t in ALL_CI_TOOLS}
        lock_tool = tool_map.get("analyser_verrous_securite")
        if lock_tool is not None:
            for target_model in concept.resolved_models:
                try:
                    forced_observation = lock_tool.invoke({"model_name": target_model})
                    tool_observations.append(str(forced_observation))
                    hop_count += 1
                    seen_calls.add(("analyser_verrous_securite", target_model))
                    logger.info(
                        "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                        "'analyser_verrous_securite' for model '%s' (amount detected in question).",
                        target_model,
                    )
                except Exception as te:
                    logger.error("Deterministic analyser_verrous_securite dispatch failed: %s", te)
            system_prompt += (
                "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                "analyser_verrous_securite has already been run for the target model(s) above "
                "because the question mentions a monetary amount; its output is already included "
                "in the tool observations. Do not call it again -- focus any further tool calls on "
                "what it does NOT cover (e.g. ir.rule / group-based record visibility via "
                "evaluer_regles_enregistrement)."
            )

    # J8/J9: force analyser_actions_serveur when the question resolves to a
    # target model, suggests automation/bypass logic (_AUTOMATION_PATTERN),
    # AND the model structurally has ServerAction nodes in the graph
    # (find_server_action_nodes). The structural guard is the primary
    # defense against noise: on a model with zero server actions the cost
    # of a false-positive keyword match is zero (empty tool_observation
    # never appended), so the keyword pattern doesn't need to be perfectly
    # precise on its own.
    if (
        concept.is_resolved
        and concept.resolved_models
        and _question_suggests_automation_bypass(question)
    ):
        from code_intelligence.ci_agent_tools import find_server_action_nodes
        tool_map = {t.name: t for t in ALL_CI_TOOLS}
        sa_tool = tool_map.get("analyser_actions_serveur")
        if sa_tool is not None:
            for target_model in concept.resolved_models:
                if not find_server_action_nodes(G, target_model):
                    continue  # structural guard: nothing to say, skip silently
                call_key = ("analyser_actions_serveur", target_model)
                if call_key in seen_calls:
                    continue
                try:
                    forced_observation = sa_tool.invoke({"model_name": target_model})
                    tool_observations.append(str(forced_observation))
                    hop_count += 1
                    seen_calls.add(call_key)
                    logger.info(
                        "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                        "'analyser_actions_serveur' for model '%s' (automation/bypass "
                        "wording + ServerAction nodes present).",
                        target_model,
                    )
                except Exception as te:
                    logger.error("Deterministic analyser_actions_serveur dispatch failed: %s", te)
            if any(k[0] == "analyser_actions_serveur" for k in seen_calls):
                system_prompt += (
                    "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                    "analyser_actions_serveur has already been run for the target model(s) "
                    "above because the question suggests automation/bypass logic; its output "
                    "is already included in the tool observations. Do not call it again."
                )

    messages = [
        SystemMessage(content=system_prompt),
        *chat_history[-6:],
        HumanMessage(content=question),
    ]

    for iteration in range(REACT_RECURSION_LIMIT):
        # Single-Pass Composite Execution: 1 Tool Selection turn + 1 Synthesis turn
        try:
            ai_msg = _invoke_with_rate_limit(llm_with_tools, messages)
        except Exception as e:
            logger.error("LLM tool selection failed: %s", e)
            ai_msg = None

        if ai_msg and getattr(ai_msg, "tool_calls", None):
            for tool_call in ai_msg.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]

                # If qui_a_acces_a is called without explicit droit, default to 'all' for single-pass matrix
                if tool_name == "qui_a_acces_a" and "droit" not in tool_args:
                    tool_args["droit"] = "all"

                logger.info("Node [code_intelligence_agent]: Single-Dispatch invoking '%s' with args %s", tool_name, tool_args)
                tool_map = {t.name: t for t in ALL_CI_TOOLS}
                if tool_name in tool_map:
                    try:
                        observation = tool_map[tool_name].invoke(tool_args)
                        tool_observations.append(str(observation))
                        hop_count += 1
                    except Exception as te:
                        logger.error("Tool execution failed (%s): %s", tool_name, te)
                        tool_observations.append(f"Error executing {tool_name}: {str(te)}")
        elif ai_msg and ai_msg.content:
            final_answer = ai_msg.content

        # Synthesize clean final answer from composite tool output
        if not final_answer:
            if tool_observations:
                synthesis_prompt = (
                    f"Original Question: {question}\n\n"
                    f"Knowledge Graph Output:\n" + "\n---\n".join(tool_observations) +
                    f"\n\nSynthesize a clear, professional response based strictly on the "
                    f"data above. Respond in the SAME language as the Original Question "
                    f"above (French question -> French answer, English question -> "
                    f"English answer) -- never mix languages. Do NOT translate exact "
                    f"technical identifiers (model names, XML-IDs, group names, method "
                    f"names) -- copy them verbatim. Each observation above comes from a "
                    f"distinct mechanism (ir.rule evaluation vs Python code lock analysis "
                    f"vs server action analysis) -- NEVER combine a numeric threshold or "
                    f"condition from one mechanism with a rule/lock name from a different "
                    f"one; attribute each finding only to its own source. Any confidence "
                    f"tag present in the source data (e.g. '[Confiance: FAIBLE]', '[Confiance: "
                    f"HIGH]', LLM interpretation confidence) MUST appear in your answer, "
                    f"attached to the specific finding it qualifies -- never drop it, "
                    f"never present a low-confidence or LLM-interpreted finding as an unqualified fact. "
                    f"Any file citation you make MUST keep its exact line range from the "
                    f"source observation (file:///path#L12-L25) -- never drop the line range "
                    f"even when shortening a citation. Any rule/action/group xml_id you cite "
                    f"as a sourcing claim MUST be prefixed 'xml_id: module.identifier', copied "
                    f"verbatim from the source observation."
                )
                try:
                    plain_llm = ChatGroq(model=GROQ_MODEL, temperature=0.0, max_retries=0, max_tokens=4096)
                    final_resp = _invoke_with_rate_limit(plain_llm, [HumanMessage(content=synthesis_prompt)])
                    final_answer = final_resp.content
                except Exception as e:
                    logger.error("Synthesis failed: %s", e)
                    final_answer = "\n\n".join(tool_observations)
            else:
                final_answer = "Je n'ai pas de données disponibles dans le graphe de connaissances pour répondre à cette question."

        if final_answer:
            break

    raw_tool_output = "\n\n".join(tool_observations)
    from code_intelligence.sourcing_guard import verify_citations, annotate_unverifiable_citations
    sourcing_result = verify_citations(final_answer, raw_tool_output)
    if not sourcing_result.is_fully_verified:
        logger.warning("Node [code_intelligence_agent]: Unverified citations -- %s", sourcing_result)
        final_answer = annotate_unverifiable_citations(final_answer, sourcing_result)

    final_answer += "\n\n[Source: Graphe de Connaissances Code Intelligence]"

    # Build sources from tool observations
    sources = []
    for obs in tool_observations:
        if obs and str(obs).strip():
            sources.append(SourceReference(
                source="Code Intelligence Graph",
                doc_type="code_graph",
                title="Graphe de Connaissances Odoo",
                snippet=str(obs)[:150],
            ))

    response = AssistantResponse(
        answer=final_answer,
        sources=sources,
        confidence=1.0 if tool_observations else 0.5,
    )

    timing = state.get("timing", {}).copy()
    timing["code_intelligence_time"] = time.time() - start_time
    timing["ci_hop_count"] = hop_count

    return {
        "response": response,
        "raw_answer": final_answer,
        "timing": timing,
        "raw_tool_output": "\n\n".join(tool_observations),
    }


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
    workflow.add_node("code_intelligence_agent", code_intelligence_agent)
    workflow.add_node("format_output", format_output)

    # Edges
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "route")

    # Conditional routing
    workflow.add_conditional_edges("route", route_decision, {
        QueryRoute.DOCUMENTAIRE.value: "generate",
        QueryRoute.DONNEES_ERP.value: "orm_agent_loop",
        QueryRoute.HYBRIDE.value: "hybrid_node",
        QueryRoute.CODE_INTELLIGENCE.value: "code_intelligence_agent",
    })

    workflow.add_edge("generate", "format_output")
    workflow.add_edge("orm_agent_loop", "format_output")
    workflow.add_edge("hybrid_node", "format_output")
    workflow.add_edge("code_intelligence_agent", "format_output")
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

