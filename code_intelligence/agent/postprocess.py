"""
code_intelligence/ci_agent_node/postprocess.py

Post-ReAct-loop pipeline: out-of-scope/dynamic-uncertainty overrides,
cross-model conflict detection, the backfill/correction chain, sourcing
verification, evidence-sufficiency assessment, and final AssistantResponse
assembly.
"""

import logging
import re
import time
from dataclasses import asdict
from typing import List, Optional

from core.schemas import AssistantResponse, SourceReference, OmittedForAuthorization
from core.evidence.evidence_sufficiency import assess_evidence_sufficiency
from core.evidence.source_refs import CODE_GRAPH_DOC_TYPE, format_code_graph_source
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
    _backfill_missing_implied_ids_mechanism,
    _backfill_missing_group_escalation_note,
)
from code_intelligence.rules.security_locks import (
    _backfill_missing_security_lock_amount,
    _backfill_missing_approval_guard_facts,
    _backfill_fiscal_lock_scope_fact,
    _correct_security_lock_threshold_contradictions,
)
from code_intelligence.rules.access_evaluator import _correct_access_permission_contradictions
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
    _build_dynamic_uncertainty_answer,
)
from code_intelligence.rules.overrides import (
    _backfill_missing_override_modules,
    _backfill_missing_override_chain_amount,
    _correct_override_cascade_contradictions,
    _backfill_missing_unguarded_super,
)
from code_intelligence.rules.structure import (
    _correct_module_extension_contradiction,
    _backfill_missing_module_extension_details,
    _strip_irrelevant_inheritance_constraints,
)
from code_intelligence.rules.workflow import (
    _correct_noop_hook_hallucinations,
    _backfill_action_confirm_workflow_details,
    _backfill_confirmation_lock_fact,
    _backfill_backorder_policy_facts,
    _backfill_stage_recurrence_conditions,
)
from code_intelligence.rules.button_path import (
    correct_button_role_contradictions,
    correct_button_visibility_contradictions,
)
from code_intelligence.rules.data_constraints import (
    backfill_missing_bounds_facts,
    backfill_missing_conditional_check_facts,
    enforce_sql_constraint_fidelity,
)
from code_intelligence.agent.context import _EXECUTION_FAILURE_NOTICE, _CI_TOOL_DISPLAY_NAMES
from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.provenance import source_footer

logger = logging.getLogger(__name__)

_UNEXPECTED_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_UNSOURCED_EXAMPLE_RE = re.compile(
    r"^\s*(?:(?:\*\*)?(?:exemple|example)(?:\*\*)?\s*:|#{1,6}\s+(?:exemple|example)\b)",
    re.IGNORECASE,
)


def _strip_unexpected_script_sentences(text: str) -> str:
    """Remove prose sentences containing a script that conflicts with the question language."""
    lines = []
    for line in text.splitlines():
        if not _UNEXPECTED_HAN_RE.search(line):
            lines.append(line)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", line)
        lines.extend(sentence for sentence in sentences if not _UNEXPECTED_HAN_RE.search(sentence))
    return "\n".join(lines)


def _strip_unsourced_examples(final_answer: str, raw_tool_output: str) -> str:
    """Drop generated example blocks when no example is supplied as evidence."""
    if re.search(r"\b(?:exemple|example)\b", raw_tool_output, re.IGNORECASE):
        return final_answer
    blocks = re.split(r"\n\s*\n", final_answer)
    return "\n\n".join(
        block for block in blocks if not _UNSOURCED_EXAMPLE_RE.match(block)
    ).strip()


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
    constraint_tool_output: str = "",
    applied_guards: Optional[List[str]] = None,
) -> str:
    """Run every backfill/correction guard in order. When `applied_guards` is given,
    the name of each guard that actually changed the answer is appended to it."""
    raw_or_scoped = raw_tool_output or scoped_tool_output
    scoped_or_raw = scoped_tool_output or raw_tool_output
    constraint_source = constraint_tool_output or scoped_tool_output or raw_tool_output
    # Section 840: list_involved_modules' MODULE-mode evidence is recorded under
    # the module name, never under the resolved MODEL name, so scoped_tool_output
    # never contains it. The module-extension guards therefore read the unscoped
    # raw output; the denial check still runs against final_answer, so no
    # cross-model contamination is possible.
    steps = [
        (_correct_security_lock_threshold_contradictions, (scoped_tool_output, question), {}),
        (_correct_access_permission_contradictions, (scoped_tool_output,), {}),
        (
            _backfill_missing_can_view_amount_fact,
            (scoped_tool_output,),
            {"tool_observation_models": scoped_tool_observation_models, "target_models": target_models},
        ),
        (_backfill_missing_required_groups, (scoped_tool_output, question), {}),
        (_backfill_missing_implied_ids_mechanism, (scoped_or_raw, question), {}),
        (_backfill_missing_group_escalation_note, (scoped_or_raw, question), {}),
        (_backfill_missing_security_lock_amount, (scoped_tool_output,), {"question": question}),
        (_backfill_missing_approval_guard_facts, (raw_or_scoped, question), {}),
        (_backfill_fiscal_lock_scope_fact, (raw_or_scoped, question), {}),
        (correct_button_role_contradictions, (raw_or_scoped,), {}),
        (correct_button_visibility_contradictions, (raw_or_scoped,), {}),
        (_backfill_missing_override_modules, (scoped_tool_output,), {"question": question}),
        (_correct_override_cascade_contradictions, (scoped_tool_output,), {}),
        (_correct_module_extension_contradiction, (raw_or_scoped,), {"question": question}),
        (_backfill_missing_module_extension_details, (raw_or_scoped,), {"question": question}),
        (_backfill_missing_override_chain_amount, (scoped_tool_output,), {}),
        (_backfill_missing_trigger_condition_literals, (scoped_tool_output,), {}),
        (_backfill_missing_hardcoded_id_literals, (scoped_tool_output,), {}),
        (_backfill_missing_unguarded_super, (scoped_tool_output,), {}),
        (_backfill_link_guard_clarifications, (scoped_tool_output,), {"question": question}),
        (_correct_can_view_amount_contradictions, (), {}),
        (_correct_noop_hook_hallucinations, (raw_or_scoped,), {"question": question}),
        (_backfill_action_confirm_workflow_details, (raw_or_scoped,), {"question": question}),
        (_backfill_confirmation_lock_fact, (raw_or_scoped,), {"question": question}),
        (_backfill_backorder_policy_facts, (raw_or_scoped,), {"question": question}),
        (_backfill_stage_recurrence_conditions, (raw_or_scoped,), {"question": question}),
        (backfill_missing_conditional_check_facts, (constraint_source,), {"question": question}),
        (backfill_missing_bounds_facts, (constraint_source,), {"question": question}),
        (_flag_ungrounded_group_xmlids, (scoped_tool_output,), {}),
        (_strip_core_only_group_mentions, (scoped_tool_output,), {}),
        (_strip_irrelevant_inheritance_constraints, (), {"question": question}),
        (enforce_sql_constraint_fidelity, (constraint_source, question), {}),
    ]
    for guard, args, kwargs in steps:
        updated = guard(final_answer, *args, **kwargs)
        if updated != final_answer:
            logger.info(
                "Node [code_intelligence_agent]: guard '%s' modified the answer (%d -> %d chars).",
                guard.__name__, len(final_answer), len(updated),
            )
            if applied_guards is not None:
                applied_guards.append(guard.__name__)
        final_answer = updated
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
    dynamic_uncertainty_answer = _build_dynamic_uncertainty_answer(raw_tool_output)
    ci_conflict_reason = None
    applied_guards: List[str] = []
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
        constraint_tool_output = "\n\n".join(
            obs
            for obs, tool_name in zip(tool_observations, tool_observation_tools)
            if tool_name == "analyze_data_constraints"
        )

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
                constraint_tool_output=constraint_tool_output,
                applied_guards=applied_guards,
            )

    from code_intelligence.agent.dispatch_guards import (
        verify_citations, annotate_unverifiable_citations, substitute_or_strip_code_blocks,
    )
    # todo/contexte.txt section 870, todo/plan_4.1_citation_as_constraint.md:
    # runs BEFORE verify_citations -- a substituted block is now genuinely
    # covered by its own nearby citation, a stripped block is no longer a
    # fenced code block at all, so neither re-triggers uncited_code_blocks.
    final_answer = substitute_or_strip_code_blocks(final_answer)
    # Section 1027: strip fabricated file:// links whose path contains the
    # prompt's example placeholder '...' -- the LLM sometimes copies them
    # verbatim. Removing before verify_citations prevents a cascading
    # SOURCING NON VÉRIFIÉ warning for a non-existent path.
    final_answer = re.sub(
        r"\[([^\]]*)\]\(file:///\.\.\.[^)]*\)",
        r"\1",
        final_answer,
    )
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

    final_answer = _strip_unexpected_script_sentences(final_answer)
    final_answer = _strip_unsourced_examples(final_answer, raw_tool_output)

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

    # Strip any accidental 'Preuves' or 'Sources' markdown section emitted by the LLM,
    # as technical proofs are already encapsulated in response.sources for the frontend dépliant.
    final_answer = re.sub(
        r"\n+(?:---\s*\n+)?(?:#{1,4}\s+)?(?:Preuves|Sources)\s*[:\n][\s\S]*$",
        "",
        final_answer,
        flags=re.IGNORECASE,
    ).strip()

    final_answer = _strip_truncation_marker_for_display(final_answer, source_label="final_answer (synthese)")

    final_answer += "\n\n" + source_footer(ci_evidence_sufficiency)

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
            source=format_code_graph_source(tname, model),
            doc_type=CODE_GRAPH_DOC_TYPE,
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
    timing["ci_llm_wait_time"] = round(ctx.llm_wait, 3)
    timing["ci_effective_time"] = round(ci_total_wall - ctx.llm_wait, 3)
    timing["ci_business_resolver_time"] = round(resolver_time, 3)
    timing["ci_per_hop_times"] = [round(t, 3) for t in ctx.per_hop_times]
    timing["ci_synthesis_time"] = round(ctx.synthesis_time, 3)
    timing["ci_applied_guards"] = applied_guards
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
        "loop_resolved_concept": asdict(concept),
        "ci_evidence_sufficiency": ci_evidence_sufficiency.to_display_dict(),
    }
