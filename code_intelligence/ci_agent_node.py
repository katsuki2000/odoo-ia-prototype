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
    # 2026-08-20 fix: REACT_RECURSION_LIMIT is used directly below (the
    # ReAct loop's own iteration cap, distinct from CI_MAX_HOPS) but was
    # never re-imported here after the graph.py -> ci_agent_node.py split
    # -- NameError at call time, only on the path where no forced
    # pre-dispatch already produced a final_answer (found via a real
    # check_bloc9_01_credit_note_cascade_e2e.py run, 01a-business). Same
    # class of gap as the ci_override_cascade import already documented
    # above (missed re-export after the module split), not a new failure
    # mode.
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
    # _correct_override_cascade_contradictions intentionally NOT imported
    # from here -- see the rag.ci_override_cascade import block below
    # (2026-08-20 fix: ci_helpers.py's own copy of this function is a
    # stale duplicate left behind by the ci_override_cascade.py split,
    # calling _extract_override_modules which was never re-imported into
    # ci_helpers.py -- NameError at call time, found via pytest).
    _backfill_missing_can_view_amount_fact,
    _format_can_view_amount_fact,
    _rehydrate_sticky_concept,
    _rank_and_cap_resolved_models,
    _override_user_groups_arg,
    _strip_group_resolution_noise,
    _force_out_of_scope_model_answer,
    _force_dynamic_uncertainty_answer,
)

# ── Backward-compatible re-exports from ci_override_cascade ───────────────────
# 2026-08-20: relocated out of rag/ci_helpers.py -- see rag/ci_override_cascade.py's
# docstring. This module's import was not updated at the time, which broke the
# import chain for anything importing FROM this module (ImportError, found
# 2026-08-20 alongside the identical gap in rag/graph.py's own import block).
from code_intelligence.ci_override_cascade import (
    _backfill_missing_override_modules,
    _backfill_missing_override_chain_amount,
    _correct_override_cascade_contradictions,
    _backfill_missing_unguarded_super,
    _rank_and_cap_override_methods,
    _MAX_OVERRIDE_CASCADE_DISPATCH,
)

logger = logging.getLogger(__name__)


# ── Bloc 7 fix: real Odoo group DB IDs -> xml_id resolution ──────────────────
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
    """
    Bloc 7 fix: the demandeur's real Odoo groups arrive from the JWT as
    res.groups DATABASE IDs (see miro_ai/controllers/main.py:
    `groups = [g.id for g in user.groups_id]`), but the Code Intelligence
    graph identifies every group by its XML-ID (module.name), built
    statically from XML extraction. Without this translation,
    resolve_group_identifier() / _has_elevated_access() never match a real
    logged-in user against any group in the graph -- every real requester
    was silently treated as belonging to no group at all (found in review,
    J23-24). This affects both evaluer_regles_enregistrement's AND/OR
    engine (Bloc 1) and authorization_gate's elevated-access check (Bloc 7).

    Fails closed: any ID that can't be resolved (RPC error, group has no
    ir.model.data entry) is simply dropped, never guessed -- a missing
    group membership can only make gating MORE restrictive, never less.
    Locked by test_j23_24_group_id_xmlid_resolution.py.
    """
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
        """
        Node [code_intelligence_agent]: ReAct agent loop for Code Intelligence.
        
        C.1.1: LangGraph ReAct loop with 13 bound tools (5 composite + 4 auxiliary +
        4 code-analysis: analyser_verrous_securite, analyser_actions_serveur,
        analyser_contraintes_donnees, evaluer_regles_enregistrement).
        C.1.2: Anti-loop guard detects duplicate tool+args calls.
        C.1.3: System prompt enforces scope-first navigation strategy.
        C.1.4: Hop counter tracks tool calls; partial response on limit.
        """
        import time
        import json as _json
        start_time = time.time()
        
        from langchain_core.messages import AIMessage, ToolMessage, SystemMessage, HumanMessage
        
        question = state.get("question", "").strip()
        chat_history = state.get("chat_history", [])
        logger.info("Node [code_intelligence_agent]: Starting ReAct loop for: %s", question)
        
        # Bloc 12 / J46-J48: reasoning-trace + LLM-call-budget instrumentation.
        # "code_intelligence" is the most expensive branch to reason about --
        # this trace_id ties together every composite tool call this question
        # triggers (forced pre-dispatch + ReAct loop hops) so the full path is
        # readable post-hoc via ReasoningTraceLogger.read_trace(trace_id), and
        # llm_call_count is directly comparable to "documentaire"/"donnees_erp".
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
        
        # Bloc 7 fix: translate the demandeur's real Odoo group DB IDs to xml_id
        # strings ONCE for this question -- see _resolve_user_group_xmlids()
        # docstring. Every gating / evaluer_regles_enregistrement call below
        # must use this resolved list, never the raw state["user_groups"] ids.
        resolved_user_group_xmlids = _resolve_user_group_xmlids(state.get("user_groups", []))
        if state.get("user_groups") and not resolved_user_group_xmlids:
            logger.warning(
                "Node [code_intelligence_agent]: none of the demandeur's %d group ID(s) "
                "resolved to an xml_id -- gating will fail closed for this request.",
                len(state["user_groups"]),
            )
        
        # Bind tools to LLM (C.1.1)
        # 2026-08-14: routed through get_chat_llm() (rag/llm_client.py) instead
        # of ChatGroq(...) directly, so LLM_PROVIDER=openrouter (Qwen3-14B) can
        # be tested on this branch -- the one scripts/check_bloc9_*.py actually
        # exercises. See llm_client.py's module docstring for exact scope.
        llm = get_chat_llm(
            temperature=0.0,
            max_retries=0,  # Let _invoke_with_rate_limit handle dynamic header backoff
            max_tokens=1024,
            # ReAct-loop fix (part 2, post-Bloc-8 regression): force ONE tool
            # call per LLM turn. Without this, llama-3.1-8b-instant frequently
            # emits 3-4 tool_calls in a single ai_msg -- all chosen blind, in
            # one shot, before any observation exists yet (confirmed in the
            # J46-J48 reasoning traces: batches of hops land at the exact same
            # millisecond timestamp). That burns through CI_MAX_HOPS in one
            # breath and defeats the messages-accumulation fix above, since
            # there's no LLM call in between the wrong guesses for the model to
            # actually see and correct from. This is a standard OpenAI Chat
            # Completions body param (parallel_tool_calls, default true) --
            # both ChatGroq and ChatOpenAI (OpenRouter) pass unknown kwargs
            # straight through via model_kwargs (same mechanism already used
            # for frequency_penalty/presence_penalty on the synthesis LLM
            # below).
            model_kwargs={"parallel_tool_calls": False},
        )
        set_llm_ref(llm)
        llm_with_tools = llm.bind_tools(ALL_CI_TOOLS)
        
        # J30-J31: phase timing instrumentation
        _ci_groq_wait = 0.0          # accumulated Groq rate-limit wait (subtracted from wall-clock)
        _ci_per_hop_times: list = []  # per-hop wall-clock durations
        
        # Story S2.0: Business Term Resolver -- Map natural language concepts to technical Odoo models/modules
        _t_resolver = time.perf_counter()
        concept = resolve_business_term(question, G, llm=llm)
        _ci_resolver_time = time.perf_counter() - _t_resolver
        if concept.source_step == "llm_arbitration":
            _llm_call_count += 1  # bounded arbitration call inside resolve_business_term
        
        # H3 (2026-08-20, todo/contexte.txt): captured BEFORE rehydration --
        # see rag/evidence_check.py's check_evidence() docstring for why this
        # must be captured here and passed in explicitly (a successful fresh
        # resolution and a successful rehydration are indistinguishable from
        # concept.is_resolved alone once rehydration has already run).
        _concept_resolved_before_rehydration = concept.is_resolved
        
        # H1b-ii (todo/contexte.txt section 64/70, 2026-08-20): rehydrate a
        # sticky resolved_concept from route() when this branch's own
        # resolution failed -- see _rehydrate_sticky_concept's own docstring
        # in rag/ci_helpers.py (extracted there 2026-08-20 for unit testing,
        # tests/test_h1b_ii_sticky_concept.py) for the full rationale.
        concept = _rehydrate_sticky_concept(concept, state)
        
        # H3 (2026-08-20, todo/contexte.txt), Phase 1 -- observational only:
        # compute RESOLU/NON_RESOLU/CONFLIT and log it, but do NOT yet change
        # tool dispatch, system_prompt content, or gating based on it. See
        # rag/evidence_check.py's module docstring for the full design and why
        # this stays observation-only for now (same phasing discipline as H1's
        # own first step).
        from core.evidence_check import check_evidence
        evidence_status = check_evidence(concept, _concept_resolved_before_rehydration, state)
        logger.info("Node [code_intelligence_agent]: H3 evidence_status=%s", evidence_status)
        
        # J32-J33: Enforce MAX_MODELS_PER_QUERY limit on resolved models
        if concept.resolved_models and len(concept.resolved_models) > MAX_MODELS_PER_QUERY:
            # Bloc 9 gap fix (2026-08-11, bloc9-07c-sudo-scope-trap) -- ranked
            # by relevance to the question instead of an arbitrary slice, see
            # _rank_and_cap_resolved_models docstring for the live failure this
            # replaces.
            concept.resolved_models = _rank_and_cap_resolved_models(
                question, concept.resolved_models, MAX_MODELS_PER_QUERY,
            )
        
        tool_observations: list = []
        # Bloc 9 gap fix (2026-08-10, bloc9-05c-no-link-trap contamination):
        # index-aligned with tool_observations -- the model_name each
        # observation actually came from, or "" when unknown. See
        # _scoped_raw_tool_output for why this exists (deterministic backfills
        # must not mix facts across models the ReAct loop happened to visit
        # in the same turn).
        tool_observation_models: list = []
        omitted_items: list = []  # Bloc 7 (J23-24): OmittedForAuthorization entries
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
        
        # J8/J15: force analyser_verrous_securite when the question resolves to
        # a target model AND that model structurally has at least one Python
        # security-lock finding (find_security_lock_source_files). Only fires
        # when a model is actually available -- an unresolved concept is a Bloc 0
        # problem, not this one.
        #
        # 2026-08-10 (Bloc 9, module 5 gap): this used to be gated ADDITIONALLY
        # on _question_is_approval_related(question) -- but questions like
        # "pourquoi je n'arrive pas à démarrer..." or "la règle s'applique-t-elle
        # ..." (module 5, 05a/05c) contain none of that vocabulary, so the
        # forced dispatch silently never fired and the LLM picked its own tool,
        # badly (hallucinated a malformed method name instead of finding the
        # real Python lock). Every module has its own action vocabulary
        # ("démarrer", "soumettre", "rejeter"...) -- chasing keywords
        # per-module is the same whack-a-mole already abandoned for
        # find_server_action_nodes/find_methods_with_override_cascade below,
        # which lean on their structural guard instead. Dropped the keyword
        # gate entirely for THIS dispatch: unlike those two tools (genuinely
        # tangential to most questions), a Python security lock is central to
        # nearly every governance/access question about a model -- which is
        # exactly why J7/J8 exist (the LLM never reliably called this tool on
        # its own even with an explicit "ALWAYS invoke" directive in
        # CI_SYSTEM_PROMPT). Tradeoff accepted: this can now also fire on
        # questions unrelated to security that happen to resolve to a model
        # with a lock elsewhere in its source -- same "false positive costs
        # ~nothing" philosophy already accepted for the other two guards below,
        # and the static tool call itself is cheap (no LLM).
        if concept.is_resolved and concept.resolved_models:
            from code_intelligence.ci_agent_tools import find_security_lock_source_files
            tool_map = {t.name: t for t in ALL_CI_TOOLS}
            lock_tool = tool_map.get("analyser_verrous_securite")
            if lock_tool is not None:
                for target_model in concept.resolved_models:
                    if not find_security_lock_source_files(G, target_model):
                        continue  # structural guard: nothing to say, skip silently
                    call_key = ("analyser_verrous_securite", target_model)
                    if call_key in seen_calls:
                        continue
                    _t_hop = time.perf_counter()
                    try:
                        forced_observation = str(lock_tool.invoke({"model_name": target_model}))
                        # Bloc 9 gap, found 2026-08-11 (bloc9-01a-business rerun):
                        # analyser_verrous_securite aggregates EVERY source file
                        # touching the model (find_model_source_filepaths), sorted
                        # alphabetically -- on a heavily-shared model like
                        # account.move that can be a dozen+ per-file blocks. The
                        # generic 1200-char cap used by the other two forced
                        # dispatches (each scoped to a single file/method) was
                        # silently truncating this aggregated text well before
                        # reaching a fact from a file that happened to sort late
                        # -- confirmed live: the has_group()-derived required
                        # group for custom_credit_note_approval never appeared
                        # anywhere in tool_observations for the account.move
                        # question (not even via the _backfill_missing_required_
                        # groups deterministic backfill below, which reads
                        # straight from these observations and would have caught
                        # a synthesis-level drop but cannot recover a fact that
                        # was never in the text to begin with). Raised only for
                        # THIS forced dispatch, not the generic per-hop cap in the
                        # ReAct loop below or the other two forced dispatches,
                        # since only this one aggregates across a model's full
                        # file set.
                        if len(forced_observation) > 3000:
                            forced_observation = forced_observation[:3000] + "\n[... Content truncated for LLM context limit ...]"
                        # Bloc 7 (J23-24): generalized gating on this forced
                        # dispatch too -- it bypasses the normal ReAct tool
                        # loop, so it must be gated here explicitly rather than
                        # relying on the loop's gating below.
                        forced_observation, omitted_list = gate_observation(
                            tool_name="analyser_verrous_securite",
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
                            tool_name="analyser_verrous_securite", tool_args={"model_name": target_model},
                            observation=forced_observation, elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                        )
                        _hop_index += 1
                        logger.info(
                            "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                            "'analyser_verrous_securite' for model '%s' (structural lock finding present).",
                            target_model,
                        )
                    except Exception as te:
                        logger.error("Deterministic analyser_verrous_securite dispatch failed: %s", te)
                if any(k[0] == "analyser_verrous_securite" for k in seen_calls):
                    system_prompt += (
                        "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                        "analyser_verrous_securite has already been run for the target model(s) above "
                        "because the question is approval/security-related; its output is already included "
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
                    _t_hop = time.perf_counter()
                    try:
                        forced_observation = str(sa_tool.invoke({"model_name": target_model}))
                        # Bloc 9 gap fix (2026-08-13, module 6/8, bloc9-06b/06c):
                        # this dispatch aggregates EVERY ServerAction node on the
                        # target model (same shape as analyser_verrous_securite's
                        # forced dispatch above, which needed 3000 for the same
                        # reason) -- on account.move, 5 boilerplate "Aucun pattern
                        # de securite detecte" entries precede the one real
                        # finding (custom_automation_traps), pushing the real
                        # content (sudo()/hardcoded IDs/trigger condition) past
                        # the flat 1200 cap this dispatch never had raised, unlike
                        # its two siblings -- confirmed live: cut mid-word inside
                        # "sudo()" itself, before the hardcoded-IDs line or the
                        # trigger-condition line were ever stored, so neither the
                        # synthesis LLM nor _backfill_missing_trigger_condition_
                        # literals (which can only re-surface a fact already
                        # present in the stored observation) ever had a chance.
                        if len(forced_observation) > 3000:
                            forced_observation = forced_observation[:3000] + "\n[... Content truncated for LLM context limit ...]"
                        # Bloc 7 (J23-24): same rationale as the
                        # analyser_verrous_securite forced dispatch above --
                        # this bypasses the ReAct loop's gating, so gate here.
                        forced_observation, omitted_list = gate_observation(
                            tool_name="analyser_actions_serveur",
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
                            tool_name="analyser_actions_serveur", tool_args={"model_name": target_model},
                            observation=forced_observation, elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                        )
                        _hop_index += 1
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
        
        # Bloc 9 gap, found 2026-08-06 (Q1.2 "avoir VIP"): deterministic
        # pre-dispatch of analyser_chaine_surcharge_methode. Unlike the two
        # forced dispatches above, this tool needs a method_name, which never
        # appears in the natural-language question -- so the structural guard
        # (find_methods_with_override_cascade: does ANY method on the resolved
        # model actually have >1 override site in the graph?) is the PRIMARY
        # defense here, not a secondary one. That's what makes it safe to reuse
        # the already-broad _APPROVAL_PATTERN without repeating the Q6.2
        # false-positive regression the amount-only trigger caused earlier: on
        # a model with no real override cascade, a keyword false-positive costs
        # nothing (the guard returns [], nothing is dispatched).
        if (
            concept.is_resolved
            and concept.resolved_models
            and _question_is_approval_related(question)
        ):
            from code_intelligence.ci_agent_tools import find_methods_with_override_cascade
            from code_intelligence.method_override_resolver import find_methods_with_override_risk_findings
            tool_map = {t.name: t for t in ALL_CI_TOOLS}
            override_tool = tool_map.get("analyser_chaine_surcharge_methode")
            if override_tool is not None:
                for target_model in concept.resolved_models:
                    candidate_methods = find_methods_with_override_cascade(G, target_model)
                    # Second, cheaper filter (2026-08-06 fix): the cascade-only
                    # guard alone fires on every ordinary multiply-overridden
                    # method (write, create, action_post...) on a shared model
                    # like account.move -- confirmed to blow past CI_MAX_HOPS
                    # (17 hops on Q1.1/Q1.2/Q5.1) and to bury the real finding
                    # in noise. Only dispatch the full LLM-backed tool for
                    # methods where the cheap deterministic AST check already
                    # found something (unguarded-super OR, 2026-08-06 Bloc 9
                    # gap fix, an unchecked long relational-field chain --
                    # renamed find_methods_with_unguarded_super ->
                    # find_methods_with_override_risk_findings accordingly).
                    flagged_methods = find_methods_with_override_risk_findings(G, target_model, candidate_methods)
                    flagged_methods = _rank_and_cap_override_methods(question, flagged_methods)
                    for method_name in flagged_methods:
                        call_key = ("analyser_chaine_surcharge_methode", target_model, method_name)
                        if call_key in seen_calls:
                            continue
                        _t_hop = time.perf_counter()
                        try:
                            forced_observation = str(override_tool.invoke({
                                "model_name": target_model, "method_name": method_name,
                            }))
                            # Bloc 9 gap, found 2026-08-11 (bloc9-01a/01b rerun,
                            # AFTER both the cap=1 fix and the verrous_securite
                            # truncation fix above): a 3-module override chain
                            # (module header + per-module warning block, each
                            # with a file link and a full explanatory sentence)
                            # routinely exceeds 1200 chars on its own -- confirmed
                            # live by the raw check script's own direct call to
                            # this same tool, which prints ~1400+ chars for
                            # action_valider_avoir's real 3-module chain. Even
                            # with cap=1 correctly limiting to ONE forced
                            # dispatch, that single dispatch's own content was
                            # still being cut -- e.g. losing the regional
                            # module's 20000e relational-chain finding, or the
                            # base module's "no risk detected" closing line,
                            # depending on where in the chain the cut landed.
                            # Raised to 2200 (a single method's chain, capped at
                            # 1 dispatch, needs less headroom than the
                            # whole-model verrous_securite aggregation above,
                            # which can span a dozen+ files and was raised to
                            # 3000).
                            if len(forced_observation) > 2200:
                                forced_observation = forced_observation[:2200] + "\n[... Content truncated for LLM context limit ...]"
                            # Bloc 7 (J23-24): same rationale as the two forced
                            # dispatches above -- bypasses the ReAct loop's
                            # gating, so gate here explicitly.
                            forced_observation, omitted_list = gate_observation(
                                tool_name="analyser_chaine_surcharge_methode",
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
                                tool_name="analyser_chaine_surcharge_methode",
                                tool_args={"model_name": target_model, "method_name": method_name},
                                observation=forced_observation, elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                            )
                            _hop_index += 1
                            logger.info(
                                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                                "'analyser_chaine_surcharge_methode' for '%s.%s' (approval wording "
                                "+ real override cascade present).",
                                target_model, method_name,
                            )
                        except Exception as te:
                            logger.error("Deterministic analyser_chaine_surcharge_methode dispatch failed: %s", te)
                if any(k[0] == "analyser_chaine_surcharge_methode" for k in seen_calls):
                    system_prompt += (
                        "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                        "analyser_chaine_surcharge_methode has already been run for the "
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
        
        # Bloc 9 gap, found 2026-08-13 (native-Odoo-out-of-scope investigation --
        # see _question_is_access_related/_ACCESS_QUESTION_PATTERN above for
        # the full rationale): force qui_a_acces_a whenever the question asks
        # who can/has the right to do something and a model resolved. Unlike
        # the tools above, this is NOT additionally gated on a structural
        # guard -- ACL entries exist on nearly every real model, so the
        # question-shape keyword IS the meaningful filter here.
        #
        # 2026-08-13 (Bloc 9, module 8/8, bloc9-08a-business): that blanket
        # firing generalized badly onto a model that DOES have a Python
        # security lock. custom.deep.document's action_validate_level2()/
        # action_final_approve() are gated by has_group() in code, already
        # force-dispatched to analyser_verrous_securite above -- the DEFAULT
        # generic read/write/create/unlink ACL matrix is real data (_expand_
        # inheriting_acl_groups correctly walks the IMPLIES hierarchy: every
        # group that transitively implies base.group_user genuinely does have
        # base CRUD access) but answers a DIFFERENT question ("who can read/
        # write this model at all") than the one asked ("who can VALIDATE a
        # 60 000€ document", governed by the has_group() gate, not the CRUD
        # ACL). Confirmed live: qui_a_acces_a's permission='all' matrix (13 unrelated
        # groups -- hr, purchase, stock, hr_expense, hr_holidays...) got dumped
        # alongside the correct has_group() finding, and the small synthesis
        # LLM conflated the two, padding "who can validate" with groups that
        # only have generic read access. Same failure shape as module 1/8's
        # Gap (a): a forced dispatch built for the case where NO other
        # governing mechanism exists (the original out-of-scope fix's actual
        # target) generalizing onto a model where a MORE SPECIFIC mechanism
        # already answers the question. Skip qui_a_acces_a's forced dispatch
        # for a target_model that already got a real (structurally-guarded)
        # analyser_verrous_securite dispatch above -- the has_group() finding
        # IS the answer to "who can do this specific action" for that model;
        # the LLM can still call qui_a_acces_a itself if it genuinely needs the
        # generic ACL matrix too (e.g. a question that also asks about plain
        # read access), same as the other two structurally-guarded tools.
        if concept.is_resolved and concept.resolved_models and _question_is_access_related(question):
            tool_map = {t.name: t for t in ALL_CI_TOOLS}
            acl_tool = tool_map.get("qui_a_acces_a")
            if acl_tool is not None:
                # 2026-08-14 (Bloc 9, module 8/8, bloc9-08a-business, contexte.txt
                # section 46, root cause B): the skip below only prevents the
                # GUARANTEED forced dispatch -- it does not add call_key to
                # seen_calls, so the "Do not call it again" instruction further
                # down (gated on `any(k[0] == "qui_a_acces_a" for k in
                # seen_calls)`) never fires either. The free ReAct LLM is left
                # completely free to call qui_a_acces_a itself on this exact
                # model (confirmed live: reasoning_trace.jsonl hop 2, permission=
                # "write", not the forced-dispatch shape) and re-introduce the
                # same 13-group parasitic ACL matrix this skip-guard was built
                # to keep out of tool_observations. Deliberately not closing the
                # tool off (this skip's own docstring: "Rien n'est retire de la
                # boite a outils" -- the LLM may still genuinely need the ACL
                # matrix for a mixed question). Instead, track which models were
                # skipped so a scoping instruction can be added below regardless
                # of whether the LLM ends up calling the tool on its own.
                skipped_lock_governed_models: List[str] = []
                for target_model in concept.resolved_models:
                    if ("analyser_verrous_securite", target_model) in seen_calls:
                        logger.info(
                            "Node [code_intelligence_agent]: skipping deterministic "
                            "qui_a_acces_a dispatch for '%s' -- a real Python security "
                            "lock (has_group()) already governs this model's actions, "
                            "more specific than the generic CRUD ACL matrix.",
                            target_model,
                        )
                        skipped_lock_governed_models.append(target_model)
                        continue
                    call_key = ("qui_a_acces_a", target_model)
                    if call_key in seen_calls:
                        continue
                    _t_hop = time.perf_counter()
                    try:
                        forced_observation = str(acl_tool.invoke({
                            "model_name": target_model, "permission": "all",
                        }))
                        if len(forced_observation) > 3000:
                            forced_observation = forced_observation[:3000] + "\n[... Content truncated for LLM context limit ...]"
                        # Bloc 7 (J23-24): same rationale as the forced
                        # dispatches above -- bypasses the ReAct loop's gating,
                        # so gate here explicitly.
                        forced_observation, omitted_list = gate_observation(
                            tool_name="qui_a_acces_a",
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
                            tool_name="qui_a_acces_a", tool_args={"model_name": target_model, "permission": "all"},
                            observation=forced_observation, elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                        )
                        _hop_index += 1
                        logger.info(
                            "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                            "'qui_a_acces_a' for model '%s' (question asks who can/has the "
                            "right to do something).",
                            target_model,
                        )
                    except Exception as te:
                        logger.error("Deterministic qui_a_acces_a dispatch failed: %s", te)
                if any(k[0] == "qui_a_acces_a" for k in seen_calls):
                    system_prompt += (
                        "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                        "qui_a_acces_a has already been run for the target model(s) above "
                        "because the question asks who can/has the right to do something; its "
                        "ACL and record-rule output is already included in the tool "
                        "observations. Do not call it again."
                    )
                if skipped_lock_governed_models:
                    system_prompt += (
                        "\n\n[SCOPING NOTE -- qui_a_acces_a]\n"
                        "For the model(s) "
                        + ", ".join(skipped_lock_governed_models)
                        + ", a Python security lock (has_group()) already governs the "
                        "specific action this question asks about; that finding is already "
                        "included in the tool observations above and is the correct basis "
                        "for answering who can perform THIS action. If you call "
                        "qui_a_acces_a for this model anyway, its output answers a "
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
        
        # Bloc9 08c fix (2026-08-14): force evaluer_regles_enregistrement + the
        # can_view_amount_v2 deterministic fact when the question is access-
        # related AND contains a monetary amount AND a model is resolved.
        # Root cause confirmed by reproduction with logging: when the ReAct
        # LLM didn't choose to call evaluer_regles_enregistrement itself, the
        # can_view_amount_v2 code path (inside the ReAct loop's tool-call
        # handler, lines 4185-4244) was NEVER reached, and the synthesis LLM
        # hallucinated "can_view_amount() = True" from scratch. This dispatch
        # guarantees the tri-state fact is computed and injected into
        # tool_observations regardless of the ReAct LLM's tool selection.
        if concept.is_resolved and concept.resolved_models and _question_is_access_related(question):
            _amount_for_rules = _extract_amount(question)
            if _amount_for_rules is not None:
                from code_intelligence.ci_agent_tools import evaluer_regles_raw
                tool_map = {t.name: t for t in ALL_CI_TOOLS}
                rule_tool = tool_map.get("evaluer_regles_enregistrement")
                if rule_tool is not None:
                    for target_model in concept.resolved_models:
                        call_key = ("evaluer_regles_enregistrement", target_model)
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
                                tool_name="evaluer_regles_enregistrement",
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
                                _dispatch_rule_result = evaluer_regles_raw(
                                    model_name=target_model,
                                    permission="read",
                                    user_groups_json=_dispatch_groups,
                                )
                                _dispatch_context = {"amount": _amount_for_rules}
                                _dispatch_context.update(_extract_company_context(question))
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
                                    "global=%d, group=%d (Bloc9 08c deterministic fix).",
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
                                tool_name="evaluer_regles_enregistrement",
                                tool_args={"model_name": target_model, "permission": "read"},
                                observation=forced_observation,
                                elapsed_ms=(time.perf_counter() - _t_hop) * 1000,
                            )
                            _hop_index += 1
                            logger.info(
                                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                                "'evaluer_regles_enregistrement' for model '%s' (access-related "
                                "question with amount=%.0f, Bloc9 08c fix).",
                                target_model, _amount_for_rules,
                            )
                        except Exception as te:
                            logger.error(
                                "Deterministic evaluer_regles_enregistrement dispatch failed: %s", te
                            )
                    if any(k[0] == "evaluer_regles_enregistrement" for k in seen_calls):
                        system_prompt += (
                            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
                            "evaluer_regles_enregistrement has already been run for the target "
                            "model(s) above and the can_view_amount_v2 deterministic fact has been "
                            "injected. Do not call evaluer_regles_enregistrement again."
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
                _llm_call_count += 1  # J46-J48: tool-selection call
                _ci_groq_wait += _wait
            except Exception as e:
                _llm_call_count += 1  # attempt still counts against the LLM-call budget
                logger.error("LLM tool selection failed: %s", e)
                ai_msg = None
        
            if ai_msg and getattr(ai_msg, "tool_calls", None):
                # ReAct-loop fix (Bloc 12 review, post-Bloc-8 regression): feed
                # the AI's tool-call message and every resulting ToolMessage
                # back into `messages` so the NEXT iteration's LLM call actually
                # sees what was already tried and what came back (success or
                # failure). Previously `messages` was NEVER updated inside this
                # loop -- every iteration re-sent the exact same initial prompt
                # (system + history + question), so the model had zero memory of
                # its own prior tool calls within the same question. That's what
                # let it repeatedly re-guess wrong technical identifiers (e.g.
                # "demande_conge" instead of the already-confirmed "hr.leave",
                # or "group_region" instead of the real xml_id) across hops
                # instead of learning from the "not found" observation it had
                # just received one message ago. Mirrors what orm_agent_loop
                # (donnees_erp branch) already does correctly.
                messages.append(ai_msg)
                for tool_call in ai_msg.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]
                    tool_id = tool_call["id"]
        
                    # If qui_a_acces_a is called without explicit permission, default to 'all' for single-pass matrix
                    if tool_name == "qui_a_acces_a" and "permission" not in tool_args:
                        tool_args["permission"] = "all"
        
                    # Bloc 7 (J23-24) / real-auth fix: force the DEMANDEUR's real
                    # groups into evaluer_regles_enregistrement's args (see
                    # _override_user_groups_arg docstring). No-op for other tools.
                    tool_args = _override_user_groups_arg(tool_name, tool_args, resolved_user_group_xmlids)
        
                    logger.info("Node [code_intelligence_agent]: Single-Dispatch invoking '%s' with args %s", tool_name, tool_args)
                    tool_map = {t.name: t for t in ALL_CI_TOOLS}
                    if tool_name not in tool_map:
                        # ReAct-loop fix: this case was previously silently
                        # ignored (no observation, no ToolMessage) -- now that
                        # ai_msg + ToolMessages are fed back into `messages`,
                        # every tool_call MUST get a matching ToolMessage or the
                        # next LLM call can be rejected by the API for an
                        # orphaned tool_call_id.
                        logger.warning(
                            "Node [code_intelligence_agent]: LLM requested unknown tool '%s'.",
                            tool_name,
                        )
                        messages.append(ToolMessage(
                            content=f"Outil '{tool_name}' non disponible.",
                            tool_call_id=tool_id,
                        ))
                    if tool_name in tool_map:
                        _t_hop = time.perf_counter()  # J30-J31: per-hop timing
                        try:
                            observation = str(tool_map[tool_name].invoke(tool_args))
                            # Bloc 9 gap, found 2026-08-12 (module 1/8, bloc9-01b-
                            # technical live rerun): the generic 1200-char cap below
                            # is fine for most tools, but analyser_chaine_surcharge_
                            # methode's forced pre-dispatch already needed 2200 (see
                            # the raised cap on that call site, same rationale) --
                            # and that forced dispatch is gated on
                            # _question_is_approval_related(question), which a
                            # purely technical wording like "quelles sont toutes les
                            # surcharges ... et dans quel ordre s'exécutent-elles ?"
                            # never matches (no approval-pattern word appears; same
                            # underscore-boundary class of gap already fixed for the
                            # override-modules/override-chain-amount backfills
                            # above). So this exact question only ever reaches the
                            # tool via the LLM's OWN free ReAct call here, which
                            # used to hit the smaller 1200 cap -- confirmed live to
                            # cut the real 3-module chain (2072 chars) mid-way
                            # through module 2, before module 3 (the base module,
                            # 'custom_credit_note_approval') is ever reached. The
                            # LLM then filled the gap by mislabeling unrelated
                            # analyser_verrous_securite content as the missing 3rd
                            # site, and the deterministic backfill couldn't recover
                            # it either -- it can only re-surface a fact already
                            # present in the stored observation, and by then it
                            # genuinely wasn't. Same raised cap as the forced
                            # dispatch, applied here too, rather than trying to
                            # widen the approval-pattern gate again (that gate is
                            # for triggering an EXTRA forced call, not for deciding
                            # how much of a call the LLM makes on its own to
                            # truncate -- widening it further risks the same kind
                            # of over-broad refiring already rejected once for
                            # _APPROVAL_PATTERN, see the J8/J9 comment above it).
                            # Bloc 9 gap fix (2026-08-13, module 6/8): analyser_
                            # actions_serveur's forced pre-dispatch above needed
                            # 3000 for the same aggregation reason -- mirror it
                            # here too, in case the LLM's own free ReAct call
                            # reaches this tool on a question whose wording
                            # doesn't satisfy _question_suggests_automation_bypass
                            # (same class of gap already fixed for
                            # analyser_chaine_surcharge_methode below).
                            _observation_cap = (
                                2200 if tool_name == "analyser_chaine_surcharge_methode"
                                else 3000 if tool_name == "analyser_actions_serveur"
                                else 1200
                            )
                            if len(observation) > _observation_cap:
                                observation = observation[:_observation_cap] + "\n[... Content truncated for LLM context limit ...]"
        
                            # Bloc 7 (J23-24): compute the RuleEvaluationResult
                            # once, unconditionally, whenever this tool ran --
                            # both the gating below and the can_view_amount
                            # deterministic fact (J14 fix, only when an amount
                            # is present) reuse this same object instead of
                            # calling evaluer_regles_raw twice.
                            rule_result = None
                            if tool_name == "evaluer_regles_enregistrement":
                                try:
                                    from code_intelligence.ci_agent_tools import evaluer_regles_raw
        
                                    rule_result = evaluer_regles_raw(
                                        model_name=tool_args.get("model_name", ""),
                                        permission=tool_args.get("permission", "read"),
                                        user_groups_json=tool_args.get("user_groups_json", "[]"),
                                    )
                                except Exception as ve:
                                    logger.error("evaluer_regles_raw computation failed: %s", ve)
        
                            # Bloc 7 (J23-24): generalized gating -- filter this
                            # observation according to the demandeur's real
                            # rights BEFORE it ever reaches the synthesis LLM,
                            # so an omitted fact can't leak back out paraphrased.
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
                            # ReAct-loop fix: feed this (already-gated)
                            # observation back as a ToolMessage tied to its
                            # tool_call_id, so the LLM sees the real result --
                            # "not found", the access matrix, whatever it is --
                            # on its NEXT tool-selection call, instead of being
                            # re-invoked blind against the exact same prompt.
                            messages.append(ToolMessage(content=observation, tool_call_id=tool_id))
                            _ci_per_hop_times.append(time.perf_counter() - _t_hop)  # J30-J31
                            hop_count += 1
                            # J46-J48: index this hop into the reasoning trace --
                            # tool_name, args, observation, elapsed, in call order.
                            _trace_logger.log_hop(
                                trace_id=_trace_id, hop_index=_hop_index, tool_name=tool_name,
                                tool_args=tool_args, observation=observation,
                                elapsed_ms=_ci_per_hop_times[-1] * 1000,
                            )
                            _hop_index += 1
        
                            # J30-J31: CI_MAX_HOPS enforcement (was defined but
                            # never checked -- the loop ran up to
                            # REACT_RECURSION_LIMIT=6 instead of CI_MAX_HOPS=4).
                            if hop_count >= CI_MAX_HOPS:
                                logger.warning(
                                    "Node [code_intelligence_agent]: CI_MAX_HOPS (%d) "
                                    "reached -- breaking ReAct loop.", CI_MAX_HOPS,
                                )
                                break
        
                            # J14 fix (Q6.1 regression):
                            # evaluer_regles_enregistrement's summary_text lists
                            # applicable group rules but never computes the actual
                            # OR-union against a specific amount -- it leaves the
                            # synthesis LLM to guess, and the LLM picked the most
                            # restrictive rule instead of the union. can_view_amount()
                            # already implements the correct AND-global/OR-group
                            # logic; reuse the RuleEvaluationResult computed above
                            # (shares the same resolve + parse logic as the @tool
                            # wrapper) to inject an unambiguous deterministic fact
                            # the synthesis LLM must not recompute or contradict.
                            # This injected fact is NEVER gated: it's already
                            # computed directly against the demandeur's real
                            # rights, so surfacing the verdict itself (not the
                            # rule's internal name/condition) is exactly the
                            # point of Bloc 7's generalized gating, not something
                            # it should hide.
                            if tool_name == "evaluer_regles_enregistrement" and rule_result is not None:
                                amount = _extract_amount(question)
                                if amount is not None:
                                    try:
                                        # Bloc9 08c fix: can_view_amount() (regex-
                                        # only, single field) silently returned
                                        # True whenever a domain_force mixed the
                                        # amount condition with something it
                                        # couldn't parse (e.g. company_id) --
                                        # confirmed root cause of 08c. can_view_
                                        # amount_v2() evaluates the FULL parsed
                                        # domain_force via Kleene tri-state logic
                                        # instead, so an unresolved condition
                                        # surfaces as None ("cannot conclude"),
                                        # never as a silent allow.
                                        #
                                        # Bloc9 08c follow-up (2026-08-13):
                                        # company/user context IS now extracted
                                        # from the question (_extract_company_
                                        # context, qualitative same/different
                                        # only -- see that function's own
                                        # docstring for why an identity lookup
                                        # isn't possible on this codebase/test
                                        # instance). A question that says
                                        # nothing about company still yields {}
                                        # here, so a company_id-referencing
                                        # domain_force still resolves to the
                                        # same honest None ("cannot conclude")
                                        # as before this follow-up -- no
                                        # regression on the silent-mention case,
                                        # only new coverage on the explicit one.
                                        context = {"amount": amount}
                                        context.update(_extract_company_context(question))
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
                                            "global_rules_applied=%d, group_rules_applied=%d "
                                            "(Bloc9 08c diagnostic, 2026-08-14: distinguishes a "
                                            "resolution/wiring gap -- model not found or zero "
                                            "applied rules would silently default this to True -- "
                                            "from a synthesis-level inversion of a correct verdict; "
                                            "bare can_view/unresolved logging alone couldn't tell "
                                            "the two apart on the bloc9-08c-nested-domain-trap rerun).",
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
                    # qui_a_acces_a before it reaches the synthesis LLM when
                    # the real-auth override has already injected the
                    # demandeur's real groups into evaluer_regles_enregistrement
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
                        f"such tag in their source text (e.g. ir.rule / evaluer_regles_enregistrement "
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
                        f"'evaluer_regles_enregistrement.can_view_amount' itself as if that were "
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
                        # 2026-08-14: routed through get_chat_llm() -- see the
                        # ReAct-loop instantiation above for the full rationale.
                        plain_llm = get_chat_llm(
                            temperature=0.0, max_retries=0, max_tokens=4096,
                            # Review finding (Q1.1 benchmark run): mitigate llama-3.1-8b-instant's
                            # decoding-collapse failure mode (see _detect_degenerate_repetition) --
                            # a mild penalty discourages the model from repeating the same token/
                            # phrase without materially changing normal synthesis quality.
                            model_kwargs={"frequency_penalty": 0.3, "presence_penalty": 0.2},
                        )
                        _t_synthesis = time.perf_counter()
                        final_resp, _synth_wait = _invoke_with_rate_limit(plain_llm, [HumanMessage(content=synthesis_prompt)])
                        _llm_call_count += 1  # J46-J48: synthesis call
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
            # Bloc 9 cross-module gap fix (2026-08-10): deterministic backfill,
            # not a prompt instruction -- see the comment above
            # _REQUIRED_GROUP_LINE_RE for why. Never runs on the dynamic-
            # uncertainty path above (that answer is deliberately restricted to
            # "cannot determine with certainty"; appending a required-group fact
            # there would contradict its own point).
            # Bloc 9 gap fix (2026-08-10, bloc9-05c-no-link-trap contamination):
            # scope both backfills to the model(s) the question actually
            # resolved to, instead of the full unscoped raw_tool_output -- see
            # _scoped_raw_tool_output docstring. raw_tool_output itself stays
            # unscoped for citation verification / dynamic-uncertainty below.
            scoped_tool_output = _scoped_raw_tool_output(
                tool_observations, tool_observation_models, concept.resolved_models,
            )
            # TEMP DEBUG (2026-08-13, requested for bloc9-08 follow-up investigation)
            # -- remove once the grounding-validator false-negative/false-positive
            # rate has been checked against a few more real bloc9-08-style runs.
            logger.info(
                "Node [code_intelligence_agent]: DEBUG scoped_tool_output for this turn "
                "(%d chars): %s", len(scoped_tool_output), scoped_tool_output,
            )
            # Bloc 9 gap fix (2026-08-14, module 8/8, bloc9-08a-business): detect
            # and correct synthesis-level inversions of Python security lock
            # threshold logic (e.g. denying manager authority above threshold or
            # wrongly attributing authority to higher untriggered admin groups).
            final_answer = _correct_security_lock_threshold_contradictions(final_answer, scoped_tool_output, question)
            final_answer = _backfill_missing_required_groups(final_answer, scoped_tool_output, question)
            # Bloc 9 gap fix (2026-08-13, module 4/8, bloc9-04a-business /
            # bloc9-04c-manager-trap): same deterministic-backfill principle,
            # applied right after the required-groups backfill above since both
            # read analyser_verrous_securite's output (as opposed to the
            # override-cascade family of backfills below, which read
            # analyser_chaine_surcharge_methode's) -- see the comment above
            # _SECURITY_LOCK_MESSAGES_MARKER for the fact shape this restores.
            final_answer = _backfill_missing_security_lock_amount(final_answer, scoped_tool_output, question=question)
            # Bloc 9 gap fix (2026-08-11, module 1/8 rerun): same deterministic-
            # backfill principle, two more applications -- see the comment
            # above _OVERRIDE_MODULE_RE/_OVERRIDE_CHAIN_AMOUNT_RE for why these
            # two are separate from the required-groups backfill (different
            # fact shapes: a module name dropped/mislabeled, and a relational-
            # chain amount threshold ignored on business-phrased questions).
            final_answer = _backfill_missing_override_modules(final_answer, scoped_tool_output)
            # Bloc 9 gap fix (2026-08-12, module 1/8, bloc9-01b-technical): fix
            # the prose ITSELF when it actively contradicts the override-cascade
            # facts (denies other overrides exist, or fabricates a short-circuit
            # execution order) -- run right after the module backfill above so
            # both operate on the same _extract_override_modules() data, before
            # the (separate) amount backfill appends anything further below.
            final_answer = _correct_override_cascade_contradictions(final_answer, scoped_tool_output)
            final_answer = _backfill_missing_override_chain_amount(final_answer, scoped_tool_output)
            # Bloc 9 gap fix (2026-08-11, module 6/8, bloc9-06c-technical-
            # condition-capture): same deterministic-backfill principle applied
            # to analyser_actions_serveur's trigger-condition literal (e.g.
            # 'in_refund') instead of the override-cascade's amount/module --
            # see the comment above _TRIGGER_CONDITION_RE for why only the
            # quoted literal is backfilled, not the whole condition expression.
            final_answer = _backfill_missing_trigger_condition_literals(final_answer, scoped_tool_output)
            # Bloc 9 gap fix (2026-08-13, module 6/8, bloc9-06c-technical-
            # condition-capture): same deterministic-backfill principle applied
            # to the hardcoded privileged-partner IDs inside the same
            # analyser_actions_serveur finding -- see the comment above
            # _HARDCODED_IDS_LINE_RE for why only the bracketed ID tokens are
            # backfilled, not the surrounding sentence.
            final_answer = _backfill_missing_hardcoded_id_literals(final_answer, scoped_tool_output)
            # Bloc 9 gap fix (2026-08-11, module 1/8, bloc9-01c-vip-trap):
            # same deterministic-backfill principle applied to the SUPER() NON
            # GARDÉ warning from the override-cascade analysis -- the condition
            # field name (e.g. avoir_vip_exempt) and the super() trap fact are
            # reliably dropped when Groq 413 truncation cuts the observation.
            final_answer = _backfill_missing_unguarded_super(final_answer, scoped_tool_output)
            # Bloc 9 gap fix (2026-08-10, bloc9-05c-no-link-trap): same
            # deterministic-backfill principle, second application -- see the
            # comment above _LINK_GUARD_RE for why this one is unconditional
            # (always appended when the annotation exists) rather than gated on
            # question wording like the required-groups backfill above.
            final_answer = _backfill_link_guard_clarifications(final_answer, scoped_tool_output)
            # Bloc9 08c follow-up (2026-08-14): symmetric to the override-cascade
            # contradiction fix above, but for the can_view_amount_v2 fact --
            # correct a synthesis-level inversion of the deterministic verdict
            # in place. Deliberately unconditional (no question-wording gate),
            # same reasoning as every other correction/backfill in this module:
            # the presence of the fact itself (_has_can_view_amount_fact) is
            # already the real relevance guard. Placed after the link-guard
            # backfill (which also appends a '[FAIT' block) so its cutoff logic
            # never mistakes the link-guard's own block for prose to scan.
            final_answer = _correct_can_view_amount_contradictions(final_answer)
            # Bloc 9 gap fix (2026-08-13, module 8/8 follow-up investigation):
            # a NEGATIVE/grounding validator, unlike every backfill above (which
            # only ever ADDS a fact known to be true). This one only ever FLAGS,
            # never silently strips -- same transparency principle already used
            # by verify_citations/annotate_unverifiable_citations right below for
            # the structurally identical problem (an LLM claim with no verified
            # backing in this turn's evidence). Extracts the set of group
            # xmlids actually grounded in this turn's scoped_tool_output (reusing
            # _extract_required_groups -- the exact same has_group() line format
            # _backfill_missing_required_groups already trusts as authoritative),
            # then flags any <module>.group_<x>-shaped token in final_answer that
            # isn't in that set. Deliberately a no-op when grounded is empty --
            # a turn where no security-lock tool fired this hop has no reference
            # set to check against, and flagging every group mention as fake in
            # that case would be strictly worse than saying nothing.
            final_answer = _flag_ungrounded_group_xmlids(final_answer, scoped_tool_output)
            # Bloc 9 gap fix (2026-08-14, module 1/8 follow-up): distinct from
            # the flag above -- a group that IS grounded but only in a
            # non-custom (core Odoo) block of this same scoped_tool_output is
            # never legitimate content for this question, so it is stripped
            # rather than merely flagged. See _grounded_core_only_groups /
            # _strip_core_only_group_mentions docstrings above for the full
            # rationale and the precedent (module 5/8 Bug 2) for why a flag
            # alone was not sufficient for this shape of problem.
            final_answer = _strip_core_only_group_mentions(final_answer, scoped_tool_output)
        
        from code_intelligence.sourcing_guard import verify_citations, annotate_unverifiable_citations
        sourcing_result = verify_citations(final_answer, raw_tool_output)
        if not sourcing_result.is_fully_verified:
            logger.warning("Node [code_intelligence_agent]: Unverified citations -- %s", sourcing_result)
            final_answer = annotate_unverifiable_citations(final_answer, sourcing_result)
        
        # Review finding (Q1.1 benchmark run): final catch-all in case a
        # degenerate repetition slipped through on a path OTHER than the main
        # synthesis-prompt branch above (e.g. ai_msg.content returned directly
        # without any tool call) -- never ship a wall of repeated tokens
        # regardless of which code path produced final_answer.
        if _detect_any_degenerate_repetition(final_answer):
            logger.error(
                "Node [code_intelligence_agent]: degenerate repetition detected in final_answer "
                "outside the main synthesis retry path -- stripping before returning."
            )
            final_answer = _strip_any_degenerate_repetition(final_answer)
        
        final_answer += "\n\n[Source: Graphe de Connaissances Code Intelligence]"
        
        # Bloc 7 (J23-24): surface the omission state explicitly and visibly,
        # kept as its own separate footer -- never merged into the sourcing
        # warning above -- so an omission is never mistaken for an unverified
        # citation or folded into the confidence score.
        from core.schemas import OmittedForAuthorization
        # Dedup: the same tool (e.g. evaluer_regles_enregistrement on the same
        # model) can legitimately be invoked more than once across the forced
        # pre-dispatch + ReAct loop, or re-invoked by the LLM with identical
        # args -- each call gates and records its own OmittedItem, so without
        # this the footer/response repeat the identical omission N times
        # (observed in the J28-29 benchmark run, e.g. Q5.1 showing the same
        # ir.rule omission 4x). Dedup on (label, reason), order-preserving.
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
                "\n\n\U0001F512 \u00c9L\u00c9MENT(S) OMIS POUR RAISON D'AUTORISATION (Bloc 7 / J23-24):\n"
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
        
        # J30-J31: compute effective latency (algorithmic) by subtracting Groq waits
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
        
        # Bloc 12 / J46-J48: close the reasoning trace for this question --
        # SUMMARY record ties hop_count/llm_call_count/total_time to every HOP
        # record logged above under the same trace_id, and flags whether
        # CI_MAX_HOPS was actually hit (the J48 guardrail).
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
