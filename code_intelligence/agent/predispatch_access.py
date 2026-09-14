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
    _truncate_observation,
    _tool_call_key,
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
            observation = _truncate_observation(observation, 3000)
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
    _truncate_observation,
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
            observation = _truncate_observation(observation, 3000)
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
    _truncate_observation,
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
            observation = _truncate_observation(observation, 3000)
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
