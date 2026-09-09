"""
code_intelligence/ci_helpers.py

Backward-compatible facade for Code Intelligence helpers.
Modularized into focused submodules:
  - ci_prompt_and_heuristics: system prompt, hops, truncation helpers
  - ci_context_extractors: question intent, amounts, company context, move type
  - ci_access_guards: required groups, core-only stripping, custom module filtering
  - ci_link_guards: link guard contradictions, trigger literals, hardcoded IDs
  - ci_security_locks: lock condition amounts, threshold contradictions
  - ci_can_view_verifier: can_view_amount verdicts, conflict resolution
  - ci_dispatch_utils: model ranking, user group overrides, dynamic uncertainty
"""

from .prompt_and_heuristics import (
    CI_MAX_HOPS,
    _MODEL_KEYED_TOOLS,
    _tool_call_key,
    _TRUNCATION_MARKER,
    _truncate_observation,
)
from code_intelligence.answer_text_signals import (
    _TRUNCATION_PROXIMITY_CHARS,
    _match_near_truncation,
)

from code_intelligence.answer_text_signals import _APPROVAL_PATTERN
from .context_extractors import (
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
    _WORKFLOW_QUESTION_PATTERN,
    _question_is_workflow_related,
    _INHERITANCE_QUESTION_PATTERN,
    _question_is_inheritance_related,
    _METHOD_OR_OVERRIDE_PATTERN,
    _question_is_method_or_override_related,
    _CONSTRAINTS_QUESTION_PATTERN,
    _question_is_constraint_related,
    _rehydrate_sticky_concept,
)

from .access_guards import (
    _REQUIRED_GROUP_LINE_RE,
    _GROUP_XMLID_RE,
    _extract_required_groups,
    _flag_ungrounded_group_xmlids,
    _SENTENCE_SPLIT_RE,
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

from .link_guards import (
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

from code_intelligence.security.locks import (
    _OVERRIDE_CHAIN_AMOUNT_RE,
    _amount_present_in_text,
    _SECURITY_LOCK_MESSAGES_MARKER,
    _extract_security_lock_condition_amounts,
    _backfill_missing_security_lock_amount,
    _correct_security_lock_threshold_contradictions,
)

from .can_view_verifier import (
    _CAN_VIEW_ALLOW_ASSERTION_RE,
    _CAN_VIEW_DENY_ASSERTION_RE,
    _CAN_VIEW_FACT_VERDICT_RE,
    _CAN_VIEW_FACT_INDETERMINATE_MARKER,
    _split_before_first_fact_marker,
    _extract_can_view_amount_verdict,
    _has_can_view_amount_fact,
    _correct_can_view_amount_contradictions,
    _can_view_amount_candidates,
    _extract_can_view_amount_verdict_label,
    _detect_can_view_amount_model_conflict,
    _format_conflicting_evidence_answer,
    _extract_can_view_amount_fact_block,
    _backfill_missing_can_view_amount_fact,
    _format_can_view_amount_fact,
)

from .dispatch_utils import (
    _question_suggests_automation_bypass,
    _rank_and_cap_resolved_models,
    _override_user_groups_arg,
    _COULD_NOT_RESOLVE_RE,
    _strip_group_resolution_noise,
    _extract_first_scoped_file_link,
    _TECHNICAL_MODEL_LOOKALIKE_RE,
    _force_out_of_scope_model_answer,
    _force_dynamic_uncertainty_answer,
)

__all__ = [k for k in globals().keys() if not k.startswith("__")]
