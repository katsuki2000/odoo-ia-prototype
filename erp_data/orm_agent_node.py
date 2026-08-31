"""
rag/orm_agent_node.py

ORM ReAct agent loop (ERP data queries) and hybrid pipeline node.

The ORM agent binds Odoo XML-RPC tools to the LLM and runs a bounded
ReAct loop with malformed-tool-call recovery. The hybrid node
orchestrates both the documentary and ERP branches, then synthesizes.
"""

import json
import logging
import re
import time

from langchain_core.messages import (
    BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage,
)
from langchain_groq import ChatGroq

from config.settings import GROQ_MODEL, GROQ_API_KEY
from core.schemas import AssistantResponse, SourceReference
from core.routing import RAGState, REACT_RECURSION_LIMIT, _is_out_of_scope, OUT_OF_SCOPE_ANSWER
from document_rag.generate_node import generate
# Section 263 (todo/contexte.txt): multi-key Groq rotation / rate-limit
# retry, same mechanism already used by the Code Intelligence branch.
from core.llm_client import (
    invoke_with_rate_limit as _invoke_with_rate_limit,
    _current_groq_key,
)

logger = logging.getLogger(__name__)


def _get_chat_groq():
    """Returns the patched ChatGroq if loaded in core.graph, else real ChatGroq."""
    import sys
    g = sys.modules.get("core.graph")
    if g and hasattr(g, "ChatGroq"):
        return g.ChatGroq
    return ChatGroq


def _build_groq_llm(**kwargs):
    """Construct a ChatGroq client bound to the CURRENT rotation-index Groq
    key (core.llm_client._current_groq_key()), same pattern as
    document_rag/generate_node.py -- keeps going through _get_chat_groq()
    so any future @patch('core.graph.ChatGroq') test remains compatible."""
    return _get_chat_groq()(model=GROQ_MODEL, api_key=_current_groq_key(), **kwargs)


def orm_agent_loop(state: RAGState) -> dict:
    """
    ReAct agent loop: Reason → call ORM tool → observe → repeat or answer.
    Bound to all 8 Odoo ORM tools via llm.bind_tools().
    Recursion capped at REACT_RECURSION_LIMIT iterations.
    """
    import time
    start_time = time.time()
    
    from langchain_core.messages import AIMessage, ToolMessage
    from erp_data.odoo_tools import (
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

    # Reasoning trace and LLM call tracking
    from code_intelligence.reasoning_trace_logger import ReasoningTraceLogger, new_trace_id
    _trace_id = new_trace_id()
    _trace_logger = ReasoningTraceLogger()
    _llm_call_count = 0
    _hop_index = 0

    if _is_out_of_scope(question):
        logger.info("Node [orm_agent_loop]: Out of scope question.")
        response = AssistantResponse(
            answer=OUT_OF_SCOPE_ANSWER,
            sources=[],
            confidence=0.0,
        )
        timing = state.get("timing", {}).copy()
        timing["generation_time"] = time.time() - start_time
        _trace_logger.log_summary(
            trace_id=_trace_id, branch="donnees_erp", question=question,
            hop_count=0, llm_call_count=0, total_time_ms=timing["generation_time"] * 1000,
        )
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
    llm = _build_groq_llm(temperature=0.0, max_retries=0)
    _tool_llm_box = [llm.bind_tools(all_tools)]

    def _rebuild_tool_llm():
        fresh = _build_groq_llm(temperature=0.0, max_retries=0)
        _tool_llm_box[0] = fresh.bind_tools(all_tools)
        return _tool_llm_box[0]

    system_prompt = (
        "Tu es un assistant IA interne spécialisé dans les données ERP Odoo. "
        "Utilise les outils disponibles pour interroger la base de données en temps réel et réponds avec les informations exactes retournées. "
        "Indique toujours la source exacte des données à la fin de ta réponse (ex: [Source: Odoo ERP - Module ...]). "
        "Rédige ta réponse exclusivement en Markdown (**gras**, listes \"- item\", etc.) -- n'utilise JAMAIS de balise HTML brute (<strong>, <br>, <div>...), le moteur d'affichage ne les rend pas et les afficherait telles quelles. "
        "Exemple de format attendu : **Chiffre d'affaires total** : 12 450€ [Source: Odoo ERP - Module Ventes]. Aucune balise HTML dans cet exemple."
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
            ai_msg, _wait = _invoke_with_rate_limit(
                _tool_llm_box[0], messages, rebuild_llm=_rebuild_tool_llm,
            )
            _llm_call_count += 1
        except Exception as e:
            _llm_call_count += 1  # attempt still counts against the LLM-call budget
            logger.warning("LLM invoke failed at iteration %d: %s", iteration + 1, e)

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
                            _t_hop = time.time()
                            observation = tool_map[fn_name].invoke(fn_args)
                            tool_observations.append(str(observation))
                            _trace_logger.log_hop(
                                trace_id=_trace_id, hop_index=_hop_index, tool_name=fn_name,
                                tool_args=fn_args, observation=str(observation),
                                elapsed_ms=(time.time() - _t_hop) * 1000,
                            )
                            _hop_index += 1
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

            _t_hop = time.time()
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
            _trace_logger.log_hop(
                trace_id=_trace_id, hop_index=_hop_index, tool_name=tool_name,
                tool_args=tool_args, observation=str(observation),
                elapsed_ms=(time.time() - _t_hop) * 1000,
            )
            _hop_index += 1
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
            _synth_llm_box = [_build_groq_llm(temperature=0.0, max_retries=0, max_tokens=512)]

            def _rebuild_synth_llm():
                _synth_llm_box[0] = _build_groq_llm(temperature=0.0, max_retries=0, max_tokens=512)
                return _synth_llm_box[0]

            final_resp, _wait3 = _invoke_with_rate_limit(
                _synth_llm_box[0], [HumanMessage(content=synthesis_prompt)],
                rebuild_llm=_rebuild_synth_llm,
            )
            _llm_call_count += 1
            final_answer = final_resp.content
        except Exception as e:
            _llm_call_count += 1
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
    timing["llm_call_count"] = _llm_call_count
    timing["hop_count"] = _hop_index
    _trace_logger.log_summary(
        trace_id=_trace_id, branch="donnees_erp", question=question,
        hop_count=_hop_index, llm_call_count=_llm_call_count,
        total_time_ms=timing["generation_time"] * 1000,
        hop_cap=REACT_RECURSION_LIMIT,
    )
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
    from config.settings import GROQ_MODEL
    
    combine_prompt = (
        f"Tu es l'agent de synthèse finale.\n"
        f"La question de l'utilisateur était : '{state['question']}'\n\n"
        f"Voici ce que l'agent de documentation a trouvé sur les procédures :\n{doc_answer}\n\n"
        f"Voici ce que l'agent des données ERP a trouvé dans les chiffres :\n{data_answer}\n\n"
        f"Combine ces deux informations pour faire une seule réponse cohérente et fluide, sans mentionner l'existence des agents.\n"
        f"Rédige exclusivement en Markdown (**gras**, listes \"- item\", etc.) -- aucune balise HTML brute (<strong>, <br>, <div>...), le moteur d'affichage ne les rend pas.\n"
        f"Exemple de format attendu :\n### Procédure et données\n\n1. **Étape** : description courte\n- Donnée associée : valeur\n\nAucune balise HTML dans cet exemple."
    )
    
    try:
        _combine_llm_box = [_build_groq_llm(temperature=0.3, max_retries=0, max_tokens=1024)]

        def _rebuild_combine_llm():
            _combine_llm_box[0] = _build_groq_llm(temperature=0.3, max_retries=0, max_tokens=1024)
            return _combine_llm_box[0]

        final_resp, _wait4 = _invoke_with_rate_limit(
            _combine_llm_box[0], [HumanMessage(content=combine_prompt)],
            rebuild_llm=_rebuild_combine_llm,
        )
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

