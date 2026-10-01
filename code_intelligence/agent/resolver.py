"""
code_intelligence/business_resolver/prompts.py

System prompts and template construction for bounded LLM arbitration over candidate Odoo models.
"""

from typing import Dict, List, Optional

_ARBITRATION_SYSTEM_PROMPT = (
    "Tu es un composant de résolution de symboles techniques Odoo. "
    "Tu dois choisir, parmi une liste fermée de modèles techniques candidats, "
    "celui qui correspond le mieux à la question métier posée ou indiquer "
    "qu'aucun ne convient. Tu ne dois JAMAIS proposer un nom de modèle en "
    "dehors de la liste fournie, même s'il te semble plus pertinent."
)

def _build_arbitration_prompt(
    query_text: str,
    candidates: List[str],
    candidate_contexts: Optional[Dict[str, str]] = None,
) -> str:
    """Build bounded arbitration prompt for selecting a candidate model."""
    candidates_block = "\n".join(
        f"- {candidate}" + (
            f" — {candidate_contexts[candidate]}"
            if candidate_contexts and candidate_contexts.get(candidate) else ""
        )
        for candidate in candidates
    )
    return (
        f'Question métier utilisateur : "{query_text}"\n\n'
        f"Modèles techniques Odoo candidats (extraits par correspondance approximative, "
        f"scores proches, ambigus) :\n{candidates_block}\n\n"
        "Réponds UNIQUEMENT avec le nom technique exact d'UN SEUL de ces modèles "
        "s'il correspond clairement à la question, ou UNIQUEMENT le mot NONE si "
        "aucun ne correspond clairement. Pas d'explication, pas de ponctuation, "
        "pas de modèle hors de cette liste."
    )


__all__ = [
    "_ARBITRATION_SYSTEM_PROMPT",
    "_build_arbitration_prompt",
]

# ── Arbitration ─────────────────────────────────────────────────────────

"""
code_intelligence/business_resolver_arbitration.py

Bounded LLM candidate arbitration over ambiguous or low-confidence fuzzy matches.
"""

import logging
from typing import Dict, List, Optional

_logger = logging.getLogger(__name__)

AMBIGUITY_GAP_THRESHOLD = 10.0
WIDENED_CANDIDATE_THRESHOLD = 30
WIDENED_CANDIDATE_LIMIT = 20

# from .prompts import _ARBITRATION_SYSTEM_PROMPT, _build_arbitration_prompt


def _llm_arbitrate(
    query_text: str,
    candidates: List[str],
    llm,
    candidate_contexts: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Bounded LLM candidate selection over a closed list."""
    if llm is None:
        _logger.warning("LLM arbitration requested but no llm client was provided; skipping.")
        return None

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        from core.llm.llm_client import get_chat_llm, invoke_with_rate_limit

        prompt = _build_arbitration_prompt(query_text, candidates, candidate_contexts)
        messages = [
            SystemMessage(content=_ARBITRATION_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        def _rebuild_arbitration_llm():
            return get_chat_llm(temperature=0.0, max_retries=0)

        response, _wait = invoke_with_rate_limit(
            llm, messages, rebuild_llm=_rebuild_arbitration_llm,
        )
        raw = (response.content or "").strip()
    except Exception:
        _logger.exception("LLM arbitration call failed for query=%r candidates=%r", query_text, candidates)
        return None

    if raw == "NONE":
        return None
    if raw in candidates:
        return raw

    _logger.warning("LLM arbitration returned an out-of-list value: %r (candidates=%r)", raw, candidates)
    return None

# ── Resolver ────────────────────────────────────────────────────────────

"""
code_intelligence/business_resolver.py

Business Term to Technical Symbol Resolver.
Maps natural language functional concepts to technical graph nodes (models, fields, modules).
"""

import logging
from typing import Dict, List, Optional, Tuple, Set

from .aliases import (
    BUSINESS_ALIASES,
    NATIVE_MODEL_SYNONYMS,
    _nfc,
    BUSINESS_ALIASES_NFC,
    _ALIAS_PATTERNS,
)

from .matching import (
    ResolvedConcept,
    _FUZZY_INDEX_CACHE,
    _build_fuzzy_index,
    _GENERIC_FIELD_NAMES,
    _find_exact_technical_model_mentions,
    _find_exact_technical_module_mentions,
    has_non_generic_field_mention,
    _specificity_score,
    rank_by_specificity,
    _fuzzy_match_graph,
)
from .semantic_retrieval import configured_semantic_model_candidates


_logger = logging.getLogger(__name__)

# Avoid generic 2-3 char words matching inside dotted model names.
_MIN_SEGMENT_LEN = 4


def _candidate_contexts(G, candidates: List[str], language: Optional[str]) -> Dict[str, str]:
    """Describe candidates with labels and declaring modules from the graph."""
    contexts = {}
    language_base = language.lower().split("_", 1)[0] if language else None
    for model in candidates:
        node_id = f"model:{model}"
        if not G.has_node(node_id):
            continue
        data = G.nodes[node_id]
        labels = []
        for label in data.get("business_labels", []):
            label_text = str(label.get("label") or "").strip()
            label_language = str(label.get("language") or "").lower()
            if not label_text or (language_base and label_language.split("_", 1)[0] != language_base):
                continue
            if label_text not in labels:
                labels.append(label_text)
        description = str(data.get("description") or "").strip()
        if description and description not in labels:
            labels.append(description)
        modules = sorted({
            successor.removeprefix("module:")
            for successor in G.successors(node_id)
            if G.edges[node_id, successor].get("edge_type") == "DEFINED_IN"
            and G.edges[node_id, successor].get("role", "declares") == "declares"
        })
        details = []
        if labels:
            details.append(f"labels: {', '.join(labels[:3])}")
        if modules:
            details.append(f"modules: {', '.join(modules)}")
        if details:
            contexts[model] = "; ".join(details)
    return contexts


def _arbitration_candidates(
    query: str,
    G,
    language: Optional[str],
    use_static_aliases: bool,
    use_semantic_retrieval: bool,
    fuzzy_results: Optional[List[Tuple[str, float]]] = None,
) -> List[str]:
    """Combine deterministic and optional semantic candidates for arbitration."""
    if fuzzy_results is None:
        fuzzy_results = _fuzzy_match_graph(
            query,
            G,
            limit=WIDENED_CANDIDATE_LIMIT,
            language=language,
            use_static_synonyms=use_static_aliases,
        )
    fuzzy_models = [model for model, _score in fuzzy_results]
    semantic_models = (
        configured_semantic_model_candidates(query, G, language)
        if use_semantic_retrieval else []
    )
    if not semantic_models:
        return fuzzy_models

    candidates = []
    fuzzy_budget = max(WIDENED_CANDIDATE_LIMIT - len(semantic_models), 0)
    for model in fuzzy_models[:fuzzy_budget]:
        if model not in candidates:
            candidates.append(model)
    for model in semantic_models:
        if model not in candidates:
            candidates.append(model)
    for model in fuzzy_models[fuzzy_budget:]:
        if model not in candidates:
            candidates.append(model)
        if len(candidates) == WIDENED_CANDIDATE_LIMIT:
            break
    return candidates[:WIDENED_CANDIDATE_LIMIT]


def _deterministic_tiebreak(
    query_lower: str,
    fuzzy_results: List[Tuple[str, float]],
    G,
) -> Optional[str]:
    """Break a fuzzy tie only on a unique model or declaring-module mention."""
    import re as _re

    top_score = fuzzy_results[0][1]
    tied = [m for m, s in fuzzy_results if (top_score - s) < AMBIGUITY_GAP_THRESHOLD]
    if len(tied) < 2:
        return None

    context_query = _re.sub(r"(?<!\w)[\w]+(?:\.[\w]+)+(?!\w)", " ", query_lower)
    context_query = _re.sub(r"(?<!\w)group_[\w]+(?!\w)", " ", context_query)

    scores: Dict[str, int] = {m: 0 for m in tied}

    for model in tied:
        segments = model.lower().replace("_", " ").split(".")
        for seg in segments:
            if len(seg) < _MIN_SEGMENT_LEN:
                continue
            for variant in (seg, seg.replace(" ", "_")):
                pattern = r"(?<![\w.])" + _re.escape(variant) + r"(?![\w.])"
                if _re.search(pattern, context_query):
                    scores[model] += 2
                    break

        model_node = f"model:{model}"
        if G.has_node(model_node):
            for successor in G.successors(model_node):
                edge = G.edges[model_node, successor]
                if (
                    edge.get("edge_type") == "DEFINED_IN"
                    and edge.get("role", "declares") == "declares"
                ):
                    mod_name = successor.removeprefix("module:").lower()
                    if len(mod_name) >= _MIN_SEGMENT_LEN:
                        mod_pattern = r"(?<![\w.])" + _re.escape(mod_name) + r"(?![\w.])"
                        if _re.search(mod_pattern, context_query):
                            scores[model] += 3

    # Only return a winner if exactly one candidate has the highest score AND it's > 0
    max_score = max(scores.values())
    if max_score <= 0:
        return None
    winners = [m for m, s in scores.items() if s == max_score]
    if len(winners) == 1:
        _logger.info(
            "Tiebreak resolved: %s (score %d) from %d tied candidates",
            winners[0], max_score, len(tied),
        )
        return winners[0]
    return None


def resolve_business_term(
    query_text: str,
    G=None,
    llm=None,
    active_model: Optional[str] = None,
    *,
    language: Optional[str] = None,
    use_static_aliases: bool = True,
) -> ResolvedConcept:
    """Resolve a natural language query into a technical Odoo model/module."""
    if not query_text:
        return ResolvedConcept(
            user_term="",
            is_resolved=False,
            reason="Empty query text provided.",
        )

    clean_query = _nfc(query_text.lower().strip())
    aliases = BUSINESS_ALIASES_NFC if use_static_aliases else {}
    alias_patterns = _ALIAS_PATTERNS if use_static_aliases else {}

    # First retain only literal model names.  Inferring a model from a shared
    # method/button name (for example action_confirm) is deliberately delayed
    # until after business aliases have had a chance to identify the primary
    # document.  Otherwise an unrelated model sharing that method can consume
    # the bounded dispatch budget before the actual target (SAL-Q2).
    exact_mentions = _find_exact_technical_model_mentions(
        clean_query, G, include_symbol_inference=False,
    )
    exact_modules = _find_exact_technical_module_mentions(clean_query, G)
    inferred_symbol_mentions = []
    if not exact_mentions and not exact_modules:
        inferred_symbol_mentions = _find_exact_technical_model_mentions(
            clean_query, G, include_symbol_inference=True,
        )
        # A unique parent model for a technical button/method is stronger
        # than a generic alias such as "commande". Shared symbols remain
        # deferred to alias resolution so unrelated models cannot consume the
        # dispatch budget (SAL-Q2 versus PUR-Q2).
        if len(inferred_symbol_mentions) == 1:
            exact_mentions = inferred_symbol_mentions
    if len(exact_mentions) > 1:
        exact_mentions = rank_by_specificity(exact_mentions, clean_query)
    if exact_mentions or exact_modules:
        if exact_modules:
            matched_aliases = [
                alias for alias in aliases
                if alias_patterns[alias].search(clean_query)
            ]
            alias_models = []
            for alias in matched_aliases:
                for t in aliases[alias]:
                    if t not in alias_models and t not in exact_mentions:
                        if G is not None:
                            is_in_mod = any(
                                G.has_edge(f"model:{t}", f"module:{mod}")
                                and G.edges[f"model:{t}", f"module:{mod}"].get(
                                    "role", "declares",
                                ) == "declares"
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
                            if (
                                u.startswith("model:")
                                and G.edges[u, mod_node].get("role", "declares") == "declares"
                            ):
                                m_name = u.replace("model:", "")
                                if m_name not in mod_models:
                                    mod_models.append(m_name)
                if mod_models:
                    exact_mentions = mod_models
        elif exact_mentions and (
            not inferred_symbol_mentions
            or has_non_generic_field_mention(clean_query, G)
        ):
            # Un nom de modele technique cite litteralement (ex. "stock.quant")
            # court-circuitait entierement la table d'alias, meme quand la
            # meme question designe par un terme metier DISTINCT un second
            # modele (ex. "numero de serie" -> stock.lot) qu'aucune mention
            # technique exacte ne couvre. Fusionne ici les modeles resolus
            # par alias qui ne sont pas deja couverts par la mention exacte,
            # sans jamais retirer ni reordonner ce que la mention exacte a
            # deja trouve (todo/contexte.txt sections 801-802, STK-Q5).
            merge_matched_aliases = [
                alias for alias in aliases
                if alias_patterns[alias].search(clean_query)
            ]
            # Section 879: meme filtre de sous-chaine que le chemin alias
            # ci-dessous -- un alias INCLUS dans un alias plus long deja
            # apparie ("commande" dans "commande d'achat") designe le meme
            # terme metier, pas un second modele distinct a fusionner
            # (PUR-Q1 : sale.order etait ajoute a purchase.order).
            # Exception : un alias inclus dont la cible est un ANCETRE en
            # notation pointee d'un modele deja resolu (ex. "purge" ->
            # cleanup.purge.wizard, parent abstrait de cleanup.purge.wizard.model,
            # DC-Q1) est de la meme famille, pas un modele etranger : conserve.
            if len(merge_matched_aliases) > 1:
                merge_matched_aliases = [
                    a for a in merge_matched_aliases
                    if not any(a != b and a in b for b in merge_matched_aliases)
                    or any(
                        m.startswith(t + ".")
                        for t in aliases[a] for m in exact_mentions
                    )
                ]
            for alias in merge_matched_aliases:
                for t in aliases[alias]:
                    if t not in exact_mentions:
                        exact_mentions.append(t)

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
        targets = aliases[alias]
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
                # Quand les deux cibles "alternatives" sont presentes simultanement
                # dans le graphe (ex. corpus custom + corpus OCA charges ensemble),
                # ne pas dependre de l'ordre d'ecriture de BUSINESS_ALIASES --
                # preferer deterministiquement la cible custom.* (le terme metier
                # adversarial explicitement teste), pas le premier element de la
                # liste (todo/contexte.txt section 730 -- bug reel trouve en
                # curl live : "demande d'achat" resolvait vers purchase.request
                # OCA au lieu de custom.purchase.request des que les deux corpus
                # coexistaient dans le meme graphe).
                custom_in_g = [t for t in existing_in_g if t.startswith("custom.")]
                targets_to_add = [custom_in_g[0]] if custom_in_g else [existing_in_g[0]]
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
        fuzzy_results = _fuzzy_match_graph(
            clean_query,
            G,
            language=language,
            use_static_synonyms=use_static_aliases,
        )
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

            # Deterministic tiebreak on model/module segment overlap.
            if G is not None:
                tiebreaker_winner = _deterministic_tiebreak(
                    clean_query, fuzzy_results, G,
                )
                if tiebreaker_winner:
                    return ResolvedConcept(
                        user_term=query_text,
                        resolved_models=[tiebreaker_winner],
                        confidence=round(top_score / 100, 2) * 0.9,
                        source_step="fuzzy_tiebreak",
                        is_resolved=True,
                        reason=(
                            f"Deterministic tiebreak among ambiguous fuzzy candidates "
                            f"({', '.join(f'{m} ({s:.0f})' for m, s in fuzzy_results)}) "
                            f"-> '{tiebreaker_winner}' (model/module name overlap in query)."
                        ),
                    )

            # Step 3: Bounded LLM Candidate Selection
            arbitration_models = _arbitration_candidates(
                clean_query,
                G,
                language,
                use_static_aliases,
                llm is not None,
            )
            chosen = _llm_arbitrate(
                query_text,
                arbitration_models,
                llm,
                _candidate_contexts(G, arbitration_models, language),
            )
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
                language=language,
                use_static_synonyms=use_static_aliases,
            )
            if widened_results:
                widened_models = _arbitration_candidates(
                    clean_query,
                    G,
                    language,
                    use_static_aliases,
                    llm is not None,
                    widened_results,
                )
                chosen = _llm_arbitrate(
                    query_text,
                    widened_models,
                    llm,
                    _candidate_contexts(G, widened_models, language),
                )
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
