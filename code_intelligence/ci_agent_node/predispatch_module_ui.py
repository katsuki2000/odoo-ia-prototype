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

from .prompt_and_heuristics import _truncate_observation
from code_intelligence.ci_agent_node.dispatch_context import DispatchContext
from code_intelligence.ci_agent_node.ui_patterns import matches_module_level_ui_inquiry

logger = logging.getLogger(__name__)


def dispatch_module_level_ui_inquiry(ctx: DispatchContext) -> None:
    if not (
        ctx.concept.is_resolved and ctx.concept.resolved_modules
        and matches_module_level_ui_inquiry(ctx.question)
        and not ctx.hop_budget_exhausted
    ):
        return

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
                    observation = _truncate_observation(observation, 3000)
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
                        observation = _truncate_observation(observation, 4000)
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
