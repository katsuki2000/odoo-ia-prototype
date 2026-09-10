"""
code_intelligence/ci_agent_node/module_inference.py

Shared helper for inferring the most relevant custom module(s) declaring/
extending a set of resolved models, ranked by lexical overlap with the
question. Extracted from the former ci_agent_node.py monolith, where this
exact computation was duplicated verbatim in two places (resolved_info
business-context block, and the inheritance pre-dispatch's module-target
fallback) -- refactor, see todo/contexte.txt. Behavior unchanged.
"""

import re
from typing import Any, List


def rank_custom_modules_for_models(G: Any, resolved_models: List[str], question: str) -> List[str]:
    """Return custom modules declaring/extending resolved_models, ranked by
    lexical overlap with the question (most relevant first). Empty list if
    none found or G is None."""
    if G is None:
        return []
    from .tool_helpers import _is_custom_module_filepath

    all_custom_mods = []
    for rm in resolved_models:
        if not G.has_node(f"model:{rm}"):
            continue
        rm_mods = set()
        for v in G.neighbors(f"model:{rm}"):
            if v.startswith("module:"):
                mod_data = G.nodes[v]
                fp = mod_data.get("filepath", "")
                if _is_custom_module_filepath(fp):
                    rm_mods.add(v.replace("module:", ""))
        if rm_mods:
            all_custom_mods.append(rm_mods)

    if not all_custom_mods:
        return []

    common_mods = set.intersection(*all_custom_mods) if len(all_custom_mods) > 1 else all_custom_mods[0]
    candidate_mods = list(common_mods if common_mods else all_custom_mods[0])
    q_words = set(re.findall(r"\w+", question.lower()))

    def _mod_rank(m):
        parts = set(m.split("_"))
        return (len(parts.intersection(q_words)), len(m))

    candidate_mods.sort(key=_mod_rank, reverse=True)
    return candidate_mods
