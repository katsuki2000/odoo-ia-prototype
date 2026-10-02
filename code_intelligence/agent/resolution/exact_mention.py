"""Resolution step: technical model or module names quoted verbatim in the question."""

from typing import Optional

from ..matching import (
    ResolvedConcept,
    _find_exact_technical_model_mentions,
    _find_exact_technical_module_mentions,
    has_non_generic_field_mention,
    rank_by_specificity,
)


def resolve_exact_mention(clean_query: str, query_text: str, G, aliases, alias_patterns) -> Optional[ResolvedConcept]:
    """Resolve literal model/module mentions, merged with aliases not covered by them."""
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
    return None
