"""
core/graph_compat.py

Backward-compatible re-exports for legacy tests and external callers that
historically imported schemas, guards, helpers, and agents from core.graph.graph.
"""

from core.schemas import (
    AssistantResponse,
    SourceReference,
    LLMResponse,
    QueryRoute,
    source_display_title,
)

from core.llm.llm_client import (
    get_chat_llm,
    invoke_with_rate_limit as _invoke_with_rate_limit,
    _parse_reset_seconds,
    _extract_rate_limit_headers,
    _ToolCallFallback,
    _try_recover_tool_use_failed,
    _reduce_message_context,
    _TOOL_MSG_HARD_CAP,
    _TOOL_USE_FAILED_RE,
    _FAILED_GEN_CALL_RE,
    _llm_call_lock,
    _last_llm_call_time,
    MIN_LLM_CALL_INTERVAL,
)

from core.output import (
    _DEGENERATE_REPETITION_RE,
    _DEGENERATE_LINE_REPETITION_MIN_REPEATS,
    _DEGENERATE_LINE_MIN_LENGTH,
    _DEGENERATE_BLANK_RUN_RE,
    _DEGENERATE_PREFIX_LENGTH,
    _DEGENERATE_PREFIX_MIN_REPEATS,
    _detect_degenerate_repetition,
    _strip_degenerate_repetition,
    _detect_degenerate_line_repetition,
    _strip_degenerate_line_repetition,
    _detect_degenerate_blank_run,
    _strip_degenerate_blank_run,
    _detect_degenerate_growing_repetition,
    _strip_degenerate_growing_repetition,
    _detect_any_degenerate_repetition,
    _strip_any_degenerate_repetition,
)

from core.state import RAGState
from core.routing.routing import (
    ERP_TYPES,
    ROUTING_CONFLICT_PRIORITY,
    ERP_KEYWORDS,
    ERP_KEYWORDS_FOLDED,
    CODE_INTEL_KEYWORDS,
    CODE_INTEL_KEYWORDS_FOLDED,
    QUANTITATIVE_TERMS,
    QUANTITATIVE_TERMS_FOLDED,
    DOC_KEYWORDS,
    DOC_KEYWORDS_FOLDED,
    DATA_TERMS,
    DATA_TERMS_FOLDED,
    DOC_ANCHORS,
    DOC_ANCHORS_FOLDED,
    THRESHOLD_QUERY_TERMS,
    THRESHOLD_QUERY_TERMS_FOLDED,
    _fold_accents,
    _fold_keywords,
    route,
    route_decision,
)

from document_rag.generate_node import (
    _parse_raw_json_answer,
    generate,
)


from erp_data.orm_agent_node import (
    orm_agent_loop,
    hybrid_node,
)

from code_intelligence.graph.loader import (
    _CACHED_CODE_INTEL_GRAPH,
    _CACHED_GRAPH_MTIME,
    GRAPH_JSON_PATH,
    _load_module,
    get_code_intelligence_graph,
)

from code_intelligence.agent.context import CI_MAX_HOPS
from code_intelligence.agent.context_extractors import (
    _AMOUNT_PATTERN,
    _AUTOMATION_PATTERN,
    _question_mentions_amount,
    _extract_amount,
    _COMPANY_DIFFERENT_PATTERN,
    _COMPANY_SAME_PATTERN,
    _extract_company_context,
    _MOVE_TYPE_ALIAS_MAP,
    _infer_move_type_context,
    _question_is_approval_related,
    _ACCESS_QUESTION_PATTERN,
    _question_is_access_related,
)
from code_intelligence.utils import _APPROVAL_PATTERN
from code_intelligence.agent.access_guards import (
    _REQUIRED_GROUP_LINE_RE,
    _GROUP_XMLID_RE,
    _extract_required_groups,
    _flag_ungrounded_group_xmlids,
    _grounded_core_only_groups,
    _strip_core_only_group_mentions,
    _scoped_raw_tool_output,
    _LOCK_CONDITION_LINE_RE,
    _AMOUNT_CMP_RE,
    _extract_required_groups_for_amount,
    _BLOCK_FILE_LINK_RE,
    _block_is_custom_module_file,
    _restrict_blocks_to_custom_modules,
    _backfill_missing_required_groups,
)
from code_intelligence.rules.security_locks import (
    _OVERRIDE_CHAIN_AMOUNT_RE,
    _amount_present_in_text,
    _SECURITY_LOCK_MESSAGES_MARKER,
    _extract_security_lock_condition_amounts,
    _backfill_missing_security_lock_amount,
    _correct_security_lock_threshold_contradictions,
)
from code_intelligence.agent.link_guards import (
    _LINK_GUARD_RE,
    _LINK_GUARD_CONTRADICTION_PATTERN,
    _LINK_GUARD_CONTRADICTING_SENTENCE_RE,
    _answer_contradicts_link_guard,
    _neutralize_contradicting_link_guard_sentence,
    _extract_link_guard_fields,
    _TRIGGER_CONDITION_RE,
    _TRIGGER_CONDITION_LITERAL_RE,
    _extract_trigger_condition_literals,
    _backfill_missing_trigger_condition_literals,
    _HARDCODED_IDS_LINE_RE,
    _extract_hardcoded_id_literals,
    _backfill_missing_hardcoded_id_literals,
    _backfill_link_guard_clarifications,
)
from code_intelligence.agent.can_view_verifier import (
    _CAN_VIEW_ALLOW_ASSERTION_RE,
    _CAN_VIEW_DENY_ASSERTION_RE,
    _CAN_VIEW_FACT_VERDICT_RE,
    _CAN_VIEW_FACT_INDETERMINATE_MARKER,
    _split_before_first_fact_marker,
    _extract_can_view_amount_verdict,
    _has_can_view_amount_fact,
    _correct_can_view_amount_contradictions,
    _extract_can_view_amount_fact_block,
    _backfill_missing_can_view_amount_fact,
    _format_can_view_amount_fact,
)
from code_intelligence.agent.dispatch_guards import (
    _question_suggests_automation_bypass,
    _rank_and_cap_resolved_models,
    _override_user_groups_arg,
    _COULD_NOT_RESOLVE_RE,
    _strip_group_resolution_noise,
    _extract_first_scoped_file_link,
    _TECHNICAL_MODEL_LOOKALIKE_RE,
    _force_out_of_scope_model_answer,
    _build_dynamic_uncertainty_answer,
)

from code_intelligence.rules.overrides import (
    _OVERRIDE_MODULE_RE,
    _extract_override_modules,
    _word_boundary_present,
    _backfill_missing_override_modules,
    _extract_override_chain_amounts,
    _backfill_missing_override_chain_amount,
    _correct_override_cascade_contradictions,
    _OVERRIDE_COUNT_DENIAL_RE,
    _OVERRIDE_ORDER_SHORTCIRCUIT_SENTENCE_RE,
    _answer_denies_other_overrides,
    _answer_asserts_override_shortcircuit,
    _neutralize_override_count_denial,
    _neutralize_override_shortcircuit_sentence,
    _UNGUARDED_SUPER_RE,
    _extract_unguarded_super_findings,
    _backfill_missing_unguarded_super,
    _MAX_OVERRIDE_CASCADE_DISPATCH,
    _rank_and_cap_override_methods,
)

from code_intelligence.agent.context import (
    _GROUP_XMLID_CACHE,
    _ADMIN_RPC_CLIENT,
    _ADMIN_RPC_UID,
    _get_admin_rpc_client,
    _resolve_user_group_xmlids,
)
from code_intelligence.agent.loop import code_intelligence_agent

__all__ = [k for k in globals().keys() if not k.startswith("__")]
