"""Ground ReAct answers in tool observations and assemble their response."""

import logging
import re
import time
from dataclasses import asdict

from config.settings import SOURCE_LINK_ROOTS
from code_intelligence.agent.context import (
    _CI_TOOL_DISPLAY_NAMES,
    _EXECUTION_FAILURE_NOTICE,
    DispatchContext,
)
from code_intelligence.agent.provenance import (
    _flag_ungrounded_group_xmlids,
    _scoped_raw_tool_output,
    source_footer,
)
from code_intelligence.rules.access_evaluator import _correct_access_permission_contradictions
from code_intelligence.rules.data_constraints import enforce_sql_constraint_fidelity
from code_intelligence.rules.security_locks import _has_elevated_access
from code_intelligence.utils import _TRUNCATION_MARKER, relativize_file_links
from core.evidence.evidence_sufficiency import assess_evidence_sufficiency
from core.evidence.source_refs import CODE_GRAPH_DOC_TYPE, format_code_graph_source
from core.output import _detect_any_degenerate_repetition, _strip_any_degenerate_repetition
from core.schemas import AssistantResponse, OmittedForAuthorization, SourceReference

logger = logging.getLogger(__name__)


def _strip_truncation_marker_for_display(text: str, source_label: str = '') -> str:
    if _TRUNCATION_MARKER in text:
        logger.warning('Observation truncated before display: %s (%d chars)', source_label, len(text))
    return text.replace(_TRUNCATION_MARKER, '').rstrip()


def build_final_response(ctx: DispatchContext, final_answer: str, state: dict,
                         start_time: float, resolver_time: float, evidence_status) -> dict:
    question, concept = ctx.question, ctx.concept
    observations = ctx.tool_observations
    models = ctx.tool_observation_models
    tools = ctx.tool_observation_tools
    raw = '\n\n'.join(observations)
    scoped = _scoped_raw_tool_output(observations, models, concept.resolved_models)
    constraints = '\n\n'.join(
        observation for observation, tool in zip(observations, tools)
        if tool == 'analyze_data_constraints'
    ) or scoped
    applied = []
    for guard, arguments in (
        (_correct_access_permission_contradictions, (scoped,)),
        (_flag_ungrounded_group_xmlids, (scoped,)),
        (enforce_sql_constraint_fidelity, (constraints, question)),
    ):
        corrected = guard(final_answer, *arguments)
        if corrected != final_answer:
            applied.append(guard.__name__)
        final_answer = corrected

    final_answer = re.sub(r'\[([^\]]*)\]\(file:///\.\.\.[^)]*\)', r'\1', final_answer)
    if _detect_any_degenerate_repetition(final_answer):
        final_answer = _strip_any_degenerate_repetition(final_answer)
    final_answer = re.sub(
        r'\n+(?:---\s*\n+)?(?:#{1,4}\s+)?(?:Preuves|Sources)\s*[:\n][\s\S]*$',
        '',
        final_answer,
        flags=re.IGNORECASE,
    ).strip()
    sufficiency = assess_evidence_sufficiency(observations, ctx.hop_count, final_answer)
    if sufficiency.has_execution_failure:
        final_answer += _EXECUTION_FAILURE_NOTICE
    final_answer = _strip_truncation_marker_for_display(final_answer, 'final_answer')
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
    for observation, model, tool in zip(observations, models, tools):
        if not observation.strip():
            continue
        display = _CI_TOOL_DISPLAY_NAMES.get(tool, tool or 'outil inconnu')
        sources.append(SourceReference(
            source=format_code_graph_source(tool, model),
            doc_type=CODE_GRAPH_DOC_TYPE,
            title=f'{display} — {model}' if model else display,
            snippet=relativize_file_links(
                _strip_truncation_marker_for_display(observation, f'{tool}({model})'),
                SOURCE_LINK_ROOTS,
            ),
        ))

    response = AssistantResponse(
        answer=final_answer,
        sources=sources,
        confidence=1.0 if observations else 0.5,
        omitted_for_authorization=omitted,
    )
    wall_time = time.time() - start_time
    timing = state.get('timing', {}).copy()
    timing.update(
        code_intelligence_time=wall_time,
        ci_hop_count=ctx.hop_count,
        ci_llm_wait_time=round(ctx.llm_wait, 3),
        ci_effective_time=round(wall_time - ctx.llm_wait, 3),
        ci_business_resolver_time=round(resolver_time, 3),
        ci_per_hop_times=[round(value, 3) for value in ctx.per_hop_times],
        ci_synthesis_time=round(ctx.synthesis_time, 3),
        ci_applied_guards=applied,
        llm_call_count=ctx.llm_call_count,
    )
    ctx.trace_logger.log_summary(
        trace_id=ctx.trace_id,
        branch='code_intelligence',
        question=question,
        hop_count=ctx.hop_count,
        llm_call_count=ctx.llm_call_count,
        total_time_ms=wall_time * 1000,
        hop_cap=ctx.hop_cap,
        fallback_reason=ctx.fallback_reason,
        final_message_preview=ctx.final_message_preview,
    )
    return {
        'response': response,
        'raw_answer': final_answer,
        'timing': timing,
        'raw_tool_output': raw,
        'knowledge_graph': ctx.G,
        'sensitive_evidence_allowed': _has_elevated_access(
            ctx.G, '', ctx.resolved_user_group_xmlids or []),
        'evidence_status': evidence_status,
        'loop_resolved_concept': asdict(concept),
        'ci_evidence_sufficiency': sufficiency.to_display_dict(),
    }
