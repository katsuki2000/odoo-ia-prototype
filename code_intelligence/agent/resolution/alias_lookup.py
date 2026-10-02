"""Resolution step: static business alias lookup."""

from typing import Optional

from ..matching import ResolvedConcept


def resolve_static_alias(clean_query: str, G, aliases, alias_patterns) -> Optional[ResolvedConcept]:
    """Resolve business aliases to graph models or modules."""
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
    return None
