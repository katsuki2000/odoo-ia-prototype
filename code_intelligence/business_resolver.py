"""
code_intelligence/business_resolver.py

Business Term to Technical Symbol Resolver.
Maps natural language functional concepts to technical graph nodes (models, fields, modules).
"""

import logging
from typing import Dict, List, Optional, Tuple, Set

from code_intelligence.business_aliases import (
    BUSINESS_ALIASES,
    NATIVE_MODEL_SYNONYMS,
    _nfc,
    BUSINESS_ALIASES_NFC,
    _ALIAS_PATTERNS,
)

from code_intelligence.business_resolver_matching import (
    ResolvedConcept,
    _FUZZY_INDEX_CACHE,
    _build_fuzzy_index,
    _GENERIC_FIELD_NAMES,
    _find_exact_technical_model_mentions,
    _find_exact_technical_module_mentions,
    _specificity_score,
    rank_by_specificity,
    _fuzzy_match_graph,
)

from code_intelligence.business_resolver_arbitration import (
    AMBIGUITY_GAP_THRESHOLD,
    WIDENED_CANDIDATE_THRESHOLD,
    WIDENED_CANDIDATE_LIMIT,
    _ARBITRATION_SYSTEM_PROMPT,
    _build_arbitration_prompt,
    _llm_arbitrate,
)

_logger = logging.getLogger(__name__)


def resolve_business_term(query_text: str, G=None, llm=None, active_model: Optional[str] = None) -> ResolvedConcept:
    """Resolve a natural language query into a technical Odoo model/module."""
    if not query_text:
        return ResolvedConcept(
            user_term="",
            is_resolved=False,
            reason="Empty query text provided.",
        )

    clean_query = _nfc(query_text.lower().strip())

    exact_mentions = _find_exact_technical_model_mentions(clean_query, G)
    exact_modules = _find_exact_technical_module_mentions(clean_query, G)
    if len(exact_mentions) > 1:
        exact_mentions = rank_by_specificity(exact_mentions, clean_query)
    if exact_mentions or exact_modules:
        if exact_modules:
            matched_aliases = [
                alias for alias in BUSINESS_ALIASES_NFC
                if _ALIAS_PATTERNS[alias].search(clean_query)
            ]
            alias_models = []
            for alias in matched_aliases:
                for t in BUSINESS_ALIASES_NFC[alias]:
                    if t not in alias_models and t not in exact_mentions:
                        if G is not None:
                            is_in_mod = any(
                                G.has_edge(f"model:{t}", f"module:{mod}") or f"model:{t}" in G.predecessors(f"module:{mod}")
                                for mod in exact_modules if G.has_node(f"module:{mod}")
                            )
                            if is_in_mod:
                                alias_models.append(t)
                        else:
                            alias_models.append(t)
            if alias_models:
                if not exact_mentions:
                    exact_mentions = alias_models
                else:
                    exact_mentions.extend(alias_models)
            elif not exact_mentions and G is not None:
                mod_models = []
                for mod in exact_modules:
                    mod_node = f"module:{mod}"
                    if G.has_node(mod_node):
                        for u in G.predecessors(mod_node):
                            if u.startswith("model:"):
                                m_name = u.replace("model:", "")
                                if m_name not in mod_models:
                                    mod_models.append(m_name)
                if mod_models:
                    exact_mentions = mod_models

        user_term_parts = list(exact_mentions) + list(exact_modules)
        reasons = []
        if exact_mentions:
            reasons.append(f"Exact technical model name(s) mentioned verbatim: {', '.join(exact_mentions)}")
        if exact_modules:
            reasons.append(f"Exact technical module name(s) mentioned verbatim: {', '.join(exact_modules)}")
        return ResolvedConcept(
            user_term=query_text if not user_term_parts else ", ".join(user_term_parts),
            resolved_models=exact_mentions,
            resolved_modules=exact_modules,
            confidence=1.0,
            source_step="exact_technical_mention",
            is_resolved=True,
            reason="; ".join(reasons),
        )

    # Step 1: Static Business Alias Lookup
    matched_models = []
    matched_modules = []
    matched_terms = []

    matched_aliases = [
        alias for alias in BUSINESS_ALIASES_NFC
        if _ALIAS_PATTERNS[alias].search(clean_query)
    ]
    if len(matched_aliases) > 1:
        matched_aliases = [
            a for a in matched_aliases
            if not any(a != b and a in b for b in matched_aliases)
        ]
        matched_aliases.sort(key=lambda a: (len(a.split()), len(a)), reverse=True)

    for alias in matched_aliases:
        targets = BUSINESS_ALIASES_NFC[alias]
        matched_terms.append(alias)
        if G is not None and G.number_of_nodes() > 0:
            existing_in_g = [
                t for t in targets
                if G.has_node(f"model:{t}") or G.has_node(f"module:{t}")
            ]
            is_alternatives = (
                len(targets) == 2
                and any(t.startswith("custom.") for t in targets)
                and not all(t.startswith("custom.") for t in targets)
            )
            if is_alternatives and existing_in_g:
                targets_to_add = [existing_in_g[0]]
            else:
                targets_to_add = existing_in_g if existing_in_g else targets
        else:
            targets_to_add = targets

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

    # Step 1.5: Ambient UI context fallback
    if active_model and G is not None and G.has_node(f"model:{active_model}"):
        return ResolvedConcept(
            user_term=query_text,
            resolved_models=[active_model],
            confidence=0.9,
            source_step="active_context",
            is_resolved=True,
            reason=f"No textual match in the question itself; resolved from active UI context (model={active_model})",
        )

    # Step 2: Fuzzy matching against Graph Node labels
    if G is not None:
        fuzzy_results = _fuzzy_match_graph(clean_query, G)
        if fuzzy_results:
            top_models = [model for model, _score in fuzzy_results]
            top_score = fuzzy_results[0][1]

            is_ambiguous = (
                len(fuzzy_results) >= 2
                and (fuzzy_results[0][1] - fuzzy_results[1][1]) < AMBIGUITY_GAP_THRESHOLD
            )

            if not is_ambiguous:
                return ResolvedConcept(
                    user_term=query_text,
                    resolved_models=top_models,
                    confidence=round(top_score / 100, 2),
                    source_step="fuzzy_graph_match",
                    is_resolved=True,
                    reason=f"Fuzzy matched graph labels: {', '.join(f'{m} ({s:.0f})' for m, s in fuzzy_results)}",
                )

            # Step 3: Bounded LLM Candidate Selection
            chosen = _llm_arbitrate(query_text, top_models, llm)
            if chosen is not None:
                return ResolvedConcept(
                    user_term=query_text,
                    resolved_models=[chosen],
                    confidence=0.6,
                    source_step="llm_arbitration",
                    is_resolved=True,
                    reason=(
                        f"LLM arbitration among ambiguous fuzzy candidates "
                        f"({', '.join(f'{m} ({s:.0f})' for m, s in fuzzy_results)}) -> chose '{chosen}'. "
                        f"Low-confidence LLM interpretation, not a certain structural fact."
                    ),
                )

            return ResolvedConcept(
                user_term=query_text,
                is_resolved=False,
                confidence=0.0,
                source_step="unresolved",
                reason=(
                    f"Ambiguous fuzzy candidates "
                    f"({', '.join(f'{m} ({s:.0f})' for m, s in fuzzy_results)}) "
                    f"and LLM arbitration did not select one."
                ),
            )
        else:
            widened_results = _fuzzy_match_graph(
                clean_query, G,
                threshold=WIDENED_CANDIDATE_THRESHOLD,
                limit=WIDENED_CANDIDATE_LIMIT,
            )
            if widened_results:
                widened_models = [model for model, _score in widened_results]
                chosen = _llm_arbitrate(query_text, widened_models, llm)
                if chosen is not None:
                    return ResolvedConcept(
                        user_term=query_text,
                        resolved_models=[chosen],
                        confidence=0.5,
                        source_step="llm_arbitration_widened",
                        is_resolved=True,
                        reason=(
                            f"No candidate reached the strict fuzzy threshold; widened "
                            f"low-threshold candidates "
                            f"({', '.join(f'{m} ({s:.0f})' for m, s in widened_results)}) "
                            f"-> LLM chose '{chosen}'. Low-confidence LLM interpretation "
                            f"over a weak candidate shortlist, not a certain structural fact."
                        ),
                    )

    # Step 4: Unresolved concept fallback
    return ResolvedConcept(
        user_term=query_text,
        is_resolved=False,
        confidence=0.0,
        source_step="unresolved",
        reason="No business alias or graph model match found.",
    )


__all__ = [
    "BUSINESS_ALIASES",
    "NATIVE_MODEL_SYNONYMS",
    "_nfc",
    "BUSINESS_ALIASES_NFC",
    "_ALIAS_PATTERNS",
    "ResolvedConcept",
    "_FUZZY_INDEX_CACHE",
    "_build_fuzzy_index",
    "_GENERIC_FIELD_NAMES",
    "_find_exact_technical_model_mentions",
    "_find_exact_technical_module_mentions",
    "_specificity_score",
    "rank_by_specificity",
    "_fuzzy_match_graph",
    "AMBIGUITY_GAP_THRESHOLD",
    "WIDENED_CANDIDATE_THRESHOLD",
    "WIDENED_CANDIDATE_LIMIT",
    "_ARBITRATION_SYSTEM_PROMPT",
    "_build_arbitration_prompt",
    "_llm_arbitrate",
    "resolve_business_term",
]
