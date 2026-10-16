"""Resolution step: technical model or module names quoted verbatim in the question."""

from typing import Optional

from ..matching import (
    ResolvedConcept,
    _find_exact_technical_model_mentions,
    _find_exact_technical_module_mentions,
    rank_by_specificity,
)


def _models_declared_by(G, modules) -> list:
    models = []
    for module in modules:
        module_node = f"module:{module}"
        if not G.has_node(module_node):
            continue
        for predecessor in G.predecessors(module_node):
            if (
                predecessor.startswith("model:")
                and G.edges[predecessor, module_node].get("role", "declares") == "declares"
            ):
                model = predecessor.removeprefix("model:")
                if model not in models:
                    models.append(model)
    return models


def resolve_exact_mention(clean_query: str, query_text: str, G) -> Optional[ResolvedConcept]:
    """Resolve literal model/module mentions."""
    exact_mentions = _find_exact_technical_model_mentions(clean_query, G, include_symbol_inference=False)
    exact_modules = _find_exact_technical_module_mentions(clean_query, G)
    if not exact_mentions and not exact_modules:
        # A technical button/method owned by a single model is a literal mention of it;
        # a symbol shared by several models stays ambiguous and is left to retrieval.
        inferred_mentions = _find_exact_technical_model_mentions(clean_query, G, include_symbol_inference=True)
        if len(inferred_mentions) == 1:
            exact_mentions = inferred_mentions
    if len(exact_mentions) > 1:
        exact_mentions = rank_by_specificity(exact_mentions, clean_query)
    if not exact_mentions and not exact_modules:
        return None
    if exact_modules and not exact_mentions and G is not None:
        exact_mentions = _models_declared_by(G, exact_modules)

    reasons = []
    if exact_mentions:
        reasons.append(f"Exact technical model name(s) mentioned verbatim: {', '.join(exact_mentions)}")
    if exact_modules:
        reasons.append(f"Exact technical module name(s) mentioned verbatim: {', '.join(exact_modules)}")
    user_term_parts = list(exact_mentions) + list(exact_modules)
    return ResolvedConcept(
        user_term=", ".join(user_term_parts) or query_text,
        resolved_models=exact_mentions,
        resolved_modules=exact_modules,
        confidence=1.0,
        source_step="exact_technical_mention",
        is_resolved=True,
        reason="; ".join(reasons),
    )
