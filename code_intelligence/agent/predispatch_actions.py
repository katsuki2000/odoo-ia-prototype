"""
code_intelligence/ci_agent_node/predispatch_server_actions.py

Deterministic pre-dispatch of 'analyze_server_actions', plus an automatic
follow-up 'read_source_code' for every file:// link its output cites.
Extracted from the former ci_agent_node.py monolith (refactor, see
todo/contexte.txt). Behavior unchanged.
"""

import logging
import time

from code_intelligence.rules.security_locks import gate_observation
from code_intelligence.agent.tools.analysis import _compose_server_actions_observation
from code_intelligence.agent.context import (
    _truncate_observation_for_budget,
    _tool_call_key,
)
from code_intelligence.agent.context import DispatchContext, PER_TOOL_OBSERVATION_CAPS

logger = logging.getLogger(__name__)


def dispatch_server_actions(ctx: DispatchContext) -> None:
    if not (ctx.concept.is_resolved and ctx.concept.resolved_models and not ctx.hop_budget_exhausted):
        return

    # Section 861 (2a): predicate matched -- the question's category was
    # recognized, this dispatcher is taking over routing for it (does not
    # imply the tool call below will succeed, only that routing was not
    # silently left open to free ReAct for this predicate's category).
    ctx.matched_dispatchers.append("dispatch_server_actions")

    from .forced_dispatch_predicates import server_actions_targets

    sa_tool = ctx.tool_map.get("analyze_server_actions")
    if sa_tool is None:
        return

    for target_model in server_actions_targets(ctx.question, ctx.concept, ctx.G):
        call_key = _tool_call_key("analyze_server_actions", {"model_name": target_model})
        if call_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            # todo/contexte.txt section 831 (Famille 1, site 3/5): was
            # `re.findall(r"\((file:///[^#\)]+)#L(\d+)-L(\d+)\)", observation)`,
            # re-parsing our own formatted tool text for every invoked-method
            # citation -- _compose_server_actions_observation() is the shared
            # implementation behind the @tool (tools/analysis.py), returning
            # both the same text AND the structured (filepath, start, end)
            # citations _trace_invoked_methods_with_citations discovers while
            # building that text, from a single analysis pass (no duplicated
            # graph traversal, no text round-trip).
            observation, _citations = _compose_server_actions_observation(target_model)
            observation = _truncate_observation_for_budget(ctx, observation, 3000)
            observation, omitted_list = gate_observation(
                tool_name="analyze_server_actions",
                model_name=target_model,
                observation=observation,
                G=ctx.G,
                user_groups=ctx.resolved_user_group_xmlids,
            )
            ctx.omitted_items.extend(omitted_list)
            ctx.record_observation(
                "analyze_server_actions", {"model_name": target_model},
                observation, target_model, call_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'analyze_server_actions' for model '%s' (automation/bypass "
                "wording + ServerAction nodes present).",
                target_model,
            )
            for _fp, _ls, _le in _citations:
                if ctx.hop_budget_exhausted:
                    break
                _read_tool = ctx.tool_map.get("read_source_code")
                if _read_tool is None:
                    continue
                _read_key = ("read_source_code", _fp, _ls, _le)
                if _read_key in ctx.seen_calls:
                    continue
                try:
                    _t_read = time.perf_counter()
                    _read_obs = str(_read_tool.invoke({
                        "filepath": _fp, "line_start": _ls, "line_end": _le,
                    }))
                    _read_obs = _truncate_observation_for_budget(ctx, _read_obs, PER_TOOL_OBSERVATION_CAPS["read_source_code"])
                    ctx.record_observation(
                        "read_source_code",
                        {"filepath": _fp, "line_start": _ls, "line_end": _le},
                        _read_obs, target_model, _read_key, time.perf_counter() - _t_read,
                    )
                except Exception as re_err:
                    logger.error("Auto read_source_code after analyze_server_actions failed: %s", re_err)
            if ctx.hop_budget_exhausted:
                logger.warning(
                    "Node [code_intelligence_agent]: CI_MAX_HOPS (%d) reached during "
                    "deterministic pre-dispatch (analyze_server_actions) -- breaking.",
                    ctx.hop_cap,
                )
                break
        except Exception as te:
            logger.error("Deterministic analyze_server_actions dispatch failed: %s", te)

    if any(k[0] == "analyze_server_actions" for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            "analyze_server_actions has already been run for the target model(s) "
            "above because the question suggests automation/bypass logic; its output "
            "is already included in the tool observations. Do not call it again."
        )


"""
code_intelligence/ci_agent_node/predispatch_override_chain.py

Deterministic pre-dispatch of 'analyze_method_override_chain', plus an
automatic follow-up 'read_source_code' for the first file:// link its
output cites. Extracted from the former ci_agent_node.py monolith
(refactor, see todo/contexte.txt). Behavior unchanged.
"""

import logging
import time

from code_intelligence.rules.security_locks import gate_observation
from code_intelligence.rules.override_unguarded import resolve_method_override_chain
from code_intelligence.agent.tool_helpers import _resolve_model_param
from code_intelligence.agent.context import (
    _truncate_observation_for_budget,
    _tool_call_key,
)
from code_intelligence.agent.context import DispatchContext

logger = logging.getLogger(__name__)


def dispatch_override_chain(ctx: DispatchContext) -> None:
    if not (ctx.concept.is_resolved and ctx.concept.resolved_models and not ctx.hop_budget_exhausted):
        return

    # Section 861 (2a): predicate matched -- the question's category was
    # recognized, this dispatcher is taking over routing for it (does not
    # imply the tool call below will succeed, only that routing was not
    # silently left open to free ReAct for this predicate's category).
    ctx.matched_dispatchers.append("dispatch_override_chain")

    from .forced_dispatch_predicates import override_chain_targets

    override_tool = ctx.tool_map.get("analyze_method_override_chain")
    if override_tool is None:
        return

    for target_model, method_name in override_chain_targets(ctx.question, ctx.concept, ctx.G):
        call_key = _tool_call_key("analyze_method_override_chain", {"model_name": target_model, "method_name": method_name})
        if call_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            observation = str(override_tool.invoke({
                "model_name": target_model, "method_name": method_name,
            }))
            observation = _truncate_observation_for_budget(ctx, observation, 2200)
            observation, omitted_list = gate_observation(
                tool_name="analyze_method_override_chain",
                model_name=target_model,
                observation=observation,
                G=ctx.G,
                user_groups=ctx.resolved_user_group_xmlids,
            )
            ctx.omitted_items.extend(omitted_list)
            ctx.record_observation(
                "analyze_method_override_chain",
                {"model_name": target_model, "method_name": method_name},
                observation, target_model, call_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'analyze_method_override_chain' for '%s.%s' (approval wording "
                "+ real override cascade present).",
                target_model, method_name,
            )
            # todo/contexte.txt section 831 (Famille 1, site 2/5): was
            # `re.search(r"\((file:///[^#\)]+)#L(\d+)-L(\d+)\)", observation)`,
            # re-parsing our own formatted tool text for the first override
            # site's file/line -- resolve_method_override_chain() is the exact
            # graph lookup analyze_method_override_chain_with_evidence() calls
            # internally (override_composer.py), already exposed and already
            # used elsewhere for the same purpose (predispatch_access.py's
            # security-distinction guard resolution); its first site is, by
            # construction, the first entry the tool's text also lists (same
            # `sites` list, same order -- verified in override_composer.py's
            # `_compose_method_override_chain`), so no behavior change.
            _override_sites = resolve_method_override_chain(
                ctx.G, _resolve_model_param(target_model), method_name,
            )
            if _override_sites and not ctx.hop_budget_exhausted:
                _read_tool = ctx.tool_map.get("read_source_code")
                if _read_tool is not None:
                    sites_to_read = []
                    if ctx.concept.resolved_modules:
                        for s in _override_sites:
                            if any(f"/{m}/" in s.filepath for m in ctx.concept.resolved_modules):
                                sites_to_read.append(s)
                    if not sites_to_read:
                        base_site = _override_sites[-1]
                        sites_to_read.append(base_site)
                        if len(_override_sites) > 1 and _override_sites[0] != base_site:
                            sites_to_read.append(_override_sites[0])

                    for _site in sites_to_read:
                        if ctx.hop_budget_exhausted:
                            break
                        _fp = _site.filepath
                        _ls = _site.lineno
                        _le = _site.end_lineno or _site.lineno
                        _read_key = ("read_source_code", _fp, _ls, _le)
                        if _read_key in ctx.seen_calls:
                            continue
                        try:
                            _t_read = time.perf_counter()
                            _read_obs = str(_read_tool.invoke({
                                "filepath": _fp, "line_start": _ls, "line_end": _le,
                            }))
                            _read_obs = _truncate_observation_for_budget(ctx, _read_obs, PER_TOOL_OBSERVATION_CAPS["read_source_code"])
                            ctx.record_observation(
                                "read_source_code",
                                {"filepath": _fp, "line_start": _ls, "line_end": _le},
                                _read_obs, target_model, _read_key, time.perf_counter() - _t_read,
                            )
                            logger.info(
                                "Node [code_intelligence_agent]: Deterministic follow-up dispatch of "
                                "'read_source_code' for '%s' lines %d-%d.",
                                _fp, _ls, _le,
                            )
                        except Exception as _re:
                            logger.error("Deterministic read_source_code dispatch failed: %s", _re)
            if ctx.hop_budget_exhausted:
                logger.warning(
                    "Node [code_intelligence_agent]: CI_MAX_HOPS (%d) reached during "
                    "deterministic pre-dispatch (analyze_method_override_chain) -- breaking.",
                    ctx.hop_cap,
                )
                break
        except Exception as te:
            logger.error("Deterministic analyze_method_override_chain dispatch failed: %s", te)

    if any(k and k[0] == "analyze_method_override_chain" for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
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


"""
code_intelligence/ci_agent_node/predispatch_constraints.py

Deterministic pre-dispatch of 'analyze_data_constraints' for constraint-
related questions, plus an automatic follow-up 'read_source_code' around
any odoo-static-exclusion-filter finding. Extracted from the former
ci_agent_node.py monolith (refactor, see todo/contexte.txt). Behavior
unchanged.
"""

import logging
import time

from code_intelligence.rules.data_constraints import analyze_data_constraints_from_filepaths
from code_intelligence.agent.tool_helpers import find_model_source_filepaths, _resolve_model_param
from core.evidence.evidence_collector import record_evidence
from code_intelligence.agent.context import (
    _truncate_observation_for_budget,
    _tool_call_key,
)
from code_intelligence.agent.context_extractors import _question_is_constraint_related
from code_intelligence.agent.context import DispatchContext

logger = logging.getLogger(__name__)


def dispatch_analyze_data_constraints(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved and ctx.concept.resolved_models
        and _question_is_constraint_related(ctx.question)
        and not ctx.hop_budget_exhausted
    ):
        return

    # Section 861 (2a): predicate matched -- the question's category was
    # recognized, this dispatcher is taking over routing for it (does not
    # imply the tool call below will succeed, only that routing was not
    # silently left open to free ReAct for this predicate's category).
    ctx.matched_dispatchers.append("dispatch_analyze_data_constraints")

    constraint_tool = ctx.tool_map.get("analyze_data_constraints")
    if constraint_tool is None:
        return

    from .forced_dispatch_predicates import data_constraints_targets

    target_models = data_constraints_targets(ctx.concept, ctx.G, ctx.question)
    for target_model in target_models:
        call_key = _tool_call_key("analyze_data_constraints", {"model_name": target_model})
        if call_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            # todo/contexte.txt section 831 (Famille 1, site 1/5): was
            # `re.search(r"\(file://([^#\)]+)#L(\d+)-L(\d+)\)\s+\(odoo-static-
            # exclusion-filter\)", observation)`, re-parsing our own formatted
            # tool text for a finding whose filepath/start_line/end_line/
            # check_id are already structured fields on SemgrepMatch --
            # analyze_data_constraints_from_filepaths() is the exact function
            # the @tool wrapper calls internally (tools/analysis.py); calling
            # it directly here (instead of invoking the @tool and re-parsing
            # its text) gives both the observation text AND the structured
            # matches from a single analysis pass, no text round-trip, no
            # duplicated Semgrep run.
            resolved_model = _resolve_model_param(target_model)
            model_node = f"model:{resolved_model}"
            constraints_result = None
            if model_node not in ctx.G:
                observation = f"Model '{resolved_model}' was not found in the indexed knowledge graph."
            else:
                filepaths = find_model_source_filepaths(ctx.G, resolved_model)
                if not filepaths:
                    observation = f"No Python source files located for model '{resolved_model}'."
                else:
                    constraints_result = analyze_data_constraints_from_filepaths(resolved_model, filepaths)
                    record_evidence(constraints_result.evidence)
                    observation = constraints_result.summary_text
            observation = _truncate_observation_for_budget(ctx, observation, 45000)
            ctx.record_observation(
                "analyze_data_constraints", {"model_name": target_model},
                observation, target_model, call_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'analyze_data_constraints' for model '%s'.",
                target_model,
            )
            if constraints_result is not None and not ctx.hop_budget_exhausted:
                exclusion_matches = [
                    m for m in constraints_result.matches
                    if m.check_id == "odoo-static-exclusion-filter"
                ]
                if exclusion_matches:
                    match = exclusion_matches[0]
                    read_tool = ctx.tool_map.get("read_source_code")
                    if read_tool is not None:
                        fp = match.filepath
                        ls = max(1, match.start_line - 5)
                        le = match.end_line + 35
                        read_key = ("read_source_code", fp, ls, le)
                        if read_key not in ctx.seen_calls:
                            try:
                                t_read = time.perf_counter()
                                read_obs = str(read_tool.invoke({
                                    "filepath": fp, "line_start": ls, "line_end": le,
                                }))
                                read_obs = _truncate_observation_for_budget(ctx, read_obs, PER_TOOL_OBSERVATION_CAPS["read_source_code"])
                                ctx.record_observation(
                                    "read_source_code",
                                    {"filepath": fp, "line_start": ls, "line_end": le},
                                    read_obs, target_model, read_key, time.perf_counter() - t_read,
                                )
                            except Exception as re_err:
                                logger.error("Auto read_source_code after analyze_data_constraints failed: %s", re_err)
            if ctx.hop_budget_exhausted:
                break
        except Exception as te:
            logger.error("Deterministic analyze_data_constraints dispatch failed: %s", te)

    if any(k and k[0] == "analyze_data_constraints" for k in ctx.seen_calls):
        # Section 974 (todo/contexte.txt): this used to be an unconditional
        # "do not call again", which silently starved a genuinely different
        # model the resolver had not recognized (PUR-Q5: the question asks
        # about purchase.order.line's own SQL constraint, but the resolver
        # only resolved purchase.order -- the LLM correctly noticed the gap
        # itself for analyze_security_locks, calling it a second time for
        # the line model, but this instruction blocked it from doing the
        # same for analyze_data_constraints). Name the model(s) already
        # covered explicitly and only forbid repeating those, not the tool.
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            f"analyze_data_constraints has already been run for: {', '.join(target_models)}; "
            "its SQL uniqueness and relational domain rules for those models are already included "
            "in the tool observations -- do not call it again for any of them. If the question also "
            "concerns a distinct related model not listed above (e.g. a line/detail model of an order "
            "model already covered), you may call analyze_data_constraints once for that other model."
        )
