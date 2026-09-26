"""
code_intelligence/ci_agent_node/predispatch_inheritance.py

Deterministic pre-dispatch of 'trace_full_inheritance' and
'list_involved_modules' for inheritance-related questions, plus an
automatic follow-up 'read_source_code' for the most relevant file:// link
trace_full_inheritance cites. Extracted from the former ci_agent_node.py
monolith (refactor, see todo/contexte.txt). Behavior unchanged.
"""

import logging
import time

from code_intelligence.agent.context import (
    _truncate_observation_for_budget,
    _tool_call_key,
)
from code_intelligence.agent.context_extractors import _question_is_inheritance_related
from code_intelligence.agent.context import DispatchContext, PER_TOOL_OBSERVATION_CAPS
from code_intelligence.agent.context_extractors import rank_custom_modules_for_models
from code_intelligence.agent.tool_helpers import _resolve_model_param
from code_intelligence.agent.tools.introspection import list_involved_modules_with_evidence
from code_intelligence.rules.structure import trace_full_inheritance as _trace_full_inheritance_impl
from core.evidence.evidence_collector import record_evidence

logger = logging.getLogger(__name__)


def _dispatch_module_extensions_if_needed(ctx: DispatchContext, mod_name: str, target_model: str) -> None:
    if ctx.hop_budget_exhausted:
        return
    call_key = ("inspect_module_extensions", mod_name)
    if call_key in ctx.seen_calls:
        return
    from code_intelligence.rules.structure import (
        inspect_module_cross_domain_extensions,
        format_module_cross_domain_extensions,
    )
    t0 = time.perf_counter()
    try:
        exts = inspect_module_cross_domain_extensions(ctx.G, mod_name)
        obs = format_module_cross_domain_extensions(exts, mod_name)
        obs = _truncate_observation_for_budget(ctx, obs, 3000)
        ctx.record_observation(
            "inspect_module_extensions", {"module_name": mod_name},
            obs, target_model or mod_name, call_key, time.perf_counter() - t0,
        )
        logger.info(
            "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
            "'inspect_module_extensions' for module '%s'.",
            mod_name,
        )
    except Exception as ee:
        logger.error("Deterministic inspect_module_extensions dispatch failed for '%s': %s", mod_name, ee)


def dispatch_inheritance(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved
        and (ctx.concept.resolved_models or ctx.concept.resolved_modules)
        and _question_is_inheritance_related(ctx.question)
        and not ctx.hop_budget_exhausted
    ):
        return

    # Section 861 (2a): predicate matched -- the question's category was
    # recognized, this dispatcher is taking over routing for it (does not
    # imply the tool call below will succeed, only that routing was not
    # silently left open to free ReAct for this predicate's category).
    ctx.matched_dispatchers.append("dispatch_inheritance")

    inherit_tool = ctx.tool_map.get("trace_full_inheritance")
    mod_tool = ctx.tool_map.get("list_involved_modules")

    target_mods_to_inspect = list(ctx.concept.resolved_modules)
    if not target_mods_to_inspect:
        candidate_mods = rank_custom_modules_for_models(ctx.G, ctx.concept.resolved_models, ctx.question)
        if candidate_mods:
            target_mods_to_inspect.append(candidate_mods[0])

    for t_mod in target_mods_to_inspect:
        if ctx.hop_budget_exhausted:
            break
        if mod_tool is not None:
            call_key = ("list_involved_modules", t_mod)
            if call_key not in ctx.seen_calls:
                t0 = time.perf_counter()
                try:
                    observation = str(mod_tool.invoke({"model_name": t_mod}))
                    observation = _truncate_observation_for_budget(ctx, observation, 3000)
                    ctx.record_observation(
                        "list_involved_modules", {"model_name": t_mod},
                        observation, t_mod, call_key, time.perf_counter() - t0,
                    )
                    logger.info(
                        "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                        "'list_involved_modules' for module '%s'.",
                        t_mod,
                    )
                except Exception as te:
                    logger.error("Deterministic list_involved_modules dispatch for module failed: %s", te)
        _dispatch_module_extensions_if_needed(ctx, t_mod, t_mod)

    for target_model in ctx.concept.resolved_models:
        if inherit_tool is not None and not ctx.hop_budget_exhausted:
            call_key = _tool_call_key("trace_full_inheritance", {"model_name": target_model})
            if call_key not in ctx.seen_calls:
                t0 = time.perf_counter()
                try:
                    # todo/contexte.txt section 831 (Famille 1, site 4/5): was
                    # `re.findall(r"\((file:///[^#\)]+)#L(\d+)-L(\d+)\)", observation)`
                    # followed by a custom-module-priority `chosen_link` search,
                    # re-parsing our own formatted tool text for a declaration
                    # site whose (filepath, lineno, end_lineno) are already
                    # structured fields on InheritanceChainResult.declaration_sites
                    # -- calling trace_full_inheritance() directly (instead of
                    # invoking the @tool and re-parsing its text) gives both the
                    # observation text AND the structured, already custom-module-
                    # first-sorted declaration sites from a single analysis pass,
                    # no text round-trip, no duplicated file reads.
                    inheritance_result = _trace_full_inheritance_impl(
                        ctx.G, _resolve_model_param(target_model),
                    )
                    record_evidence(inheritance_result.evidence)
                    observation = inheritance_result.summary_text
                    observation = _truncate_observation_for_budget(ctx, observation, 3000)
                    ctx.record_observation(
                        "trace_full_inheritance", {"model_name": target_model},
                        observation, target_model, call_key, time.perf_counter() - t0,
                    )
                    logger.info(
                        "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                        "'trace_full_inheritance' for model '%s'.",
                        target_model,
                    )
                    chosen_site = None
                    if ctx.concept.resolved_modules:
                        for fp, ls, le in inheritance_result.declaration_sites:
                            if any(f"/{m}/" in fp for m in ctx.concept.resolved_modules):
                                chosen_site = (fp, ls, le)
                                break
                    if not chosen_site and inheritance_result.declaration_sites:
                        chosen_site = inheritance_result.declaration_sites[0]

                    if chosen_site:
                        _read_tool = ctx.tool_map.get("read_source_code")
                        if _read_tool is not None:
                            _fp, _ls, _le = chosen_site
                            try:
                                # NOTE: matches the original monolith exactly --
                                # this particular follow-up read does NOT cost a
                                # hop and is not added to seen_calls (unlike the
                                # analogous follow-ups in predispatch_server_
                                # actions.py/predispatch_override_chain.py).
                                # Preserved as-is (pure refactor, no behavior
                                # change); not something this mandate fixes.
                                _read_obs = str(_read_tool.invoke({
                                    "filepath": _fp,
                                    "line_start": _ls,
                                    "line_end": _le,
                                }))
                                _read_obs = _truncate_observation_for_budget(ctx, _read_obs, PER_TOOL_OBSERVATION_CAPS["read_source_code"])
                                ctx.tool_observations.append(_read_obs)
                                ctx.tool_observation_models.append(target_model)
                                ctx.tool_observation_tools.append("read_source_code")
                                ctx.trace_logger.log_hop(
                                    trace_id=ctx.trace_id, hop_index=ctx.hop_index,
                                    tool_name="read_source_code",
                                    tool_args={"filepath": _fp, "line_start": _ls, "line_end": _le},
                                    observation=_read_obs, elapsed_ms=0,
                                )
                                ctx.hop_index += 1
                            except Exception as re_err:
                                logger.error("Auto read_source_code after trace_full_inheritance failed: %s", re_err)
                except Exception as te:
                    logger.error("Deterministic trace_full_inheritance dispatch failed: %s", te)
        if mod_tool is not None and not ctx.concept.resolved_modules and not ctx.hop_budget_exhausted:
            call_key = _tool_call_key("list_involved_modules", {"model_name": target_model})
            if call_key not in ctx.seen_calls:
                t0 = time.perf_counter()
                try:
                    observation = str(mod_tool.invoke({"model_name": target_model}))
                    observation = _truncate_observation_for_budget(ctx, observation, 3000)
                    ctx.record_observation(
                        "list_involved_modules", {"model_name": target_model},
                        observation, target_model, call_key, time.perf_counter() - t0,
                    )
                    logger.info(
                        "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                        "'list_involved_modules' for model '%s'.",
                        target_model,
                    )
                    # todo/contexte.txt section 830: was `re.findall(r"(\S+) \(declares\)", observation)`,
                    # re-parsing our own formatted tool text (Family 1 anti-pattern --
                    # fragile to any wording/spacing change in list_involved_modules'
                    # text, even though the structured data it was built from is
                    # already available). list_involved_modules_with_evidence() is the
                    # exact same function the @tool wrapper calls internally to build
                    # `observation` in model mode (introspection.py's `_impl = ...`
                    # branch) -- calling it directly here returns the same (module,
                    # role) pairs with no text round-trip, so this is not a behavior
                    # change, only a removal of an unnecessary and fragile parse step.
                    declaring_modules = [
                        mod for mod, role in list_involved_modules_with_evidence(
                            ctx.G, _resolve_model_param(target_model),
                        ).modules
                        if role == "declares"
                    ]
                    for dec_mod in declaring_modules:
                        if ctx.hop_budget_exhausted:
                            break
                        mod_call_key = ("list_involved_modules", dec_mod)
                        if mod_call_key not in ctx.seen_calls:
                            t1 = time.perf_counter()
                            try:
                                mod_obs = str(mod_tool.invoke({"model_name": dec_mod}))
                                mod_obs = _truncate_observation_for_budget(ctx, mod_obs, 3000)
                                ctx.record_observation(
                                    "list_involved_modules", {"model_name": dec_mod},
                                    mod_obs, target_model, mod_call_key,
                                    time.perf_counter() - t1,
                                )
                                logger.info(
                                    "Node [code_intelligence_agent]: Deterministic "
                                    "pre-dispatch of 'list_involved_modules' in module "
                                    "mode for declaring module '%s'.",
                                    dec_mod,
                                )
                            except Exception as me:
                                logger.error(
                                    "Deterministic list_involved_modules module-mode "
                                    "dispatch failed for '%s': %s", dec_mod, me,
                                )
                        _dispatch_module_extensions_if_needed(ctx, dec_mod, target_model)
                except Exception as te:
                    logger.error("Deterministic list_involved_modules dispatch failed: %s", te)

    if any(k and k[0] in {"trace_full_inheritance", "list_involved_modules", "inspect_module_extensions"} for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH -- INHERITANCE & MODULE EXTENSIONS]\n"
            "trace_full_inheritance, list_involved_modules, and inspect_module_extensions have already been run for the "
            "target model(s) and declaring module(s) above; model hierarchy, mixins, declaring/extending modules, "
            "and out-of-perimeter model extensions (with their exact Python class names, files, fields, and methods) "
            "are already included in the tool observations. Do not call them again.\n"
            "IMPORTANT GUIDELINES FOR SYNTHESIS:\n"
            "1. If asked whether a target model is new or an extension, rely on trace_full_inheritance: if it declares "
            "a new _name and only inherits mixins, state clearly that it is a new model.\n"
            "2. If asked whether the declaring module extends any native models outside its perimeter/domain (or under "
            "what class name), rely strictly on the '[FAIT DÉTERMINISTIQUE -- EXTENSIONS DU MODULE HORS PÉRIMÈTRE]' "
            "observation. Do NOT claim that the module extends nothing outside its domain when extensions are listed, "
            "and cite the primary business model extended (e.g. account.move under class AccountMove for sales/invoicing) "
            "and its exact Python class name provided in the observation."
        )


"""
code_intelligence/ci_agent_node/predispatch_workflow.py

Deterministic pre-dispatch of 'describe_workflow' for workflow-related
questions. Extracted from the former ci_agent_node.py monolith (refactor,
see todo/contexte.txt). Behavior unchanged.
"""

import logging
import time

from code_intelligence.agent.context import (
    _truncate_observation_for_budget,
    _tool_call_key,
)
from code_intelligence.agent.context_extractors import _question_is_workflow_related
from code_intelligence.agent.context import DispatchContext
from code_intelligence.rules.override_unguarded import resolve_method_override_chain

logger = logging.getLogger(__name__)

# Section 911 (A): describe_workflow only analyzes `state`-field transitions
# (code_intelligence/rules/workflow.py) -- a model driven by stage_id/kanban
# stages instead (e.g. maintenance.request) always comes back with this exact
# marker, even when real automatic logic exists on stage change (todo/contexte.txt
# section 910/§5, 911: MNT-Q2, the LLM then guessed a plausible-but-wrong method
# name -- 'action_done', absent from the graph for this model -- instead of ever
# reading write(), where the real logic lives).
_WORKFLOW_EMPTY_MARKER = "has no explicit workflow state transitions defined"


def dispatch_describe_workflow(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved and ctx.concept.resolved_models
        and _question_is_workflow_related(ctx.question)
        and not ctx.hop_budget_exhausted
    ):
        return

    # Section 861 (2a): predicate matched -- the question's category was
    # recognized, this dispatcher is taking over routing for it (does not
    # imply the tool call below will succeed, only that routing was not
    # silently left open to free ReAct for this predicate's category).
    ctx.matched_dispatchers.append("dispatch_describe_workflow")

    wf_tool = ctx.tool_map.get("describe_workflow")
    if wf_tool is None:
        return

    empty_models = []

    for target_model in ctx.concept.resolved_models:
        call_key = _tool_call_key("describe_workflow", {"model_name": target_model})
        if call_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            observation = str(wf_tool.invoke({"model_name": target_model}))
            observation = _truncate_observation_for_budget(ctx, observation, 3000)
            ctx.record_observation(
                "describe_workflow", {"model_name": target_model},
                observation, target_model, call_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'describe_workflow' for model '%s'.",
                target_model,
            )
            if _WORKFLOW_EMPTY_MARKER in observation:
                empty_models.append(target_model)
            if ctx.hop_budget_exhausted:
                break
        except Exception as te:
            logger.error("Deterministic describe_workflow dispatch failed: %s", te)

    # Section 911 (A): relay to write() -- same resolve_method_override_chain
    # already used for the security-distinction guard follow-up (section
    # 784/786/788) -- so the LLM is never left alone with an empty workflow
    # observation and no lead beyond guessing a method name.
    read_tool = ctx.tool_map.get("read_source_code")
    for target_model in empty_models:
        if ctx.hop_budget_exhausted or read_tool is None:
            break
        write_sites = resolve_method_override_chain(ctx.G, target_model, "write")
        if not write_sites:
            continue
        site = write_sites[0]
        if not site.filepath or not site.lineno:
            continue
        end_lineno = site.end_lineno or site.lineno
        read_key = ("read_source_code", site.filepath, site.lineno, end_lineno)
        if read_key in ctx.seen_calls:
            continue
        t0 = time.perf_counter()
        try:
            read_observation = str(read_tool.invoke({
                "filepath": site.filepath, "line_start": site.lineno, "line_end": end_lineno,
            }))
            read_observation = _truncate_observation_for_budget(ctx, read_observation, PER_TOOL_OBSERVATION_CAPS["read_source_code"])
            from code_intelligence.rules.source_callees import read_method_source
            from code_intelligence.rules.workflow import (
                inspect_stage_workflow_actions,
                format_stage_workflow_note,
            )
            write_src = read_method_source(site.filepath, site.lineno, end_lineno) or ""
            actions = inspect_stage_workflow_actions(write_src)
            stage_note = format_stage_workflow_note(target_model, actions)
            if stage_note:
                read_observation += "\n\n" + stage_note
            ctx.record_observation(
                "read_source_code",
                {"filepath": site.filepath, "line_start": site.lineno, "line_end": end_lineno},
                read_observation, target_model, read_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic follow-up dispatch of "
                "'read_source_code' for '%s.write()' (%s L%d-%d) -- describe_workflow "
                "returned no state-field transitions for this model (section 911).",
                target_model, site.filepath, site.lineno, end_lineno,
            )
        except Exception as te:
            logger.error("Deterministic write() follow-up dispatch (section 911) failed: %s", te)

    if any(k and k[0] == "describe_workflow" for k in ctx.seen_calls):
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH]\n"
            "describe_workflow has already been run for the target model(s) above; "
            "its workflow state and transition structure is already included in the tool "
            "observations. Do not call describe_workflow again."
        )
    if empty_models:
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH -- STAGE-BASED MODEL(S)]\n"
            "describe_workflow found no explicit `state`-field transitions for: "
            + ", ".join(empty_models) + ". This kind of model is often driven by "
            "stage_id/kanban stages instead, which describe_workflow does not analyze. "
            "Any automatic logic triggered when a record reaches a given stage (e.g. "
            "duplication, recurrence, notifications) typically lives in write() -- its "
            "real source has already been fetched above via read_source_code where "
            "resolvable. Do NOT guess another method name (e.g. 'action_done') for "
            "these model(s), and do not call read_source_code again for their write(). "
            "For stage-driven recurrence, rely strictly on the '[FAIT DÉTERMINISTIQUE -- WORKFLOW D'ÉTAPE ET RÉCURRENCE (write())]' "
            "observation for any boundary conditions (such as repeat_type == 'forever' or schedule_date <= repeat_until). "
            "Do NOT claim that followers or notifications are sent upon reaching 'done' unless explicitly triggered by write()."
        )


"""
code_intelligence/ci_agent_node/predispatch_button.py

Deterministic pre-dispatch of 'button_execution_path' when the question
names a UI element (button/menu/field), plus an automatic follow-up
'read_source_code' for the file:// link its output cites. Extracted from
the former ci_agent_node.py monolith (refactor, see todo/contexte.txt).
Behavior unchanged.
"""

import logging
import time

from code_intelligence.agent.context import (
    _truncate_observation_for_budget,
    _tool_call_key,
)
from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.context_extractors import extract_ui_element_name, is_group_identifier
from code_intelligence.agent.tool_helpers import _resolve_model_param
from code_intelligence.rules.button_path import button_execution_path as _button_execution_path_impl
from code_intelligence.rules.override_unguarded import resolve_method_override_chain
from code_intelligence.rules.source_callees import (
    extract_followable_callees,
    extract_has_group_literals,
    read_method_source,
)
from code_intelligence.rules.technical_groups import format_technical_group_note, technical_groups_among
from core.evidence.evidence_collector import record_evidence

logger = logging.getLogger(__name__)

_MAX_FOLLOWED_CALLEES = 6


def dispatch_button_execution_path(ctx: DispatchContext) -> None:
    if not (ctx.concept.is_resolved and ctx.concept.resolved_models and not ctx.hop_budget_exhausted):
        return

    # Section 861 (2a): predicate matched -- the question's category was
    # recognized, this dispatcher is taking over routing for it (does not
    # imply the tool call below will succeed, only that routing was not
    # silently left open to free ReAct for this predicate's category).
    ctx.matched_dispatchers.append("dispatch_button_execution_path")

    ui_name = extract_ui_element_name(ctx.question)
    if not ui_name:
        return

    # Section 876: a security group is never a button/menu/field of a view.
    # The extractor already skips groups in its bare-parenthesis fallback;
    # this keeps any other extraction path from dispatching a group name.
    if is_group_identifier(ui_name):
        logger.info(
            "Node [code_intelligence_agent]: skipping 'button_execution_path' "
            "pre-dispatch, '%s' is a security group identifier, not a UI element.",
            ui_name,
        )
        return

    btn_tool = ctx.tool_map.get("button_execution_path")
    if btn_tool is None:
        return

    followed_any_callee = False

    for target_model in ctx.concept.resolved_models:
        call_key = _tool_call_key("button_execution_path", {"button_name": ui_name, "model_name": target_model})
        if call_key in ctx.seen_calls:
            continue
        try:
            t0 = time.perf_counter()
            # todo/contexte.txt section 831 (Famille 1, site 5/5): was
            # `re.search(r"\((file:///[^#\)]+)#L(\d+)-L(\d+)\)", observation)`,
            # re-parsing our own formatted tool text for the called method's
            # file/line -- button_execution_path()'s ButtonExecutionPathResult
            # now carries method_filepath/method_lineno/method_end_lineno as
            # structured fields, already computed locally wherever the result
            # is built (button_path.py's main path, and its XML-field/dynamic-
            # view/menu fallback paths in xml_view_finder.py/navigation.py) --
            # calling the rule function directly (instead of invoking the
            # @tool and re-parsing its text) gives both the observation text
            # AND these structured fields from a single analysis pass.
            button_result = _button_execution_path_impl(
                ctx.G, ui_name, _resolve_model_param(target_model),
                user_groups=ctx.resolved_user_group_xmlids or [],
            )
            record_evidence(button_result.evidence)
            observation = button_result.summary_text + "\n" + "\n".join(button_result.execution_steps)
            observation = _truncate_observation_for_budget(ctx, observation, 3000)
            ctx.record_observation(
                "button_execution_path",
                {"button_name": ui_name, "model_name": target_model},
                observation, target_model, call_key, time.perf_counter() - t0,
            )
            logger.info(
                "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                "'button_execution_path' for element '%s' on model '%s'.",
                ui_name, target_model,
            )
            _own_read_obs = None
            if button_result.method_filepath and not ctx.hop_budget_exhausted:
                read_tool = ctx.tool_map.get("read_source_code")
                if read_tool is not None:
                    fp = button_result.method_filepath
                    ls = button_result.method_lineno
                    le = button_result.method_end_lineno
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
                            _own_read_obs = read_obs
                        except Exception as re_err:
                            logger.error("Auto read_source_code after button_execution_path failed: %s", re_err)

            if _own_read_obs and not ctx.hop_budget_exhausted:
                _own_source = read_method_source(fp, ls, le) or ""
                _followed_count = 0
                for _called_name in extract_followable_callees(_own_source, button_result.method_name):
                    if ctx.hop_budget_exhausted or _followed_count >= _MAX_FOLLOWED_CALLEES:
                        break
                    _call_sites = resolve_method_override_chain(ctx.G, target_model, _called_name)
                    if not _call_sites:
                        continue
                    _declaring_mod = target_model.split(".")[0]
                    _cs = next((s for s in _call_sites if s.module == _declaring_mod), _call_sites[-1])
                    if not _cs.filepath or not _cs.lineno:
                        continue
                    _cs_end = _cs.end_lineno or _cs.lineno
                    _call_read_key = ("read_source_code", _cs.filepath, _cs.lineno, _cs_end)
                    if _call_read_key in ctx.seen_calls:
                        continue
                    read_tool = ctx.tool_map.get("read_source_code")
                    if read_tool is None:
                        break
                    try:
                        t_call = time.perf_counter()
                        _call_obs = str(read_tool.invoke({
                            "filepath": _cs.filepath, "line_start": _cs.lineno, "line_end": _cs_end,
                        }))
                        _call_obs = _truncate_observation_for_budget(ctx, _call_obs, PER_TOOL_OBSERVATION_CAPS["read_source_code"])
                        _technical_groups = technical_groups_among(
                            ctx.G,
                            extract_has_group_literals(
                                read_method_source(_cs.filepath, _cs.lineno, _cs_end) or ""
                            ),
                        )
                        if _technical_groups:
                            _call_obs += "\n" + format_technical_group_note(_technical_groups)
                        ctx.record_observation(
                            "read_source_code",
                            {"filepath": _cs.filepath, "line_start": _cs.lineno, "line_end": _cs_end},
                            _call_obs, target_model, _call_read_key, time.perf_counter() - t_call,
                        )
                        logger.info(
                            "Node [code_intelligence_agent]: Deterministic follow-up dispatch of "
                            "'read_source_code' for '%s.%s()' (%s L%d-%d), called from '%s'.",
                            target_model, _called_name, _cs.filepath, _cs.lineno, _cs_end,
                            button_result.method_name,
                        )
                        _followed_count += 1
                        followed_any_callee = True
                    except Exception as call_err:
                        logger.error("Deterministic callee follow-up dispatch failed: %s", call_err)
            if "not found" not in observation.lower():
                break
            if ctx.hop_budget_exhausted:
                break
        except Exception as te:
            logger.error("Deterministic button_execution_path dispatch failed: %s", te)

    if followed_any_callee:
        has_noop_hook = any("[NOTE DÉTERMINISTIQUE -- HOOK SANS EFFET / NO-OP]" in o for o in ctx.tool_observations)
        noop_guidance = (
            " If a called method is marked as a no-op hook (empty body or returning True/None without logic, "
            "e.g. validate_taxes_on_sales_order), do NOT claim that it validates, recalculates, or modifies anything: "
            "it performs NO default business logic in this module."
            if has_noop_hook else ""
        )
        ctx.system_prompt_suffix += (
            "\n\n[DETERMINISTIC PRE-DISPATCH -- CALLED METHODS]\n"
            "The method body above calls other methods of the same model (another button_* "
            "method, a method used as a condition, or a step it delegates to); their real "
            "definitions have already been fetched above via read_source_code. Rely on that exact "
            "source for what they do and on which record or user they evaluate; do not guess their "
            f"line range or call read_source_code again for them.{noop_guidance}"
        )


"""
code_intelligence/ci_agent_node/predispatch_module_ui.py

Deterministic pre-dispatch for module-level UI inquiries ("modifie-t-il une
vue", "ajoute-t-il un bouton", ...): runs 'list_involved_modules' then reads
the module's manifest to check for a views/ folder. Extracted from the
former ci_agent_node.py monolith (refactor, see todo/contexte.txt).
Behavior unchanged.
"""

import logging
import time
from pathlib import Path

from code_intelligence.agent.context import (
    _truncate_observation_for_budget,
)
from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.context_extractors import matches_module_level_ui_inquiry

logger = logging.getLogger(__name__)


def dispatch_module_level_ui_inquiry(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved and ctx.concept.resolved_modules
        and matches_module_level_ui_inquiry(ctx.question)
        and not ctx.hop_budget_exhausted
    ):
        return

    # Section 861 (2a): predicate matched -- the question's category was
    # recognized, this dispatcher is taking over routing for it (does not
    # imply the tool call below will succeed, only that routing was not
    # silently left open to free ReAct for this predicate's category).
    ctx.matched_dispatchers.append("dispatch_module_level_ui_inquiry")

    mod_tool = ctx.tool_map.get("list_involved_modules")
    read_tool = ctx.tool_map.get("read_source_code")

    for t_mod in ctx.concept.resolved_modules:
        if ctx.hop_budget_exhausted:
            break
        if mod_tool is not None:
            call_key = ("list_involved_modules", t_mod)
            if call_key not in ctx.seen_calls:
                t0 = time.perf_counter()
                try:
                    observation = str(mod_tool.invoke({"model_name": t_mod}))
                    observation = _truncate_observation_for_budget(ctx, observation, 3000)
                    ctx.record_observation(
                        "list_involved_modules", {"model_name": t_mod},
                        observation, t_mod, call_key, time.perf_counter() - t0,
                    )
                    logger.info(
                        "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                        "'list_involved_modules' for module '%s' in UI check.",
                        t_mod,
                    )
                except Exception as te:
                    logger.error("Deterministic list_involved_modules dispatch for module failed: %s", te)

        if ctx.G is not None and read_tool is not None and not ctx.hop_budget_exhausted:
            mod_data = ctx.G.nodes.get(f"module:{t_mod}", {})
            mod_manifest_fp = mod_data.get("filepath", "")
            if mod_manifest_fp and Path(mod_manifest_fp).exists():
                manifest_p = Path(mod_manifest_fp)
                read_key = ("read_source_code", str(manifest_p), 1, 40)
                if read_key not in ctx.seen_calls:
                    t0 = time.perf_counter()
                    try:
                        observation = str(read_tool.invoke({"filepath": str(manifest_p), "line_start": 1, "line_end": 40}))
                        observation = _truncate_observation_for_budget(ctx, observation, 4000)
                        views_dir = manifest_p.parent / "views"
                        if not views_dir.exists():
                            observation += (
                                f"\n\n[Module Structure]: Le dossier '{views_dir.name}/' "
                                f"n'existe pas dans le module '{t_mod}'. Aucune vue XML ni "
                                f"bouton declare."
                            )
                        ctx.record_observation(
                            "read_source_code",
                            {"filepath": str(manifest_p), "line_start": 1, "line_end": 40},
                            observation, t_mod, read_key, time.perf_counter() - t0,
                        )
                        logger.info(
                            "Node [code_intelligence_agent]: Deterministic pre-dispatch of "
                            "'read_source_code' for manifest of '%s' in UI check.",
                            t_mod,
                        )
                    except Exception as re_err:
                        logger.error("Auto read manifest in module UI check failed: %s", re_err)
