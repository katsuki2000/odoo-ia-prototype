"""
code_intelligence/ci_agent_node/predispatch_access.py

Deterministic pre-dispatch of 'who_has_access_to' for access-related
questions -- skips models already governed by a more specific
analyze_security_locks finding (Python has_group() lock beats the generic
CRUD ACL matrix). Extracted from the former ci_agent_node.py monolith
(refactor, see todo/contexte.txt). Behavior unchanged.
"""

import logging
import time
from typing import List

from code_intelligence.rules.security_locks import gate_observation
from code_intelligence.agent.context import (
    _truncate_observation_for_budget,
    _tool_call_key,
    PER_TOOL_OBSERVATION_CAPS,
)
from code_intelligence.agent.context_extractors import _question_is_access_related
from code_intelligence.agent.context import DispatchContext

logger = logging.getLogger(__name__)


def dispatch_who_has_access_to(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved and ctx.concept.resolved_models
        and _question_is_access_related(ctx.question)
        and not ctx.hop_budget_exhausted
    ):
        return

    # Section 861 (2a): predicate matched -- the question's category was
    # recognized, this dispatcher is taking over routing for it (does not
    # imply the tool call below will succeed, only that routing was not
    # silently left open to free ReAct for this predicate's category).
    ctx.matched_dispatchers.append("dispatch_who_has_access_to")

    from .forced_dispatch_predicates import security_locks_targets, who_has_access_targets

    acl_tool = ctx.tool_map.get("who_has_access_to")
    if acl_tool is None:
        return

    _lock_governed_models = set(security_locks_targets(ctx.concept, ctx.G))
    skipped_lock_governed_models: List[str] = [
        m for m in ctx.concept.resolved_models if m in _lock_governed_models
    ]
    for target_model in skipped_lock_governed_models:
        logger.info(
            "Node [code_intelligence_agent]: skipping deterministic "
            "who_has_access_to dispatch for '%s' -- a real Python security "
            "lock (has_group()) already governs this model's actions, "
            "more specific than the generic CRUD ACL matrix.",
            target_model,
        )

    # Bloc P1 Jour 6 (todo/contexte.txt section 210): which models to
    # actually dispatch on is decided by the same shared predicate the
    # Investigation Planner uses, instead of a second, separately
    # maintained exclusion loop reaching the same result.
    for target_model in who_has_access_targets(ctx.question, ctx.concept, ctx.G)[:1]:
        call_key = _tool_call_key("who_has_access_to", {"model_name": target_model})
        if call_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            observation = str(acl_tool.invoke({
                "model_name": target_model, "permission": "all",
            }))
            # Section 894: was a hardcoded 3000 (silently below the real
            # worst case, see PER_TOOL_OBSERVATION_CAPS's comment in
            # context.py) -- reads the single source of truth directly so
            # this call site cannot drift from the dict again.
            observation = _truncate_observation_for_budget(
                ctx, observation, PER_TOOL_OBSERVATION_CAPS["who_has_access_to"],
            )
            observation, omitted_list = gate_observation(
                tool_name="who_has_access_to",
                model_name=target_model,
                observation=observation,
                G=ctx.G,
                user_groups=ctx.resolved_user_group_xmlids,
            )
            ctx.omitted_items.extend(omitted_list)
            ctx.record_observation(
                "who_has_access_to", {"model_name": target_model, "permission": "all"},
                observation, target_model, call_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'who_has_access_to' for model '%s' (question asks who can/has the "
                "right to do something).",
                target_model,
            )
            if ctx.hop_budget_exhausted:
                logger.warning(
                    "Node [code_intelligence_agent]: CI_MAX_HOPS (%d) reached during "
                    "deterministic pre-dispatch (who_has_access_to) -- breaking.",
                    ctx.hop_cap,
                )
                break
        except Exception as te:
            logger.error("Deterministic who_has_access_to dispatch failed: %s", te)

    if any(k[0] == "who_has_access_to" for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            "who_has_access_to has already been run for the target model(s) above "
            "because the question asks who can/has the right to do something; its "
            "ACL and record-rule output is already included in the tool "
            "observations. Do not call it again."
        )
    if skipped_lock_governed_models:
        ctx.system_prompt_suffix += (
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


"""
code_intelligence/ci_agent_node/predispatch_record_rules.py

Deterministic pre-dispatch of 'evaluate_record_rules', followed by an
injected 'can_view_amount_v2' deterministic fact when the question names an
amount. Extracted from the former ci_agent_node.py monolith (refactor, see
todo/contexte.txt). Behavior unchanged.
"""

import json as _json_dispatch
import logging
import time

from code_intelligence.rules.security_locks import gate_observation
from code_intelligence.agent.context import (
    _truncate_observation_for_budget,
    _tool_call_key,
)
from code_intelligence.agent.context_extractors import (
    _question_is_access_related,
    _extract_amount,
    _extract_company_context,
    _infer_move_type_context,
)
from code_intelligence.agent.can_view_verifier import _format_can_view_amount_fact
from code_intelligence.agent.context import DispatchContext

logger = logging.getLogger(__name__)


def dispatch_evaluate_record_rules(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved and ctx.concept.resolved_models
        and _question_is_access_related(ctx.question)
        and not ctx.hop_budget_exhausted
    ):
        return

    # Section 861 (2a): predicate matched -- the question's category was
    # recognized, this dispatcher is taking over routing for it (does not
    # imply the tool call below will succeed, only that routing was not
    # silently left open to free ReAct for this predicate's category).
    ctx.matched_dispatchers.append("dispatch_evaluate_record_rules")

    from code_intelligence.agent.tools import evaluate_rules_raw

    amount_for_rules = _extract_amount(ctx.question)
    rule_tool = ctx.tool_map.get("evaluate_record_rules")
    if rule_tool is None:
        return

    for target_model in ctx.concept.resolved_models[:1]:
        call_key = _tool_call_key("evaluate_record_rules", {"model_name": target_model})
        if call_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            dispatch_groups = _json_dispatch.dumps(ctx.resolved_user_group_xmlids or [])
            observation = str(rule_tool.invoke({
                "model_name": target_model,
                "user_groups_json": dispatch_groups,
                "permission": "read",
            }))
            observation = _truncate_observation_for_budget(ctx, observation, 3000)
            observation, omitted_list = gate_observation(
                tool_name="evaluate_record_rules",
                model_name=target_model,
                observation=observation,
                G=ctx.G,
                user_groups=ctx.resolved_user_group_xmlids,
            )
            ctx.omitted_items.extend(omitted_list)
            ctx.record_observation(
                "evaluate_record_rules",
                {"model_name": target_model, "permission": "read"},
                observation, target_model, call_key, time.perf_counter() - t0,
            )

            if amount_for_rules is not None:
                try:
                    dispatch_rule_result = evaluate_rules_raw(
                        model_name=target_model,
                        permission="read",
                        user_groups_json=dispatch_groups,
                    )
                    dispatch_context = {"amount": amount_for_rules}
                    dispatch_context.update(_extract_company_context(ctx.question))
                    dispatch_context.update(_infer_move_type_context(ctx.concept))
                    dispatch_can_view, dispatch_unresolved = (
                        dispatch_rule_result.can_view_amount_v2(dispatch_context)
                    )
                    ctx.tool_observations.append(
                        _format_can_view_amount_fact(
                            amount_for_rules, dispatch_can_view, dispatch_unresolved
                        )
                    )
                    ctx.tool_observation_models.append(target_model)
                    ctx.tool_observation_tools.append("can_view_amount_v2")
                    logger.info(
                        "Node [code_intelligence_agent]: Pre-dispatch "
                        "can_view_amount_v2 fact for model=%s, amount=%.0f, "
                        "result=%s, unresolved=%s, context=%s, "
                        "global=%d, group=%d.",
                        target_model, amount_for_rules, dispatch_can_view,
                        dispatch_unresolved, dispatch_context,
                        len(dispatch_rule_result.applied_global_rules),
                        len(dispatch_rule_result.applied_group_rules),
                    )
                except Exception as ve:
                    logger.error("Pre-dispatch can_view_amount_v2 injection failed: %s", ve)

            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'evaluate_record_rules' for model '%s' (access/rules-related question).",
                target_model,
            )
            if ctx.hop_budget_exhausted:
                logger.warning(
                    "Node [code_intelligence_agent]: CI_MAX_HOPS (%d) reached during "
                    "deterministic pre-dispatch (evaluate_record_rules) -- breaking.",
                    ctx.hop_cap,
                )
                break
        except Exception as te:
            logger.error("Deterministic evaluate_record_rules dispatch failed: %s", te)

    if any(k and k[0] == "evaluate_record_rules" for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            "evaluate_record_rules has already been run for the target "
            "model(s) above and the can_view_amount_v2 deterministic fact has been "
            "injected. Do not call evaluate_record_rules again."
        )


"""
code_intelligence/ci_agent_node/predispatch_security_locks.py

Deterministic pre-dispatch of 'analyze_security_locks' when the resolved
concept targets model(s) and the question isn't inheritance-related.
Extracted from the former ci_agent_node.py monolith (refactor, see
todo/contexte.txt). Behavior unchanged.
"""

import logging
import time

from code_intelligence.rules.security_locks import gate_observation
from code_intelligence.agent.context import (
    _truncate_observation_for_budget,
    _tool_call_key,
)
from code_intelligence.agent.context_extractors import _question_is_inheritance_related
from code_intelligence.agent.context import DispatchContext

logger = logging.getLogger(__name__)


def dispatch_security_locks(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved and ctx.concept.resolved_models
        and not ctx.hop_budget_exhausted
        and not _question_is_inheritance_related(ctx.question)
    ):
        return

    # Section 861 (2a): predicate matched -- the question's category was
    # recognized, this dispatcher is taking over routing for it (does not
    # imply the tool call below will succeed, only that routing was not
    # silently left open to free ReAct for this predicate's category).
    ctx.matched_dispatchers.append("dispatch_security_locks")

    from .forced_dispatch_predicates import security_locks_targets

    lock_tool = ctx.tool_map.get("analyze_security_locks")
    if lock_tool is None:
        return

    for target_model in security_locks_targets(ctx.concept, ctx.G)[:1]:
        call_key = _tool_call_key("analyze_security_locks", {"model_name": target_model})
        if call_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            observation = str(lock_tool.invoke({"model_name": target_model}))
            observation = _truncate_observation_for_budget(ctx, observation, 3000)
            observation, omitted_list = gate_observation(
                tool_name="analyze_security_locks",
                model_name=target_model,
                observation=observation,
                G=ctx.G,
                user_groups=ctx.resolved_user_group_xmlids,
            )
            ctx.omitted_items.extend(omitted_list)
            ctx.record_observation(
                "analyze_security_locks", {"model_name": target_model},
                observation, target_model, call_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'analyze_security_locks' for model '%s' (structural lock finding present).",
                target_model,
            )
            if ctx.hop_budget_exhausted:
                logger.warning(
                    "Node [code_intelligence_agent]: CI_MAX_HOPS (%d) reached during "
                    "deterministic pre-dispatch (analyze_security_locks) -- breaking.",
                    ctx.hop_cap,
                )
                break
        except Exception as te:
            logger.error("Deterministic analyze_security_locks dispatch failed: %s", te)

    if any(k[0] == "analyze_security_locks" for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            "analyze_security_locks has already been run for the target model(s) above "
            "because the question is approval/security-related; its output is already included "
            "in the tool observations. Do not call it again -- focus any further tool calls on "
            "what it does NOT cover (e.g. ir.rule / group-based record visibility via "
            "evaluate_record_rules)."
        )


"""
code_intelligence/ci_agent_node/predispatch_security_distinction.py

Deterministic pre-dispatch chain for security-distinction questions
("qu'est-ce qui distingue reellement group A de group B") --
describe_workflow -> button_execution_path -> read_source_code -- so the
real approval/confirmation method name is discovered from the workflow
graph instead of guessed by the LLM (todo/contexte.txt section 782: the
LLM guessed 'action_confirm', which does not exist, instead of the real
'button_confirm'), and the method body is always read via
read_source_code instead of stopping at a button-level "no restriction"
summary that never exposes an internal Python guard call (section 782).
Complements, does not replace, the mid-loop textual reminder in
dispatch_guards.py::_maybe_build_application_layer_reminder (section
779/781), which remains the fallback when this block finds no
approval-like transition method. New block (section 784), following the
same auto-follow-citation pattern as dispatch_server_actions/
dispatch_override_chain (predispatch_actions.py).
"""

import logging
import re
import time

from code_intelligence.agent.context import (
    _truncate_observation_for_budget,
    _tool_call_key,
)
from code_intelligence.agent.context_extractors import _question_is_security_distinction_related
from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.tool_helpers import _resolve_model_param
from code_intelligence.rules.button_path import button_execution_path as _button_execution_path_impl
from code_intelligence.rules.override_unguarded import resolve_method_override_chain
from core.evidence.evidence_collector import record_evidence

logger = logging.getLogger(__name__)

# Method name pattern matched against describe_workflow's "Method: `xxx()`"
# lines. Restricted to the real Odoo naming convention for approval/
# confirmation buttons (button_confirm/button_approve/button_validate...)
# rather than a bare 'confirm|approve|valid' substring match: verified
# empirically on purchase.order (section 784) that a substring match alone
# also catches 'confirm_reminder_mail' (an unrelated reminder-email method,
# not button-bound to any approval semantics), which would waste hop
# budget on an irrelevant candidate.
_WORKFLOW_METHOD_RE = re.compile(r"Method:\s*`([A-Za-z_][A-Za-z0-9_]*)\(\)`")
_APPROVAL_BUTTON_METHOD_RE = re.compile(r"^button_(?:confirm|approve|valid)", re.IGNORECASE)


def dispatch_security_distinction_guard(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved and ctx.concept.resolved_models
        and _question_is_security_distinction_related(ctx.question)
        and not ctx.hop_budget_exhausted
    ):
        return

    # Section 861 (2a): predicate matched -- the question's category was
    # recognized, this dispatcher is taking over routing for it (does not
    # imply the tool call below will succeed, only that routing was not
    # silently left open to free ReAct for this predicate's category).
    ctx.matched_dispatchers.append("dispatch_security_distinction_guard")

    wf_tool = ctx.tool_map.get("describe_workflow")
    btn_tool = ctx.tool_map.get("button_execution_path")
    if wf_tool is None or btn_tool is None:
        return

    ran_any_button = False
    any_guard_resolved = False

    for target_model in ctx.concept.resolved_models:
        if ctx.hop_budget_exhausted:
            break

        wf_call_key = _tool_call_key("describe_workflow", {"model_name": target_model})
        wf_observation = None
        if wf_call_key in ctx.seen_calls:
            # Reuse the observation already fetched by dispatch_describe_workflow
            # (or an earlier target_model iteration below) this turn -- no
            # re-invocation, no double hop count.
            for _obs, _tool_name, _model in zip(
                ctx.tool_observations, ctx.tool_observation_tools, ctx.tool_observation_models
            ):
                if _tool_name == "describe_workflow" and _model == target_model:
                    wf_observation = _obs
                    break
        if wf_observation is None:
            t0 = time.perf_counter()
            try:
                wf_observation = str(wf_tool.invoke({"model_name": target_model}))
                wf_observation = _truncate_observation_for_budget(ctx, wf_observation, 3000)
                ctx.record_observation(
                    "describe_workflow", {"model_name": target_model},
                    wf_observation, target_model, wf_call_key, time.perf_counter() - t0,
                )
                logger.info(
                    "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                    "'describe_workflow' for model '%s' (security-distinction "
                    "question -- discovering real approval/confirmation method "
                    "names before any button_execution_path call).",
                    target_model,
                )
            except Exception as te:
                logger.error(
                    "Deterministic describe_workflow dispatch (security-distinction) failed: %s", te
                )
                continue

        seen_methods = set()
        candidate_methods = []
        for m in _WORKFLOW_METHOD_RE.findall(wf_observation):
            if m in seen_methods:
                continue
            seen_methods.add(m)
            if _APPROVAL_BUTTON_METHOD_RE.match(m):
                candidate_methods.append(m)

        guard_resolved = False
        for method_name in candidate_methods:
            if ctx.hop_budget_exhausted:
                break
            btn_call_key = _tool_call_key(
                "button_execution_path", {"model_name": target_model, "button_name": method_name}
            )
            if btn_call_key in ctx.seen_calls:
                continue
            t0 = time.perf_counter()
            try:
                # todo/contexte.txt section 831 (Famille 1, site 5/5): was
                # `re.search(r"\((file:///[^#\)]+)#L(\d+)-L(\d+)\)", observation)`,
                # re-parsing our own formatted tool text for the called method's
                # file/line -- see the analogous fix and comment in
                # predispatch_structure.py::dispatch_button_execution_path
                # (same tool, same ButtonExecutionPathResult.method_filepath/
                # method_lineno/method_end_lineno structured fields).
                button_result = _button_execution_path_impl(
                    ctx.G, method_name, _resolve_model_param(target_model),
                    user_groups=ctx.resolved_user_group_xmlids or [],
                )
                record_evidence(button_result.evidence)
                observation = button_result.summary_text + "\n" + "\n".join(button_result.execution_steps)
                observation = _truncate_observation_for_budget(ctx, observation, 3000)
                ctx.record_observation(
                    "button_execution_path",
                    {"button_name": method_name, "model_name": target_model},
                    observation, target_model, btn_call_key, time.perf_counter() - t0,
                )
                ran_any_button = True
                logger.info(
                    "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                    "'button_execution_path' for real method '%s' on model '%s' "
                    "(security-distinction question, name discovered via "
                    "describe_workflow, never guessed).",
                    method_name, target_model,
                )
                _read_obs = None
                if button_result.method_filepath and not ctx.hop_budget_exhausted:
                    read_tool = ctx.tool_map.get("read_source_code")
                    if read_tool is not None:
                        _fp = button_result.method_filepath
                        _ls = button_result.method_lineno
                        _le = button_result.method_end_lineno
                        _read_key = ("read_source_code", _fp, _ls, _le)
                        if _read_key not in ctx.seen_calls:
                            try:
                                _t_read = time.perf_counter()
                                _read_obs = str(read_tool.invoke({
                                    "filepath": _fp, "line_start": _ls, "line_end": _le,
                                }))
                                _read_obs = _truncate_observation_for_budget(ctx, _read_obs, 4000)
                                ctx.record_observation(
                                    "read_source_code",
                                    {"filepath": _fp, "line_start": _ls, "line_end": _le},
                                    _read_obs, target_model, _read_key, time.perf_counter() - _t_read,
                                )
                                logger.info(
                                    "Node [code_intelligence_agent]: Deterministic follow-up "
                                    "dispatch of 'read_source_code' for '%s' lines %d-%d "
                                    "(security-distinction application-guard verification).",
                                    _fp, _ls, _le,
                                )
                            except Exception as re_err:
                                logger.error(
                                    "Deterministic read_source_code dispatch "
                                    "(security-distinction) failed: %s", re_err,
                                )
                        # Follow an internal guard call found inside the button's own
                        # body (e.g. `order._approval_allowed()`) instead of moving on
                        # to the next candidate button -- the guard's own definition,
                        # not the calling button's body, is what carries the real
                        # distinction (todo/contexte.txt section 786: read_source_code
                        # on button_confirm alone only shows the guard being called,
                        # never its body, and a 2nd button_execution_path call then
                        # exhausts the hop budget before the guard is ever resolved).
                        if _read_obs and not ctx.hop_budget_exhausted:
                            _guard_match = re.search(r"\b(_\w*_allowed|_check_\w*)\s*\(", _read_obs)
                            if _guard_match:
                                guard_name = _guard_match.group(1)
                                # Pure graph lookup (code_intelligence/rules/override_unguarded.py),
                                # no LLM, no heuristic risk analysis, no hop cost -- resolves the
                                # guard method's own file/line location directly, so the single hop
                                # spent below goes straight to a literal read_source_code of the
                                # guard's body (todo/contexte.txt section 788: analyze_method_override_chain
                                # was tried first but never reproduces the method's own condition logic --
                                # it only returns structural-risk heuristics -- and its own file:// link
                                # was never auto-followed, wasting a 2nd hop for nothing).
                                guard_sites = resolve_method_override_chain(ctx.G, target_model, guard_name)
                                if guard_sites:
                                    _gs = guard_sites[0]
                                    read_tool = ctx.tool_map.get("read_source_code")
                                    if read_tool is not None and _gs.filepath and _gs.lineno:
                                        _g_le = _gs.end_lineno or _gs.lineno
                                        guard_read_key = ("read_source_code", _gs.filepath, _gs.lineno, _g_le)
                                        if guard_read_key not in ctx.seen_calls:
                                            try:
                                                _t_guard = time.perf_counter()
                                                guard_observation = str(read_tool.invoke({
                                                    "filepath": _gs.filepath,
                                                    "line_start": _gs.lineno,
                                                    "line_end": _g_le,
                                                }))
                                                guard_observation = _truncate_observation_for_budget(ctx, guard_observation, 2200)
                                                ctx.record_observation(
                                                    "read_source_code",
                                                    {"filepath": _gs.filepath, "line_start": _gs.lineno, "line_end": _g_le},
                                                    guard_observation, target_model, guard_read_key,
                                                    time.perf_counter() - _t_guard,
                                                )
                                                logger.info(
                                                    "Node [code_intelligence_agent]: Deterministic follow-up "
                                                    "dispatch of 'read_source_code' for guard '%s.%s' "
                                                    "(internal guard call found inside '%s', security-distinction "
                                                    "application-guard body resolution, via pure graph lookup).",
                                                    target_model, guard_name, method_name,
                                                )
                                                guard_resolved = True
                                            except Exception as guard_err:
                                                logger.error(
                                                    "Deterministic read_source_code dispatch "
                                                    "(security-distinction guard follow-up) failed: %s", guard_err,
                                                )
            except Exception as te:
                logger.error(
                    "Deterministic button_execution_path dispatch (security-distinction) failed: %s", te
                )
            if guard_resolved:
                any_guard_resolved = True
                # Real application-layer guard found and resolved -- no need to
                # spend further hops on the remaining button candidates.
                break

    if ran_any_button:
        _guard_note = (
            " Its own definition (the literal condition logic) has already been "
            "fetched above via a direct read_source_code lookup -- rely on that "
            "exact source, do not re-derive, summarize away, or ignore its "
            "condition logic in favor of a simpler button-level group restriction."
            if any_guard_resolved
            else ""
        )
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            "This question compares permissions between two roles/groups. Beyond "
            "the ACL/ir.rule observations above, the real approval/confirmation "
            "method's execution path (and its source code) has already been "
            "fetched above via describe_workflow + button_execution_path + "
            "read_source_code -- do not guess a button/method name and do not "
            "call these tools again. If the source code shows an internal guard "
            "call (e.g. a method named like _*_allowed()/_check_*()), that guard, "
            "not the ACL/ir.rule matrix, is the real distinction between the two "
            "groups compared in the question." + _guard_note
        )
