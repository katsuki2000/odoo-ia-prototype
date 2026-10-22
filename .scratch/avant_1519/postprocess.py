"""Answer grounding, retained legacy correctors and response assembly."""

import logging
import re
import time
from dataclasses import asdict
from typing import List, Optional

from core.schemas import AssistantResponse, SourceReference, OmittedForAuthorization
from core.evidence.evidence_sufficiency import assess_evidence_sufficiency
from core.evidence.source_refs import CODE_GRAPH_DOC_TYPE, format_code_graph_source
from config.settings import SOURCE_LINK_ROOTS
from code_intelligence.utils import _TRUNCATION_MARKER, relativize_file_links
from core.output import _detect_any_degenerate_repetition, _strip_any_degenerate_repetition
from code_intelligence.agent.access_guards import (
    _scoped_raw_tool_output, _flag_ungrounded_group_xmlids,
)
from code_intelligence.rules.access_evaluator import _correct_access_permission_contradictions
from code_intelligence.agent.link_guards import (
    _backfill_missing_trigger_condition_literals, _backfill_missing_hardcoded_id_literals,
    _backfill_link_guard_clarifications,
)
from code_intelligence.agent.can_view_verifier import (
    _correct_can_view_amount_contradictions, _backfill_missing_can_view_amount_fact,
    _detect_can_view_amount_model_conflict, _format_conflicting_evidence_answer,
)
from code_intelligence.agent.dispatch_guards import _force_out_of_scope_model_answer, _build_dynamic_uncertainty_answer
from code_intelligence.rules.overrides import (
    _backfill_missing_override_modules, _backfill_missing_override_chain_amount,
    _correct_override_cascade_contradictions, _backfill_missing_unguarded_super,
)
from code_intelligence.rules.structure import (
    _correct_module_extension_contradiction, _backfill_missing_module_extension_details,
    _strip_irrelevant_inheritance_constraints,
)
from code_intelligence.rules.workflow import (
    _correct_noop_hook_hallucinations, _backfill_action_confirm_workflow_details,
    _backfill_confirmation_lock_fact, _backfill_backorder_policy_facts, _backfill_stage_recurrence_conditions,
)
from code_intelligence.rules.button_path import correct_button_role_contradictions, correct_button_visibility_contradictions
from code_intelligence.rules.data_constraints import (
    backfill_missing_bounds_facts, backfill_missing_conditional_check_facts, enforce_sql_constraint_fidelity,
)
from code_intelligence.agent.context import _EXECUTION_FAILURE_NOTICE, _CI_TOOL_DISPLAY_NAMES, DispatchContext
from code_intelligence.agent.provenance import source_footer
from code_intelligence.rules.security_locks import _has_elevated_access

logger = logging.getLogger(__name__)
_UNEXPECTED_HAN_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
_UNSOURCED_EXAMPLE_RE = re.compile(
    r'^\s*(?:(?:\*\*)?(?:exemple|example)(?:\*\*)?\s*:|#{1,6}\s+(?:exemple|example)\b)', re.IGNORECASE)


def _strip_unexpected_script_sentences(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if not _UNEXPECTED_HAN_RE.search(line):
            lines.append(line)
        else:
            lines.extend(sentence for sentence in re.split(r'(?<=[.!?])\s+', line)
                         if not _UNEXPECTED_HAN_RE.search(sentence))
    return '\n'.join(lines)


def _strip_unsourced_examples(final_answer: str, raw_tool_output: str) -> str:
    if re.search(r'\b(?:exemple|example)\b', raw_tool_output, re.IGNORECASE):
        return final_answer
    return '\n\n'.join(block for block in re.split(r'\n\s*\n', final_answer)
                        if not _UNSOURCED_EXAMPLE_RE.match(block)).strip()


def _strip_truncation_marker_for_display(text: str, source_label: str = '') -> str:
    """Keep truncation markers in observations; remove them only in display copies."""
    if not text:
        return text
    if _TRUNCATION_MARKER in text:
        logger.warning('Observation truncated before display: %s (%d chars)', source_label, len(text))
    return text.replace(_TRUNCATION_MARKER, '').rstrip()


def _apply_backfill_chain(final_answer: str, scoped_tool_output: str, question: str,
                          scoped_tool_observation_models=None, target_models=None,
                          raw_tool_output: str = '', constraint_tool_output: str = '',
                          applied_guards: Optional[List[str]] = None) -> str:
    """Retain unreviewed correctors until their evidence contracts are migrated."""
    rawOrScoped = raw_tool_output or scoped_tool_output
    scopedOrRaw = scoped_tool_output or raw_tool_output
    constraintSource = constraint_tool_output or scoped_tool_output or raw_tool_output
    steps = [
        (_correct_access_permission_contradictions, (scoped_tool_output,), {}),
        (_backfill_missing_can_view_amount_fact, (scoped_tool_output,),
         {'tool_observation_models': scoped_tool_observation_models, 'target_models': target_models}),
        (correct_button_role_contradictions, (rawOrScoped,), {}),
        (correct_button_visibility_contradictions, (rawOrScoped,), {}),
        (_backfill_missing_override_modules, (scoped_tool_output,), {'question': question}),
        (_correct_override_cascade_contradictions, (scoped_tool_output,), {}),
        (_correct_module_extension_contradiction, (rawOrScoped,), {'question': question}),
        (_backfill_missing_module_extension_details, (rawOrScoped,), {'question': question}),
        (_backfill_missing_override_chain_amount, (scoped_tool_output,), {}),
        (_backfill_missing_trigger_condition_literals, (scoped_tool_output,), {}),
        (_backfill_missing_hardcoded_id_literals, (scoped_tool_output,), {}),
        (_backfill_missing_unguarded_super, (scoped_tool_output,), {}),
        (_backfill_link_guard_clarifications, (scoped_tool_output,), {'question': question}),
        (_correct_can_view_amount_contradictions, (), {}),
        (_correct_noop_hook_hallucinations, (rawOrScoped,), {'question': question}),
        (_backfill_action_confirm_workflow_details, (rawOrScoped,), {'question': question}),
        (_backfill_confirmation_lock_fact, (rawOrScoped,), {'question': question}),
        (_backfill_backorder_policy_facts, (rawOrScoped,), {'question': question}),
        (_backfill_stage_recurrence_conditions, (rawOrScoped,), {'question': question}),
        (backfill_missing_conditional_check_facts, (constraintSource,), {'question': question}),
        (backfill_missing_bounds_facts, (constraintSource,), {'question': question}),
        (_flag_ungrounded_group_xmlids, (scoped_tool_output,), {}),
        (_strip_irrelevant_inheritance_constraints, (), {'question': question}),
        (enforce_sql_constraint_fidelity, (constraintSource, question), {}),
    ]
    for guard, args, kwargs in steps:
        updated = guard(final_answer, *args, **kwargs)
        if updated != final_answer:
            logger.info("Node [code_intelligence_agent]: guard '%s' modified the answer (%d -> %d chars).",
                        guard.__name__, len(final_answer), len(updated))
            if applied_guards is not None:
                applied_guards.append(guard.__name__)
        final_answer = updated
    return final_answer


def build_final_response(ctx: DispatchContext, final_answer: str, state: dict,
                         start_time: float, resolver_time: float, evidence_status) -> dict:
    question, concept = ctx.question, ctx.concept
    observations, models, tools = ctx.tool_observations, ctx.tool_observation_models, ctx.tool_observation_tools
    raw = '\n\n'.join(observations)
    refusal = _force_out_of_scope_model_answer(question, concept)
    uncertainty = _build_dynamic_uncertainty_answer(raw)
    conflict, applied = None, []
    if refusal:
        final_answer = refusal
    elif uncertainty:
        final_answer = uncertainty
    else:
        scoped = _scoped_raw_tool_output(observations, models, concept.resolved_models)
        targets = set(concept.resolved_models) if concept.resolved_models else None
        scopedModels = [model for obs, model in zip(observations, models)
                        if not targets or (model and model in targets)]
        constraints = '\n\n'.join(obs for obs, tool in zip(observations, tools) if tool == 'analyze_data_constraints')
        conflict = _detect_can_view_amount_model_conflict(
            scoped, tool_observation_models=scopedModels, target_models=concept.resolved_models)
        if conflict:
            final_answer = _format_conflicting_evidence_answer(
                scoped, tool_observation_models=scopedModels, target_models=concept.resolved_models) or final_answer
        else:
            final_answer = _apply_backfill_chain(
                final_answer, scoped, question, scoped_tool_observation_models=scopedModels,
                target_models=concept.resolved_models, raw_tool_output=raw,
                constraint_tool_output=constraints, applied_guards=applied)
    from code_intelligence.agent.dispatch_guards import (
        verify_citations, annotate_unverifiable_citations, substitute_or_strip_code_blocks,
    )
    final_answer = substitute_or_strip_code_blocks(final_answer, observations)
    final_answer = re.sub(r'\[([^\]]*)\]\(file:///\.\.\.[^)]*\)', r'\1', final_answer)
    sourcing = verify_citations(final_answer, raw)
    if not sourcing.is_fully_verified:
        logger.warning('Unverified citations: %s', sourcing)
        final_answer = annotate_unverifiable_citations(final_answer, sourcing)
    if _detect_any_degenerate_repetition(final_answer):
        final_answer = _strip_any_degenerate_repetition(final_answer)
    final_answer = _strip_unexpected_script_sentences(final_answer)
    final_answer = _strip_unsourced_examples(final_answer, raw)
    sufficiency = assess_evidence_sufficiency(observations, ctx.hop_count, final_answer, conflict_reason=conflict)
    if sufficiency.has_execution_failure:
        final_answer += _EXECUTION_FAILURE_NOTICE
    final_answer = re.sub(
        r'\n+(?:---\s*\n+)?(?:#{1,4}\s+)?(?:Preuves|Sources)\s*[:\n][\s\S]*$', '',
        final_answer, flags=re.IGNORECASE).strip()
    final_answer = _strip_truncation_marker_for_display(final_answer, 'final_answer (synthese)')
    final_answer += '\n\n' + source_footer(sufficiency)
    seen, omitted = set(), []
    for item in ctx.omitted_items:
        key = item.label, item.reason
        if key not in seen:
            seen.add(key)
            omitted.append(OmittedForAuthorization(label=item.label, reason=item.reason))
    if omitted:
        final_answer += "\n\n[ACCES RESTREINT] ÉLÉMENT(S) OMIS POUR RAISON D'AUTORISATION:\n" + '\n'.join(
            f'  - {item.label} : {item.reason}' for item in omitted)
    final_answer = relativize_file_links(final_answer, SOURCE_LINK_ROOTS)
    sources = []
    for obs, model, tool in zip(observations, models, tools):
        if not obs or not str(obs).strip():
            continue
        display = _CI_TOOL_DISPLAY_NAMES.get(tool, tool or 'outil inconnu')
        sources.append(SourceReference(
            source=format_code_graph_source(tool, model), doc_type=CODE_GRAPH_DOC_TYPE,
            title=f'{display} — {model}' if model else display,
            snippet=relativize_file_links(
                _strip_truncation_marker_for_display(str(obs), f'{tool}({model})'), SOURCE_LINK_ROOTS)))
    response = AssistantResponse(answer=final_answer, sources=sources,
        confidence=1.0 if observations else 0.5, omitted_for_authorization=omitted)
    wallTime = time.time() - start_time
    timing = state.get('timing', {}).copy()
    timing.update(code_intelligence_time=wallTime, ci_hop_count=ctx.hop_count,
        ci_llm_wait_time=round(ctx.llm_wait, 3), ci_effective_time=round(wallTime - ctx.llm_wait, 3),
        ci_business_resolver_time=round(resolver_time, 3), ci_per_hop_times=[round(t, 3) for t in ctx.per_hop_times],
        ci_synthesis_time=round(ctx.synthesis_time, 3), ci_applied_guards=applied, llm_call_count=ctx.llm_call_count)
    ctx.trace_logger.log_summary(trace_id=ctx.trace_id, branch='code_intelligence', question=question,
        hop_count=ctx.hop_count, llm_call_count=ctx.llm_call_count, total_time_ms=wallTime * 1000, hop_cap=ctx.hop_cap)
    return {'response': response, 'raw_answer': final_answer, 'timing': timing, 'raw_tool_output': raw,
            'knowledge_graph': ctx.G,
            'sensitive_evidence_allowed': _has_elevated_access(ctx.G, '', ctx.resolved_user_group_xmlids or []),
            'evidence_status': evidence_status, 'loop_resolved_concept': asdict(concept),
            'ci_evidence_sufficiency': sufficiency.to_display_dict()}
