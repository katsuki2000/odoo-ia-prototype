"""
rag/ci_agent_node.py

Code Intelligence agent node.

LangGraph ReAct agent for Odoo source-code and security analysis.
Uses the knowledge graph, business resolver, deterministic tools,
and authorization gating to answer governance/access/code questions.
"""

import json
import logging
import time
from typing import List, Optional, Any


from core.schemas import AssistantResponse, SourceReference
from core.routing import (
    RAGState, _is_out_of_scope, OUT_OF_SCOPE_ANSWER,
    _is_massive_extraction_request, _is_prompt_injection,
    
    REACT_RECURSION_LIMIT,
)
from core.llm_client import (
    get_chat_llm,
    invoke_with_rate_limit as _invoke_with_rate_limit,
)
from core.degenerate_guards import (
    _detect_any_degenerate_repetition,
    _strip_any_degenerate_repetition,
)
from code_intelligence.ci_graph_loader import get_code_intelligence_graph
from code_intelligence.business_resolver import resolve_business_term
from code_intelligence.ci_helpers import (
    CI_SYSTEM_PROMPT,
    CI_MAX_HOPS,
    _AMOUNT_PATTERN,
    _question_mentions_amount,
    _extract_amount,
    _extract_company_context,
    _infer_move_type_context,
    _question_is_approval_related,
    _question_is_access_related,
    _question_suggests_automation_bypass,
    _extract_required_groups,
    _flag_ungrounded_group_xmlids,
    _strip_core_only_group_mentions,
    _scoped_raw_tool_output,
    _extract_required_groups_for_amount,
    _backfill_missing_required_groups,
    _backfill_missing_security_lock_amount,
    _backfill_missing_trigger_condition_literals,
    _backfill_missing_hardcoded_id_literals,
    _backfill_link_guard_clarifications,
    _correct_can_view_amount_contradictions,
    _correct_security_lock_threshold_contradictions,
    _backfill_missing_can_view_amount_fact,
    _format_can_view_amount_fact,
    _rehydrate_sticky_concept,
    _rank_and_cap_resolved_models,
    _override_user_groups_arg,
    _strip_group_resolution_noise,
    _force_out_of_scope_model_answer,
    _force_dynamic_uncertainty_answer,
)

from code_intelligence.ci_override_cascade import (
    _backfill_missing_override_modules,
    _backfill_missing_override_chain_amount,
    _correct_override_cascade_contradictions,
    _backfill_missing_unguarded_super,
    _rank_and_cap_override_methods,
    _MAX_OVERRIDE_CASCADE_DISPATCH,
)

logger = logging.getLogger(__name__)


# ── Real Odoo group DB IDs -> xml_id resolution ──────────────────────────────
_GROUP_XMLID_CACHE: dict = {}
_ADMIN_RPC_CLIENT = None
_ADMIN_RPC_UID = None


def _get_admin_rpc_client():
    """Lazy singleton admin XML-RPC client + uid, reused across requests --
    pure static-metadata lookups only (group xml_id resolution), never used
    for anything requiring the actual requester's own rights."""
    global _ADMIN_RPC_CLIENT, _ADMIN_RPC_UID
    import sys
    g_mod = sys.modules.get("core.graph")
    target_client = getattr(g_mod, "_ADMIN_RPC_CLIENT", None) if g_mod is not None else _ADMIN_RPC_CLIENT
    target_uid = getattr(g_mod, "_ADMIN_RPC_UID", None) if g_mod is not None else _ADMIN_RPC_UID
    if target_client is not None:
        return target_client, target_uid

    if _ADMIN_RPC_CLIENT is None:
        from code_intelligence.odoo_rpc_client import OdooRpcClient
        client = OdooRpcClient()
        _ADMIN_RPC_UID = client.authenticate_admin()
        _ADMIN_RPC_CLIENT = client
        if g_mod is not None:
            g_mod._ADMIN_RPC_CLIENT = client
            g_mod._ADMIN_RPC_UID = _ADMIN_RPC_UID
    return _ADMIN_RPC_CLIENT, _ADMIN_RPC_UID


def _resolve_user_group_xmlids(group_ids) -> list:
    global _GROUP_XMLID_CACHE
    import sys
    g_mod = sys.modules.get("core.graph")
    cache = getattr(g_mod, "_GROUP_XMLID_CACHE", None) if g_mod is not None else _GROUP_XMLID_CACHE
    if cache is None:
        cache = _GROUP_XMLID_CACHE

    if not group_ids:
        return []

    uncached = [g for g in group_ids if g not in cache]
    if uncached:
        try:
            client, admin_uid = _get_admin_rpc_client()
            resolved = client.get_group_xmlids(admin_uid, uncached)
            cache.update(resolved)
            _GROUP_XMLID_CACHE.update(resolved)
        except Exception as e:
            logger.error(
                "Group ID -> xml_id resolution failed for %s: %s. "
                "These groups will be treated as unresolved (fail closed).",
                uncached, e,
            )

    return [cache[g] for g in group_ids if g in cache]


class CodeIntelligenceAgentRunner:
    def __init__(self, state: RAGState):
        self.state = state

    def run(self) -> dict:
        state = self.state
        import time
        import json as _json
        start_time = time.time()
        
        from langchain_core.messages import AIMessage, ToolMessage, SystemMessage, HumanMessage
        
        question = state.get("question", "").strip()
        chat_history = state.get("chat_history", [])
        logger.info("Node [code_intelligence_agent]: Starting ReAct loop for: %s", question)
        
        from code_intelligence.reasoning_trace_logger import ReasoningTraceLogger, new_trace_id
        _trace_id = new_trace_id()
        _trace_logger = ReasoningTraceLogger()
        _llm_call_count = 0
        _hop_index = 0
        
        if _is_out_of_scope(question):
            logger.info("Node [code_intelligence_agent]: Out of scope question.")
            response = AssistantResponse(
                answer=OUT_OF_SCOPE_ANSWER,
                sources=[],
                confidence=0.0,
            )
            timing = state.get("timing", {}).copy()
            timing["code_intelligence_time"] = time.time() - start_time
            _trace_logger.log_summary(
                trace_id=_trace_id, branch="code_intelligence", question=question,
                hop_count=0, llm_call_count=0, total_time_ms=timing["code_intelligence_time"] * 1000,
                hop_cap=CI_MAX_HOPS,
            )
            return {"response": response, "raw_answer": response.answer, "timing": timing}
        
        # J32-J33: Security & Massive Extraction Safeguards
        from config.settings import (
            MAX_MODELS_PER_QUERY,
            MASSIVE_EXTRACTION_REFUSAL_MSG,
            PROMPT_INJECTION_REFUSAL_MSG,
        )
        
        if _is_prompt_injection(question):
            logger.warning("Node [code_intelligence_agent]: Prompt injection attempt intercepted.")
            response = AssistantResponse(
                answer=PROMPT_INJECTION_REFUSAL_MSG,
                sources=[],
                confidence=0.0,
            )
            timing = state.get("timing", {}).copy()
            timing["code_intelligence_time"] = time.time() - start_time
            _trace_logger.log_summary(
                trace_id=_trace_id, branch="code_intelligence", question=question,
                hop_count=0, llm_call_count=0, total_time_ms=timing["code_intelligence_time"] * 1000,
                hop_cap=CI_MAX_HOPS,
            )
            return {"response": response, "raw_answer": response.answer, "timing": timing}
        
        if _is_massive_extraction_request(question):
            logger.warning("Node [code_intelligence_agent]: Massive extraction request intercepted.")
            response = AssistantResponse(
                answer=MASSIVE_EXTRACTION_REFUSAL_MSG,
                sources=[],
                confidence=0.0,
            )
            timing = state.get("timing", {}).copy()
            timing["code_intelligence_time"] = time.time() - start_time
            _trace_logger.log_summary(
                trace_id=_trace_id, branch="code_intelligence", question=question,
                hop_count=0, llm_call_count=0, total_time_ms=timing["code_intelligence_time"] * 1000,
                hop_cap=CI_MAX_HOPS,
            )
            return {"response": response, "raw_answer": response.answer, "timing": timing}
        
        # Initialize the knowledge graph and inject into tool wrappers
        G = get_code_intelligence_graph()
        from code_intelligence.ci_agent_tools import ALL_CI_TOOLS, set_graph_ref, set_llm_ref
        from code_intelligence.authorization_gate import gate_observation, OmittedItem
        set_graph_ref(G)
        
        resolved_user_group_xmlids = _resolve_user_group_xmlids(state.get("user_groups", []))
        if state.get("user_groups") and not resolved_user_group_xmlids:
            logger.warning(
                "Node [code_intelligence_agent]: none of the demandeur's %d group ID(s) "
                "resolved to an xml_id -- gating will fail closed for this request.",
                len(state["user_groups"]),
            )
        
        llm = get_chat_llm(
            temperature=0.0,
            max_retries=0,  # Let _invoke_with_rate_limit handle dynamic header backoff
            max_tokens=1024,
            model_kwargs={"parallel_tool_calls": False},
        )
        set_llm_ref(llm)
        llm_with_tools = llm.bind_tools(ALL_CI_TOOLS)
        
        _ci_groq_wait = 0.0          # accumulated Groq rate-limit wait (subtracted from wall-clock)
        _ci_per_hop_times: list = []  # per-hop wall-clock durations
        
        # Business Term Resolver -- Map natural language concepts to technical Odoo models/modules
        _t_resolver = time.perf_counter()
        concept = resolve_business_term(question, G, llm=llm)
        _ci_resolver_time = time.perf_counter() - _t_resolver
        if concept.source_step == "llm_arbitration":
            _llm_call_count += 1 
        _concept_resolved_before_rehydration = concept.is_resolved
        concept = _rehydrate_sticky_concept(concept, state)
        from core.evidence_check import check_evidence
        evidence_status = check_evidence(concept, _concept_resolved_before_rehydration, state)
        logger.info("Node [code_intelligence_agent]: H3 evidence_status=%s", evidence_status)
        
        if concept.resolved_models and len(concept.resolved_models) > MAX_MODELS_PER_QUERY:
            concept.resolved_models = _rank_and_cap_resolved_models(
                question, concept.resolved_models, MAX_MODELS_PER_QUERY,
            )
        
        tool_observations: list = []
        tool_observation_models: list = []
        omitted_items: list = []  # OmittedForAuthorization entries
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
        if concept.is_resolved and concept.resolved_models:
            from code_intelligence.ci_agent_tools import find_security_lock_source_files
            tool_map = {t.name: t for t in ALL_CI_TOOLS}
            lock_tool = tool_map.get("analyze_security_locks")
            if lock_tool is not None:
                for target_model in concept.resolved_models:
                    if not find_security_lock_source_files(G, target_model):
                        continue  # structural guard: nothing to say, skip silently
                    call_key = ("analyze_security_locks", target_model)
                    if call_key in seen_calls:
                        continue
                    _t_hop = time.perf_counter()
                    try:
                        forced_observation = str(lock_tool.invoke({"model_name": target_model}))
                        if len(forced_observation) > 3000:
                            forced_observation = forced_observation[:3000] + "\n[... Content truncated for LLM context limit ...]"
                        forced_observation, omitted_list = gate_observation(
                            tool_name="analyze_security_locks",
                            model_name=target_model,
                            observation=forced_observation,
                            G=G,
                            user_groups=resolved_user_group_xmlids,
                        )
                        omitted_items.extend(omitted_list)
                        tool_observations.append(forced_observation)
                        tool_observation_models.append(target_model)
                        hop_count += 1
                        seen_calls.add(call_key)
                        _trace_logger.log_hop(
                            trace_id=_trace_id, hop_index=_hop_index,
                            tool_name="analyze_security_locks", tool_args={"model_name": target_model},
                            observation=forced_observation, elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                        )
                        _hop_index += 1
                        logger.info(
                            "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                            "'analyze_security_locks' for model '%s' (structural lock finding present).",
                            target_model,
                        )
                    except Exception as te:
                        logger.error("Deterministic analyze_security_locks dispatch failed: %s", te)
                if any(k[0] == "analyze_security_locks" for k in seen_calls):
                    system_prompt += (
                        "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                        "analyze_security_locks has already been run for the target model(s) above "
                        "because the question is approval/security-related; its output is already included "
                        "in the tool observations. Do not call it again -- focus any further tool calls on "
                        "what it does NOT cover (e.g. ir.rule / group-based record visibility via "
                        "evaluate_record_rules)."
                    )
        
        if (
            concept.is_resolved
            and concept.resolved_models
            and _question_suggests_automation_bypass(question)
        ):
            from code_intelligence.ci_agent_tools import find_server_action_nodes
            tool_map = {t.name: t for t in ALL_CI_TOOLS}
            sa_tool = tool_map.get("analyze_server_actions")
            if sa_tool is not None:
                for target_model in concept.resolved_models:
                    if not find_server_action_nodes(G, target_model):
                        continue  # structural guard: nothing to say, skip silently
                    call_key = ("analyze_server_actions", target_model)
                    if call_key in seen_calls:
                        continue
                    _t_hop = time.perf_counter()
                    try:
                        forced_observation = str(sa_tool.invoke({"model_name": target_model}))
                        if len(forced_observation) > 3000:
                            forced_observation = forced_observation[:3000] + "\n[... Content truncated for LLM context limit ...]"
                        forced_observation, omitted_list = gate_observation(
                            tool_name="analyze_server_actions",
                            model_name=target_model,
                            observation=forced_observation,
                            G=G,
                            user_groups=resolved_user_group_xmlids,
                        )
                        omitted_items.extend(omitted_list)
                        tool_observations.append(forced_observation)
                        tool_observation_models.append(target_model)
                        hop_count += 1
                        seen_calls.add(call_key)
                        _trace_logger.log_hop(
                            trace_id=_trace_id, hop_index=_hop_index,
                            tool_name="analyze_server_actions", tool_args={"model_name": target_model},
                            observation=forced_observation, elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                        )
                        _hop_index += 1
                        logger.info(
                            "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                            "'analyze_server_actions' for model '%s' (automation/bypass "
                            "wording + ServerAction nodes present).",
                            target_model,
                        )
                    except Exception as te:
                        logger.error("Deterministic analyze_server_actions dispatch failed: %s", te)
                if any(k[0] == "analyze_server_actions" for k in seen_calls):
                    system_prompt += (
                        "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                        "analyze_server_actions has already been run for the target model(s) "
                        "above because the question suggests automation/bypass logic; its output "
                        "is already included in the tool observations. Do not call it again."
                    )
        if (
            concept.is_resolved
            and concept.resolved_models
            and _question_is_approval_related(question)
        ):
            from code_intelligence.ci_agent_tools import find_methods_with_override_cascade
            from code_intelligence.method_override_resolver import find_methods_with_override_risk_findings
            tool_map = {t.name: t for t in ALL_CI_TOOLS}
            override_tool = tool_map.get("analyze_method_override_chain")
            if override_tool is not None:
                for target_model in concept.resolved_models:
                    candidate_methods = find_methods_with_override_cascade(G, target_model)
                    flagged_methods = find_methods_with_override_risk_findings(G, target_model, candidate_methods)
                    flagged_methods = _rank_and_cap_override_methods(question, flagged_methods)
                    for method_name in flagged_methods:
                        call_key = ("analyze_method_override_chain", target_model, method_name)
                        if call_key in seen_calls:
                            continue
                        _t_hop = time.perf_counter()
                        try:
                            forced_observation = str(override_tool.invoke({
                                "model_name": target_model, "method_name": method_name,
                            }))
                            if len(forced_observation) > 2200:
                                forced_observation = forced_observation[:2200] + "\n[... Content truncated for LLM context limit ...]"
                            forced_observation, omitted_list = gate_observation(
                                tool_name="analyze_method_override_chain",
                                model_name=target_model,
                                observation=forced_observation,
                                G=G,
                                user_groups=resolved_user_group_xmlids,
                            )
                            omitted_items.extend(omitted_list)
                            tool_observations.append(forced_observation)
                            tool_observation_models.append(target_model)
                            hop_count += 1
                            seen_calls.add(call_key)
                            _trace_logger.log_hop(
                                trace_id=_trace_id, hop_index=_hop_index,
                                tool_name="analyze_method_override_chain",
                                tool_args={"model_name": target_model, "method_name": method_name},
                                observation=forced_observation, elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                            )
                            _hop_index += 1
                            logger.info(
                                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                                "'analyze_method_override_chain' for '%s.%s' (approval wording "
                                "+ real override cascade present).",
                                target_model, method_name,
                            )
                        except Exception as te:
                            logger.error("Deterministic analyze_method_override_chain dispatch failed: %s", te)
                if any(k[0] == "analyze_method_override_chain" for k in seen_calls):
                    system_prompt += (
                        "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                        "analyze_method_override_chain has already been run for the "
                        "overridden method(s) above because the question is approval-related "
                        "and a real override cascade exists on the target model; its output is "
                        "already included in the tool observations. Do not call it again -- if "
                        "it flagged an unguarded super() OR an unchecked relational-field chain "
                        "(CHAINE RELATIONNELLE NON VERIFIEE), that finding takes precedence over "
                        "any single-module reading of the method. A relational-chain finding "
                        "often names a SECOND threshold/condition (e.g. a higher amount that "
                        "triggers an additional module's override on top of the first module's "
                        "rule) -- when the question's stated amount clears both thresholds, both "
                        "must be reported together, not only the first one encountered."
                    )
        
        if concept.is_resolved and concept.resolved_models and _question_is_access_related(question):
            tool_map = {t.name: t for t in ALL_CI_TOOLS}
            acl_tool = tool_map.get("who_has_access_to")
            if acl_tool is not None:
                skipped_lock_governed_models: List[str] = []
                for target_model in concept.resolved_models:
                    if ("analyze_security_locks", target_model) in seen_calls:
                        logger.info(
                            "Node [code_intelligence_agent]: skipping deterministic "
                            "who_has_access_to dispatch for '%s' -- a real Python security "
                            "lock (has_group()) already governs this model's actions, "
                            "more specific than the generic CRUD ACL matrix.",
                            target_model,
                        )
                        skipped_lock_governed_models.append(target_model)
                        continue
                    call_key = ("who_has_access_to", target_model)
                    if call_key in seen_calls:
                        continue
                    _t_hop = time.perf_counter()
                    try:
                        forced_observation = str(acl_tool.invoke({
                            "model_name": target_model, "permission": "all",
                        }))
                        if len(forced_observation) > 3000:
                            forced_observation = forced_observation[:3000] + "\n[... Content truncated for LLM context limit ...]"
                        forced_observation, omitted_list = gate_observation(
                            tool_name="who_has_access_to",
                            model_name=target_model,
                            observation=forced_observation,
                            G=G,
                            user_groups=resolved_user_group_xmlids,
                        )
                        omitted_items.extend(omitted_list)
                        tool_observations.append(forced_observation)
                        tool_observation_models.append(target_model)
                        hop_count += 1
                        seen_calls.add(call_key)
                        _trace_logger.log_hop(
                            trace_id=_trace_id, hop_index=_hop_index,
                            tool_name="who_has_access_to", tool_args={"model_name": target_model, "permission": "all"},
                            observation=forced_observation, elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                        )
                        _hop_index += 1
                        logger.info(
                            "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                            "'who_has_access_to' for model '%s' (question asks who can/has the "
                            "right to do something).",
                            target_model,
                        )
                    except Exception as te:
                        logger.error("Deterministic who_has_access_to dispatch failed: %s", te)
                if any(k[0] == "who_has_access_to" for k in seen_calls):
                    system_prompt += (
                        "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                        "who_has_access_to has already been run for the target model(s) above "
                        "because the question asks who can/has the right to do something; its "
                        "ACL and record-rule output is already included in the tool "
                        "observations. Do not call it again."
                    )
                if skipped_lock_governed_models:
                    system_prompt += (
                        "\n\n[SCOPING NOTE -- who_has_access_to]\n"
                        "For the model(s) "
                        + ", ".join(skipped_lock_governed_models)
                        + ", a Python security lock (has_group()) already governs the "
                        "specific action this question asks about; that finding is already "
                        "included in the tool observations above and is the correct basis "
                        "for answering who can perform THIS action. If you call "
                        "who_has_access_to for this model anyway, its output answers a "
                        "DIFFERENT, broader question (generic read/write/create/unlink ACL "
                        "access to the model as a whole) -- do not use it to determine who "
                        "can perform the specific action asked about, and do not treat its "
                        "groups as alternative or additional authorities for that action. "
                        "Each has_group() threshold in the security lock finding is an "
                        "independent minimum-requirement gate ('this group is REQUIRED "
                        "above this amount', meaning members of this group ARE AUTHORIZED to "
                        "validate above this amount), not an exclusive authority tier or ceiling. "
                        "A lock whose threshold is higher than the asked amount (e.g. >100000€ when "
                        "asked about 60000€) does NOT apply to that amount and its group is not required."
                    )
        if concept.is_resolved and concept.resolved_models and _question_is_access_related(question):
            _amount_for_rules = _extract_amount(question)
            if _amount_for_rules is not None:
                from code_intelligence.ci_agent_tools import evaluate_rules_raw
                tool_map = {t.name: t for t in ALL_CI_TOOLS}
                rule_tool = tool_map.get("evaluate_record_rules")
                if rule_tool is not None:
                    for target_model in concept.resolved_models:
                        call_key = ("evaluate_record_rules", target_model)
                        if call_key in seen_calls:
                            continue
                        _t_hop = time.perf_counter()
                        try:
                            import json as _json_dispatch
                            _dispatch_groups = _json_dispatch.dumps(resolved_user_group_xmlids or [])
                            forced_observation = str(rule_tool.invoke({
                                "model_name": target_model,
                                "user_groups_json": _dispatch_groups,
                                "permission": "read",
                            }))
                            if len(forced_observation) > 3000:
                                forced_observation = forced_observation[:3000] + "\n[... Content truncated for LLM context limit ...]"
                            forced_observation, omitted_list = gate_observation(
                                tool_name="evaluate_record_rules",
                                model_name=target_model,
                                observation=forced_observation,
                                G=G,
                                user_groups=resolved_user_group_xmlids,
                            )
                            omitted_items.extend(omitted_list)
                            tool_observations.append(forced_observation)
                            tool_observation_models.append(target_model)
                            hop_count += 1
                            seen_calls.add(call_key)
        
                            # Now compute can_view_amount_v2 deterministic fact
                            try:
                                _dispatch_rule_result = evaluate_rules_raw(
                                    model_name=target_model,
                                    permission="read",
                                    user_groups_json=_dispatch_groups,
                                )
                                _dispatch_context = {"amount": _amount_for_rules}
                                _dispatch_context.update(_extract_company_context(question))
                                _dispatch_context.update(_infer_move_type_context(concept))
                                _dispatch_can_view, _dispatch_unresolved = (
                                    _dispatch_rule_result.can_view_amount_v2(_dispatch_context)
                                )
                                tool_observations.append(
                                    _format_can_view_amount_fact(
                                        _amount_for_rules, _dispatch_can_view, _dispatch_unresolved
                                    )
                                )
                                tool_observation_models.append(target_model)
                                logger.info(
                                    "Node [code_intelligence_agent]: Pre-dispatch "
                                    "can_view_amount_v2 fact for model=%s, amount=%.0f, "
                                    "result=%s, unresolved=%s, context=%s, "
                                    "global=%d, group=%d.",
                                    target_model, _amount_for_rules, _dispatch_can_view,
                                    _dispatch_unresolved, _dispatch_context,
                                    len(_dispatch_rule_result.applied_global_rules),
                                    len(_dispatch_rule_result.applied_group_rules),
                                )
                            except Exception as ve:
                                logger.error(
                                    "Pre-dispatch can_view_amount_v2 injection failed: %s", ve
                                )
        
                            _trace_logger.log_hop(
                                trace_id=_trace_id, hop_index=_hop_index,
                                tool_name="evaluate_record_rules",
                                tool_args={"model_name": target_model, "permission": "read"},
                                observation=forced_observation,
                                elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                            )
                            _hop_index += 1
                            logger.info(
                                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                                "'evaluate_record_rules' for model '%s' (access-related "
                                "question with amount=%.0f).",
                                target_model, _amount_for_rules,
                            )
                        except Exception as te:
                            logger.error(
                                "Deterministic evaluate_record_rules dispatch failed: %s", te
                            )
                    if any(k[0] == "evaluate_record_rules" for k in seen_calls):
                        system_prompt += (
                            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                            "evaluate_record_rules has already been run for the target "
                            "model(s) above and the can_view_amount_v2 deterministic fact has been "
                            "injected. Do not call evaluate_record_rules again."
                        )
        messages = [
            SystemMessage(content=system_prompt),
            *chat_history[-6:],
            HumanMessage(content=question),
        ]
        
        if tool_observations:
            final_answer = _force_dynamic_uncertainty_answer(question, "\n\n".join(tool_observations))
        
        _t_react_loop = time.perf_counter()
        for iteration in range(0 if final_answer else REACT_RECURSION_LIMIT):
            # Single-Pass Composite Execution: 1 Tool Selection turn + 1 Synthesis turn
            try:
                ai_msg, _wait = _invoke_with_rate_limit(llm_with_tools, messages)
                _llm_call_count += 1  # tool-selection call
                _ci_groq_wait += _wait
            except Exception as e:
                _llm_call_count += 1  # attempt still counts against the LLM-call budget
                logger.error("LLM tool selection failed: %s", e)
                ai_msg = None
        
            if ai_msg and getattr(ai_msg, "tool_calls", None):
                messages.append(ai_msg)
                for tool_call in ai_msg.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]
                    tool_id = tool_call["id"]

                    if tool_name == "who_has_access_to" and "permission" not in tool_args:
                        tool_args["permission"] = "all"
        
                    tool_args = _override_user_groups_arg(tool_name, tool_args, resolved_user_group_xmlids)
        
                    logger.info("Node [code_intelligence_agent]: Single-Dispatch invoking '%s' with args %s", tool_name, tool_args)
                    tool_map = {t.name: t for t in ALL_CI_TOOLS}
                    if tool_name not in tool_map:
 
                        logger.warning(
                            "Node [code_intelligence_agent]: LLM requested unknown tool '%s'.",
                            tool_name,
                        )
                        messages.append(ToolMessage(
                            content=f"Outil '{tool_name}' non disponible.",
                            tool_call_id=tool_id,
                        ))
                    if tool_name in tool_map:
                        _t_hop = time.perf_counter()  # per-hop timing
                        try:
                            observation = str(tool_map[tool_name].invoke(tool_args))
 
                            _observation_cap = (
                                2200 if tool_name == "analyze_method_override_chain"
                                else 3000 if tool_name == "analyze_server_actions"
                                else 1200
                            )
                            if len(observation) > _observation_cap:
                                observation = observation[:_observation_cap] + "\n[... Content truncated for LLM context limit ...]"
        
                            rule_result = None
                            if tool_name == "evaluate_record_rules":
                                try:
                                    from code_intelligence.ci_agent_tools import evaluate_rules_raw
        
                                    rule_result = evaluate_rules_raw(
                                        model_name=tool_args.get("model_name", ""),
                                        permission=tool_args.get("permission", "read"),
                                        user_groups_json=tool_args.get("user_groups_json", "[]"),
                                    )
                                except Exception as ve:
                                    logger.error("evaluate_rules_raw computation failed: %s", ve)
        

                            observation, omitted_list = gate_observation(
                                tool_name=tool_name,
                                model_name=tool_args.get("model_name", ""),
                                observation=observation,
                                G=G,
                                user_groups=resolved_user_group_xmlids,
                                rule_result=rule_result,
                            )
                            omitted_items.extend(omitted_list)
        
                            tool_observations.append(observation)
                            tool_observation_models.append(tool_args.get("model_name", ""))

                            messages.append(ToolMessage(content=observation, tool_call_id=tool_id))
                            _ci_per_hop_times.append(time.perf_counter() - _t_hop)  # J30-J31
                            hop_count += 1

                            _trace_logger.log_hop(
                                trace_id=_trace_id, hop_index=_hop_index, tool_name=tool_name,
                                tool_args=tool_args, observation=observation,
                                elapsed_ms=_ci_per_hop_times[-1] * 1000,
                            )
                            _hop_index += 1
        

                            if hop_count >= CI_MAX_HOPS:
                                logger.warning(
                                    "Node [code_intelligence_agent]: CI_MAX_HOPS (%d) "
                                    "reached -- breaking ReAct loop.", CI_MAX_HOPS,
                                )
                                break
        
                            if tool_name == "evaluate_record_rules" and rule_result is not None:
                                amount = _extract_amount(question)
                                if amount is not None:
                                    try:
                                        context = {"amount": amount}
                                        context.update(_extract_company_context(question))
                                        context.update(_infer_move_type_context(concept))
                                        can_view, unresolved_fields = rule_result.can_view_amount_v2(
                                            context
                                        )
                                        tool_observations.append(
                                            _format_can_view_amount_fact(amount, can_view, unresolved_fields)
                                        )
                                        tool_observation_models.append(tool_args.get("model_name", ""))
                                        logger.info(
                                            "Node [code_intelligence_agent]: Injected deterministic "
                                            "can_view_amount_v2 fact for model=%s, amount=%.0f, "
                                            "result=%s, unresolved=%s, context=%s, "
                                            "global_rules_applied=%d, group_rules_applied=%d.",
                                            tool_args.get("model_name", ""), amount, can_view,
                                            unresolved_fields, context,
                                            len(rule_result.applied_global_rules),
                                            len(rule_result.applied_group_rules),
                                        )
                                    except Exception as ve:
                                        logger.error(
                                            "Deterministic can_view_amount injection failed: %s", ve
                                        )
                        except Exception as te:
                            logger.error("Tool execution failed (%s): %s", tool_name, te)
                            _error_observation = f"Error executing {tool_name}: {str(te)}"
                            tool_observations.append(_error_observation)
                            tool_observation_models.append(tool_args.get("model_name", ""))
                            # ReAct-loop fix: surface the failure to the LLM
                            # too, so it doesn't blindly repeat the exact same
                            # failing call on the next iteration.
                            messages.append(ToolMessage(content=_error_observation, tool_call_id=tool_id))
            elif ai_msg and ai_msg.content:
                final_answer = ai_msg.content
        
            # Synthesize clean final answer from composite tool output
            if not final_answer:
                if tool_observations:
                    # Q6.1 fix: strip 'could not be resolved' noise from
                    # who_has_access_to before it reaches the synthesis LLM when
                    # the real-auth override has already injected the
                    # demandeur's real groups into evaluate_record_rules
                    # and a deterministic can_view_amount fact is present.
                    tool_observations, tool_observation_models = _strip_group_resolution_noise(
                        tool_observations, resolved_user_group_xmlids, tool_observation_models,
                    )
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
                        f"one; attribute each finding only to its own source. Some observations "
                        f"carry an explicit confidence tag literally present in their source text "
                        f"(e.g. '[Confiance: FAIBLE]', '[Confiance: HIGH]') -- for those, copy the "
                        f"exact tag text verbatim next to the finding it qualifies; never translate, "
                        f"abbreviate, or paraphrase HIGH/MEDIUM/LOW/FAIBLE. Observations with NO "
                        f"such tag in their source text (e.g. ir.rule / evaluate_record_rules "
                        f"output, resolved model listings) are deterministic facts -- NEVER invent, "
                        f"infer, or add a confidence tag to them. Presenting a deterministic fact as "
                        f"if it carried a confidence level is itself a fabrication. "
                        f"If a [FAIT DÉTERMINISTIQUE] observation is present, it is the "
                        f"authoritative verdict on the user's access for the stated amount -- "
                        f"never recompute or contradict it, and do NOT mention, paraphrase, or "
                        f"allude to any 'could not be resolved' message from a different tool "
                        f"about group identifiers; those are obsolete artifacts of an earlier "
                        f"resolution step and have been superseded by the deterministic "
                        f"evaluation. If that verdict says the engine CANNOT determine access "
                        f"(an indeterminate/'ind\u00e9termin\u00e9' result, listing which condition(s) "
                        f"could not be resolved), you MUST report that uncertainty explicitly and "
                        f"MUST NOT state or imply that access is allowed or denied -- do not round "
                        f"an indeterminate verdict to a yes/no answer. This verdict is a CONCLUSION, not an explanation: you MUST "
                        f"still explain WHY in your answer, using the applicable and ignored rule "
                        f"names/domain_force from the OTHER observations in this same response "
                        f"(e.g. an unconditional group rule that outweighs a capped one via OR, "
                        f"or -- when no group rule applies at all -- the remaining global rule that "
                        f"carries no amount condition). Never quote or restate the bracketed "
                        f"'[FAIT DÉTERMINISTIQUE]' label or the mechanism name "
                        f"'evaluate_record_rules.can_view_amount' itself as if that were "
                        f"the explanation -- it is internal bookkeeping, not user-facing reasoning. "
                        f"Any file citation you make MUST keep its exact line range from the "
                        f"source observation (file:///path#L12-L25) -- never drop the line range "
                        f"even when shortening a citation. Any rule/action/group xml_id you cite "
                        f"as a sourcing claim MUST be prefixed 'xml_id: module.identifier', copied "
                        f"verbatim from the source observation. "
                        f"If an observation contains 'SUPER() NON GARDÉ', it means a conditional "
                        f"exemption in one module can be silently nullified by an unconditional "
                        f"super() call re-applying the parent module's logic -- this is the ACTUAL "
                        f"real-world behavior, more authoritative than a single module's lock message "
                        f"read in isolation. When both are present, lead the answer with what the "
                        f"override-chain finding says actually happens, not with the base module's "
                        f"lock message alone -- do not present the base module's rule as the answer "
                        f"while ignoring a SUPER() NON GARDÉ finding on the same method. "
                        f"If an observation contains 'CHAINE RELATIONNELLE NON VÉRIFIÉE', it "
                        f"describes a SECOND, ADDITIONAL threshold/condition from a different "
                        f"override module on top of whatever the base module's lock message already "
                        f"said (e.g. base module: >5000€ needs manager approval; override module: "
                        f">20000€ ALSO triggers director notification, with a real risk it silently "
                        f"fails if the hierarchy chain is incomplete) -- when the amount in the "
                        f"Original Question clears BOTH thresholds, report BOTH levels explicitly as "
                        f"a cascade, including the relational-chain risk verbatim; never report only "
                        f"the first (lowest) threshold and drop the second. "
                        f"When an observation names a chain of override modules (e.g. 'Cha\u00eene de "
                        f"surcharge de ... (N modules ...)'), the list of modules and their line "
                        f"ranges in that observation is EXHAUSTIVE and CLOSED -- never add a module, "
                        f"file path, or line range that is not copied verbatim from that observation, "
                        f"even to make the pattern look complete or consistent with the others; if "
                        f"you are unsure whether a module belongs, omit it rather than invent one. "
                        f"When a finding includes a literal condition or field name in backticks "
                        f"(e.g. `rec.partner_id.avoir_vip_exempt`, `rec.amount_total > 20000`), copy "
                        f"that literal verbatim in your answer -- do not paraphrase it away into a "
                        f"generic phrase like 'a conditional branch'. If a module listed in an "
                        f"override chain has NO \u26a0\ufe0f warning attached to it in the observation, state "
                        f"explicitly that no risk pattern was detected for that module by this "
                        f"heuristic -- never invent a risk finding to fill that gap. "
                        f"If the Original Question above asks about more than one condition or "
                        f"threshold (e.g. 'qui peut valider X, et y a-t-il une restriction "
                        f"supplémentaire au-delà de Y ?'), answer EACH part explicitly and "
                        f"separately -- never answer only the first part and silently imply 'no' "
                        f"for the rest. When an observation's 'Messages de verrous' section lists "
                        f"more than one message, treat each one as a DISTINCT finding to report -- "
                        f"do not summarize or select only one of them; a second or third message in "
                        f"that list is exactly as authoritative as the first. When the question "
                        f"asks who can validate/approve an operation for a specific monetary amount, "
                        f"evaluate each lock message condition against that specific amount: a lock "
                        f"whose threshold is exceeded (e.g. >50000€ for a 60000€ document) is triggered "
                        f"and requires the specified group (meaning members of that group ARE AUTHORIZED to "
                        f"validate above that amount, and the threshold is a minimum floor where their authority "
                        f"is required, NOT an upper ceiling where their authority ends). A lock whose threshold "
                        f"is NOT reached (e.g. >100000€ for a 60000€ document) is not triggered, does not "
                        f"restrict that amount, and its group is NOT required for that amount."
                    )
                    try:
                        plain_llm = get_chat_llm(
                            temperature=0.0, max_retries=0, max_tokens=4096,
                            model_kwargs={"frequency_penalty": 0.3, "presence_penalty": 0.2},
                        )
                        _t_synthesis = time.perf_counter()
                        final_resp, _synth_wait = _invoke_with_rate_limit(plain_llm, [HumanMessage(content=synthesis_prompt)])
                        _llm_call_count += 1  # synthesis call
                        _ci_groq_wait += _synth_wait
                        final_answer = final_resp.content
                        _ci_synthesis_time = time.perf_counter() - _t_synthesis
                        if _detect_any_degenerate_repetition(final_answer):
                            logger.warning(
                                "Node [code_intelligence_agent]: degenerate repetition detected in "
                                "synthesis output (%d chars) -- retrying once with an explicit "
                                "anti-repetition instruction before falling back to stripping it.",
                                len(final_answer),
                            )
                            retry_messages = [
                                HumanMessage(content=synthesis_prompt),
                                SystemMessage(content=(
                                    "RAPPEL STRICT : ta r\u00e9ponse pr\u00e9c\u00e9dente contenait une "
                                    "r\u00e9p\u00e9tition d\u00e9g\u00e9n\u00e9r\u00e9e (le m\u00eame mot ou groupe "
                                    "de mots r\u00e9p\u00e9t\u00e9 des dizaines de fois de suite). Ne r\u00e9p\u00e8te "
                                    "JAMAIS un mot ou groupe de mots plus de 2-3 fois de suite. Si tu "
                                    "n'as rien de nouveau \u00e0 dire sur un point, passe au suivant ou "
                                    "termine ta phrase."
                                )),
                            ]
                            try:
                                retry_resp, _retry_wait = _invoke_with_rate_limit(plain_llm, retry_messages, max_retries=2)
                                _llm_call_count += 1  # J46-J48: anti-repetition retry call
                                _ci_groq_wait += _retry_wait
                                if not _detect_any_degenerate_repetition(retry_resp.content):
                                    final_answer = retry_resp.content
                                else:
                                    logger.error(
                                        "Node [code_intelligence_agent]: synthesis still degenerate "
                                        "after retry -- stripping the repeated run instead of shipping it."
                                    )
                                    final_answer = _strip_any_degenerate_repetition(final_answer)
                            except Exception as retry_e:
                                logger.error("Anti-repetition retry failed: %s", retry_e)
                                final_answer = _strip_any_degenerate_repetition(final_answer)
                    except Exception as e:
                        logger.error("Synthesis failed: %s", e)
                        final_answer = "\n\n".join(tool_observations)
                else:
                    final_answer = "Je n'ai pas de données disponibles dans le graphe de connaissances pour répondre à cette question."
        
            if final_answer:
                break
        
        raw_tool_output = "\n\n".join(tool_observations)
        out_of_scope_model_answer = _force_out_of_scope_model_answer(question, concept)
        dynamic_uncertainty_answer = _force_dynamic_uncertainty_answer(question, raw_tool_output)
        if out_of_scope_model_answer:
            final_answer = out_of_scope_model_answer
        elif dynamic_uncertainty_answer:
            final_answer = dynamic_uncertainty_answer
        else:

            scoped_tool_output = _scoped_raw_tool_output(
                tool_observations, tool_observation_models, concept.resolved_models,
            )

            final_answer = _correct_security_lock_threshold_contradictions(final_answer, scoped_tool_output, question)

            final_answer = _backfill_missing_can_view_amount_fact(final_answer, scoped_tool_output)

            final_answer = _backfill_missing_required_groups(final_answer, scoped_tool_output, question)

            final_answer = _backfill_missing_security_lock_amount(final_answer, scoped_tool_output, question=question)

            final_answer = _backfill_missing_override_modules(final_answer, scoped_tool_output)

            final_answer = _correct_override_cascade_contradictions(final_answer, scoped_tool_output)
            final_answer = _backfill_missing_override_chain_amount(final_answer, scoped_tool_output)

            final_answer = _backfill_missing_trigger_condition_literals(final_answer, scoped_tool_output)
 
            final_answer = _backfill_missing_hardcoded_id_literals(final_answer, scoped_tool_output)
 
 
            final_answer = _backfill_missing_unguarded_super(final_answer, scoped_tool_output)
 
 
            final_answer = _backfill_link_guard_clarifications(final_answer, scoped_tool_output)
 
            final_answer = _correct_can_view_amount_contradictions(final_answer)

            final_answer = _flag_ungrounded_group_xmlids(final_answer, scoped_tool_output)
 
            final_answer = _strip_core_only_group_mentions(final_answer, scoped_tool_output)
        
        from code_intelligence.sourcing_guard import verify_citations, annotate_unverifiable_citations
        sourcing_result = verify_citations(final_answer, raw_tool_output)
        if not sourcing_result.is_fully_verified:
            logger.warning("Node [code_intelligence_agent]: Unverified citations -- %s", sourcing_result)
            final_answer = annotate_unverifiable_citations(final_answer, sourcing_result)
 
        if _detect_any_degenerate_repetition(final_answer):
            logger.error(
                "Node [code_intelligence_agent]: degenerate repetition detected in final_answer "
                "outside the main synthesis retry path -- stripping before returning."
            )
            final_answer = _strip_any_degenerate_repetition(final_answer)
        
        final_answer += "\n\n[Source: Graphe de Connaissances Code Intelligence]"
        

        from core.schemas import OmittedForAuthorization

        _seen_omitted_keys: set = set()
        deduped_omitted_items = []
        for _item in omitted_items:
            _key = (_item.label, _item.reason)
            if _key not in _seen_omitted_keys:
                _seen_omitted_keys.add(_key)
                deduped_omitted_items.append(_item)
        omitted_for_authorization = [
            OmittedForAuthorization(label=item.label, reason=item.reason)
            for item in deduped_omitted_items
        ]
        if omitted_for_authorization:
            omission_separator = chr(10)
            omission_lines = omission_separator.join(f"  - {o.label} : {o.reason}" for o in omitted_for_authorization)
            final_answer += (
                "\n\n\U0001F512 \u00c9L\u00c9MENT(S) OMIS POUR RAISON D'AUTORISATION:\n"
                + omission_lines
            )
        
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
            omitted_for_authorization=omitted_for_authorization,
        )
        
        _ci_total_wall = time.time() - start_time
        _ci_react_loop_time = time.perf_counter() - _t_react_loop if '_t_react_loop' in dir() else 0.0
        _ci_post_time = time.perf_counter() - (_t_react_loop + _ci_react_loop_time) if '_t_react_loop' in dir() else 0.0
        
        timing = state.get("timing", {}).copy()
        timing["code_intelligence_time"] = _ci_total_wall
        timing["ci_hop_count"] = hop_count
        timing["ci_groq_wait_time"] = round(_ci_groq_wait, 3)
        timing["ci_effective_time"] = round(_ci_total_wall - _ci_groq_wait, 3)
        timing["ci_business_resolver_time"] = round(_ci_resolver_time, 3) if '_ci_resolver_time' in dir() else 0.0
        timing["ci_per_hop_times"] = [round(t, 3) for t in _ci_per_hop_times]
        timing["ci_synthesis_time"] = round(_ci_synthesis_time, 3) if '_ci_synthesis_time' in dir() else 0.0
        timing["llm_call_count"] = _llm_call_count
        
        _trace_logger.log_summary(
            trace_id=_trace_id, branch="code_intelligence", question=question,
            hop_count=hop_count, llm_call_count=_llm_call_count,
            total_time_ms=_ci_total_wall * 1000, hop_cap=CI_MAX_HOPS,
        )
        
        return {
            "response": response,
            "raw_answer": final_answer,
            "timing": timing,
            "raw_tool_output": "\n\n".join(tool_observations),
            "evidence_status": evidence_status,
        }
                
def code_intelligence_agent(state: RAGState) -> dict:
    return CodeIntelligenceAgentRunner(state).run()
