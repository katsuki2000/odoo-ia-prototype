"""Resolution step: static business alias lookup."""

from typing import Optional

from ..matching import ResolvedConcept
from .alias_targets import alias_targets_in_graph


def resolve_static_alias(clean_query: str, G, aliases, alias_patterns) -> Optional[ResolvedConcept]:
    """Resolve business aliases to graph models or modules; targets absent from a loaded graph are dropped."""
    matched_models = []
    matched_modules = []
    matched_terms = []

    matched_aliases = [
        alias for alias in aliases
        if alias_patterns[alias].search(clean_query)
    ]
    if len(matched_aliases) > 1:
        matched_aliases = [
            a for a in matched_aliases
            if not any(a != b and a in b for b in matched_aliases)
        ]
        matched_aliases.sort(key=lambda a: (len(a.split()), len(a)), reverse=True)

    for alias in matched_aliases:
        targets_to_add = alias_targets_in_graph(G, aliases[alias])
        if not targets_to_add:
            continue
        matched_terms.append(alias)
        for t in targets_to_add:
            if G is not None and G.has_node(f"module:{t}") and not G.has_node(f"model:{t}"):
                if t not in matched_modules:
                    matched_modules.append(t)
            else:
                if t not in matched_models:
                    matched_models.append(t)

    if matched_models or matched_modules:
        return ResolvedConcept(
            user_term=", ".join(matched_terms),
            resolved_models=matched_models,
            resolved_modules=matched_modules,
            confidence=1.0,
            source_step="static_alias",
            is_resolved=True,
            reason=f"Matched static aliases: {', '.join(matched_terms)}",
        )
    return None
