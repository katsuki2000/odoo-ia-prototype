"""
code_intelligence/ci_agent_node/postprocess.py

Post-ReAct-loop pipeline: out-of-scope/dynamic-uncertainty overrides,
cross-model conflict detection, the backfill/correction chain, sourcing
verification, evidence-sufficiency assessment, and final AssistantResponse
assembly.
"""

import logging
import time

from core.schemas import AssistantResponse, SourceReference, OmittedForAuthorization
from core.evidence.evidence_sufficiency import assess_evidence_sufficiency
from code_intelligence.utils import _TRUNCATION_MARKER
from core.output import (
    _detect_any_degenerate_repetition,
    _strip_any_degenerate_repetition,
)
from code_intelligence.agent.access_guards import (
    _scoped_raw_tool_output,
    _flag_ungrounded_group_xmlids,
    _strip_core_only_group_mentions,
    _backfill_missing_required_groups,
)
from code_intelligence.rules.security_locks import (
    _backfill_missing_security_lock_amount,
    _correct_security_lock_threshold_contradictions,
)
from code_intelligence.agent.link_guards import (
    _backfill_missing_trigger_condition_literals,
    _backfill_missing_hardcoded_id_literals,
    _backfill_link_guard_clarifications,
)
from code_intelligence.agent.can_view_verifier import (
    _correct_can_view_amount_contradictions,
    _backfill_missing_can_view_amount_fact,
    _detect_can_view_amount_model_conflict,
    _format_conflicting_evidence_answer,
)
from code_intelligence.agent.dispatch_guards import (
    _force_out_of_scope_model_answer,
    _force_dynamic_uncertainty_answer,
)
from code_intelligence.rules.overrides import (
    _backfill_missing_override_modules,
    _backfill_missing_override_chain_amount,
    _correct_override_cascade_contradictions,
    _backfill_missing_unguarded_super,
)
from code_intelligence.rules.structure import _correct_module_extension_contradiction
from code_intelligence.agent.context import _EXECUTION_FAILURE_NOTICE, _CI_TOOL_DISPLAY_NAMES
from code_intelligence.agent.context import DispatchContext

logger = logging.getLogger(__name__)


def _strip_truncation_marker_for_display(text: str, source_label: str = "") -> str:
    """Cosmetic-only: drop the internal truncation marker before user-facing
    text is built (evidence snippet, final answer). ctx.tool_observations
    itself is NEVER passed through this -- _match_near_truncation() in
    access_guards.py / security/locks.py / overrides/cascade.py still needs
    the marker present there to reject facts extracted too close to a cut.
    See todo/contexte.txt (marqueur de troncature visible utilisateur).

    Section 876 (todo/contexte.txt): the warning used to name neither the
    tool nor the size that got cut, forcing a manual reasoning_trace.jsonl
    read every time (see section 875) to find out which call actually
    truncated. source_label/len(text) are logged whenever the caller has
    them -- purely diagnostic, no behaviour change."""
    if not text:
        return text
    if _TRUNCATION_MARKER in text:
        label = f" [source: {source_label}, {len(text)} chars]" if source_label else " [source: unknown]"
        logger.warning(
            "Node [code_intelligence_agent]: an observation was truncated "
            "(cap reached) and the marker is being stripped from user-facing "
            "text%s -- some evidence may be missing from this answer. See "
            "todo/contexte.txt sections 801-802/876.",
            label,
        )
    return text.replace(_TRUNCATION_MARKER, "").rstrip()


def _apply_backfill_chain(
    final_answer: str,
    scoped_tool_output: str,
    question: str,
    scoped_tool_observation_models=None,
    target_models=None,
    raw_tool_output: str = "",
) -> str:
    final_answer = _correct_security_lock_threshold_contradictions(final_answer, scoped_tool_output, question)
    final_answer = _backfill_missing_can_view_amount_fact(
        final_answer,
        scoped_tool_output,
        tool_observation_models=scoped_tool_observation_models,
        target_models=target_models,
    )
    final_answer = _backfill_missing_required_groups(final_answer, scoped_tool_output, question)
    final_answer = _backfill_missing_security_lock_amount(final_answer, scoped_tool_output, question=question)
    final_answer = _backfill_missing_override_modules(final_answer, scoped_tool_output, question=question)
    final_answer = _correct_override_cascade_contradictions(final_answer, scoped_tool_output)
    # Section 840: list_involved_modules' MODULE-mode evidence ("Module 'X'
    # defines or extends...") is recorded under tool_observation_models="X"
    # (the module name, e.g. "account"), never under the resolved MODEL name
    # (e.g. "account.move") -- scoped_tool_output filters by resolved model,
    # so this evidence is structurally never present there. Use the
    # unscoped raw_tool_output for this one guard instead; the denial check
    # still runs against final_answer, so no cross-model contamination risk.
    final_answer = _correct_module_extension_contradiction(
        final_answer, raw_tool_output or scoped_tool_output, question=question
    )
    final_answer = _backfill_missing_override_chain_amount(final_answer, scoped_tool_output)
    final_answer = _backfill_missing_trigger_condition_literals(final_answer, scoped_tool_output)
    final_answer = _backfill_missing_hardcoded_id_literals(final_answer, scoped_tool_output)
    final_answer = _backfill_missing_unguarded_super(final_answer, scoped_tool_output)
    final_answer = _backfill_link_guard_clarifications(final_answer, scoped_tool_output, question=question)
    final_answer = _correct_can_view_amount_contradictions(final_answer)
    final_answer = _flag_ungrounded_group_xmlids(final_answer, scoped_tool_output)
    final_answer = _strip_core_only_group_mentions(final_answer, scoped_tool_output)
    return final_answer


def build_final_response(
    ctx: DispatchContext,
    final_answer: str,
    state: dict,
    start_time: float,
    resolver_time: float,
    evidence_status,
) -> dict:
    question = ctx.question
    concept = ctx.concept
    tool_observations = ctx.tool_observations
    tool_observation_models = ctx.tool_observation_models
    tool_observation_tools = ctx.tool_observation_tools

    raw_tool_output = "\n\n".join(tool_observations)
    out_of_scope_model_answer = _force_out_of_scope_model_answer(question, concept)
    dynamic_uncertainty_answer = _force_dynamic_uncertainty_answer(question, raw_tool_output)
    ci_conflict_reason = None
    if out_of_scope_model_answer:
        final_answer = out_of_scope_model_answer
    elif dynamic_uncertainty_answer:
        final_answer = dynamic_uncertainty_answer
    else:
        scoped_tool_output = _scoped_raw_tool_output(
            tool_observations, tool_observation_models, concept.resolved_models,
        )
        # Section 2xx (todo/contexte.txt): kept aligned 1:1 with the blocks
        # in scoped_tool_output (same filter as _scoped_raw_tool_output) so
        # the backfill below can pick the fact block belonging to the
        # actually resolved model(s) instead of the first block found by
        # chance ordering. Fail-closed (section 492, Bug 2): a falsy model
        # is only kept when there is no target set at all.
        scoped_target_set = set(concept.resolved_models) if concept.resolved_models else None
        scoped_tool_observation_models = [
            model
            for obs, model in zip(tool_observations, tool_observation_models)
            if not scoped_target_set or (model and model in scoped_target_set)
        ]

        # H3 dedicated CONFLICTING path (todo/contexte.txt sections
        # 419-420): detected BEFORE any single-verdict backfill/correction
        # call, so a genuine cross-model disagreement is exposed as-is
        # rather than silently resolved toward one side.
        ci_conflict_reason = _detect_can_view_amount_model_conflict(
            scoped_tool_output,
            tool_observation_models=scoped_tool_observation_models,
            target_models=concept.resolved_models,
        )

        if ci_conflict_reason:
            final_answer = _format_conflicting_evidence_answer(
                scoped_tool_output,
                tool_observation_models=scoped_tool_observation_models,
                target_models=concept.resolved_models,
            ) or final_answer
        else:
            final_answer = _apply_backfill_chain(
                final_answer,
                scoped_tool_output,
                question,
                scoped_tool_observation_models=scoped_tool_observation_models,
                target_models=concept.resolved_models,
                raw_tool_output=raw_tool_output,
            )

    from code_intelligence.agent.dispatch_guards import (
        verify_citations, annotate_unverifiable_citations, substitute_or_strip_code_blocks,
    )
    # todo/contexte.txt section 870, todo/plan_4.1_citation_as_constraint.md:
    # runs BEFORE verify_citations -- a substituted block is now genuinely
    # covered by its own nearby citation, a stripped block is no longer a
    # fenced code block at all, so neither re-triggers uncited_code_blocks.
    final_answer = substitute_or_strip_code_blocks(final_answer)
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

    # Bloc P1 Tranche 2 (todo/contexte.txt section 405-408): post-analysis
    # verdict on THIS branch's own synthesized answer, evaluated before the
    # '[Source: ...]' footer/omission block are appended. Drives
    # core/graph.py's post-CI conditional edge -- never decided here, this
    # node only computes and reports the verdict.
    ci_evidence_sufficiency = assess_evidence_sufficiency(
        tool_observations, ctx.hop_count, final_answer,
        conflict_reason=ci_conflict_reason,
    )
    logger.info(
        "Node [code_intelligence_agent]: evidence sufficiency=%s (relevant=%d/%d) reasons=%s",
        ci_evidence_sufficiency.status.value, ci_evidence_sufficiency.relevant_observation_count,
        ci_evidence_sufficiency.total_observation_count, ci_evidence_sufficiency.reasons,
    )

    # todo/contexte.txt sections 485-486 (Chantier 1): a captured
    # execution exception is not a genuine absence of evidence --
    # core/graph.py::ci_evidence_decision() keeps this response on
    # format_output (never a silent fallback to generate()/RAG). Added
    # BEFORE the source suffix, never after (the suffix must stay last).
    if ci_evidence_sufficiency.has_execution_failure:
        final_answer += _EXECUTION_FAILURE_NOTICE

    final_answer = _strip_truncation_marker_for_display(final_answer, source_label="final_answer (synthese)")

    final_answer += "\n\n[Source: Graphe de Connaissances Code Intelligence]"

    seen_omitted_keys: set = set()
    deduped_omitted_items = []
    for item in ctx.omitted_items:
        key = (item.label, item.reason)
        if key not in seen_omitted_keys:
            seen_omitted_keys.add(key)
            deduped_omitted_items.append(item)
    omitted_for_authorization = [
        OmittedForAuthorization(label=item.label, reason=item.reason)
        for item in deduped_omitted_items
    ]
    if omitted_for_authorization:
        omission_lines = chr(10).join(f"  - {o.label} : {o.reason}" for o in omitted_for_authorization)
        final_answer += (
            "\n\n[ACCES RESTREINT] \u00c9L\u00c9MENT(S) OMIS POUR RAISON D'AUTORISATION:\n"
            + omission_lines
        )

    # Build sources from tool observations -- one SourceReference per tool
    # call, with the FULL observation text as snippet, so the dépliant
    # ("Niveau Vérification & Preuves") can show the real deterministic
    # evidence instead of it being duplicated into the main answer text.
    sources = []
    for obs, model, tname in zip(tool_observations, tool_observation_models, tool_observation_tools):
        if not obs or not str(obs).strip():
            continue
        display_tool = _CI_TOOL_DISPLAY_NAMES.get(tname, tname or "outil inconnu")
        title = f"{display_tool} — {model}" if model else display_tool
        sources.append(SourceReference(
            source=f"code_intelligence:{tname or 'unknown'}:{model or 'unknown'}",
            doc_type="code_graph",
            title=title,
            snippet=_strip_truncation_marker_for_display(str(obs), source_label=f"{tname or 'unknown'}({model or 'unknown'})"),
        ))

    response = AssistantResponse(
        answer=final_answer,
        sources=sources,
        confidence=1.0 if tool_observations else 0.5,
        omitted_for_authorization=omitted_for_authorization,
    )

    ci_total_wall = time.time() - start_time
    timing = state.get("timing", {}).copy()
    timing["code_intelligence_time"] = ci_total_wall
    timing["ci_hop_count"] = ctx.hop_count
    timing["ci_groq_wait_time"] = round(ctx.groq_wait, 3)
    timing["ci_effective_time"] = round(ci_total_wall - ctx.groq_wait, 3)
    timing["ci_business_resolver_time"] = round(resolver_time, 3)
    timing["ci_per_hop_times"] = [round(t, 3) for t in ctx.per_hop_times]
    timing["ci_synthesis_time"] = round(ctx.synthesis_time, 3)
    timing["llm_call_count"] = ctx.llm_call_count

    ctx.trace_logger.log_summary(
        trace_id=ctx.trace_id, branch="code_intelligence", question=question,
        hop_count=ctx.hop_count, llm_call_count=ctx.llm_call_count,
        total_time_ms=ci_total_wall * 1000, hop_cap=ctx.hop_cap,
    )

    return {
        "response": response,
        "raw_answer": final_answer,
        "timing": timing,
        "raw_tool_output": "\n\n".join(tool_observations),
        "evidence_status": evidence_status,
        "ci_evidence_sufficiency": ci_evidence_sufficiency.to_display_dict(),
    }
