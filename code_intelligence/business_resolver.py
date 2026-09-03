"""
code_intelligence/business_resolver.py

Business Term to Technical Symbol Resolver.
Maps natural language functional concepts to technical graph nodes (models, fields, modules).

Resolution Order:
1. Static Business Alias Lookup (BUSINESS_ALIASES dictionary) - 100% deterministic, zero latency.
2. Fuzzy String Matching against indexed Graph Node labels, names, and XML-IDs.
3. Bounded LLM Candidate Selection (only if ambiguous candidates exist).
4. Explicit "unresolved" return status if no candidate matches.
"""

import re
import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process

_logger = logging.getLogger(__name__)


BUSINESS_ALIASES: Dict[str, List[str]] = {
    # Comptabilité / avoirs
    "avoir": ["account.move"],
    "avoirs": ["account.move"],
    "credit note": ["account.move"],
    "facture": ["account.move"],
    "factures": ["account.move"],
    "facturation": ["account.move"],
    "demande d'achat": ["custom.purchase.request"],
    "demande d'achats": ["custom.purchase.request"],
    # Prêt matériel
    "mise a disposition": ["custom.asset.loan"],
    "mise à disposition": ["custom.asset.loan"],
    # Section 228 (todo/contexte.txt) : alias manquants, question H4 reelle
    # ("Quelles sont les regles de visibilite pour les prets de materiel ?")
    # ne matchait aucun alias existant -- "mise a disposition" seul ne couvre
    # pas le vocabulaire "pret(s) de materiel".
    "pret de materiel": ["custom.asset.loan"],
    "prêt de matériel": ["custom.asset.loan"],
    "prets de materiel": ["custom.asset.loan"],
    "prêts de matériel": ["custom.asset.loan"],
    # Congés
    "conge": ["hr.leave"],
    "congé": ["hr.leave"],
    "conges": ["hr.leave"],
    "congés": ["hr.leave"],
    "demande de conge": ["hr.leave"],
    "demande de congé": ["hr.leave"],
    "remboursement": ["custom.reimbursement.request", "hr.expense"],
    "remboursement de frais": ["custom.reimbursement.request", "hr.expense"],
    "note de frais": ["custom.reimbursement.request", "hr.expense"],
    # Automatismes Odoo
    "action automatique": ["base.automation"],
    "serveur action": ["ir.actions.server"],
    "server action": ["ir.actions.server"],
    # Deep inheritance security
    "document deep": ["custom.deep.document"],
    "deep document": ["custom.deep.document"],
    # Section 228 (todo/contexte.txt) : forme plurielle manquante -- la
    # frontiere de mot stricte du pattern d'alias ne tolere pas le "s" du
    # pluriel intercale ("documents deep" ne matchait ni "document deep" ni
    # "deep document"), reproduit par une question H4 reelle ("Un employe
    # peut-il voir les documents deep sans autorisation ?").
    "documents deep": ["custom.deep.document"],
    "deep documents": ["custom.deep.document"],
}


# Section 307-310 (todo/contexte.txt) : lexique de synonymes FR pour les
# modeles Odoo natifs, delibrement SEPARE de BUSINESS_ALIASES (mecanisme
# different -- celui-ci alimente l'index fuzzy du Step 2, il n'est jamais
# teste en priorite/deterministe comme BUSINESS_ALIASES au Step 1). Portee
# Phase 1 restreinte aux 4 entrees ci-dessous, chacune validee empiriquement
# via scripts/test_resolver.py (sections 307-310) : la requete correspondante
# etait un `unresolved` PROPRE (reason="No business alias or graph model
# match found."), sans aucun candidat concurrent existant a ce jour. Des
# candidats plus courts/ambigus ("achat" seul, "stock" seul, "reception"
# seul, "produit" seul) ont ete explicitement exclus de cette Phase 1 --
# ils sont deja noyes dans plusieurs modeles a score quasi identique dans
# l'index existant (5+ candidats a 100 pour "stock"/"reception", 5 candidats
# a 86 pour "produit"), et l'ajout d'un synonyme supplementaire n'y cree pas
# de gagnant net -- au contraire, "achat" seul creerait une egalite exacte a
# 100 avec un label de champ existant sur custom.asset.loan (root cause
# tracee section 309). Ne pas y ajouter d'entree sans repeter la meme mesure
# prealable (dump reason via _fuzzy_match_graph/resolve_business_term).
NATIVE_MODEL_SYNONYMS: Dict[str, List[str]] = {
    "sale.order": ["commande de vente", "devis", "vente"],
    "purchase.order": ["commande d'achat"],
    "stock.picking": ["livraison"],
    "stock.move": ["mouvement de stock"],
}


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


BUSINESS_ALIASES_NFC: Dict[str, List[str]] = {_nfc(k): v for k, v in BUSINESS_ALIASES.items()}

_ALIAS_PATTERNS: Dict[str, re.Pattern] = {
    alias: re.compile(r"(?<!\w)" + re.escape(alias) + r"(?!\w)")
    for alias in BUSINESS_ALIASES_NFC
}

AMBIGUITY_GAP_THRESHOLD = 10.0

# Section 228 (todo/contexte.txt), option (b): candidate shortlist used ONLY
# when the strict fuzzy pass (threshold above, in _fuzzy_match_graph's default
# argument) finds nothing at all -- see the "else" branch in
# resolve_business_term below for the full rationale (length_penalty makes the
# strict threshold unreachable for long questions matched against short
# indexed labels). Never auto-accepted: only ever used to build a bounded
# closed list for _llm_arbitrate.
WIDENED_CANDIDATE_THRESHOLD = 30
WIDENED_CANDIDATE_LIMIT = 8

_ARBITRATION_SYSTEM_PROMPT = (
    "Tu es un composant de résolution de symboles techniques Odoo. "
    "Tu dois choisir, parmi une liste fermée de modèles techniques candidats, "
    "celui qui correspond le mieux à la question métier posée — ou indiquer "
    "qu'aucun ne convient. Tu ne dois JAMAIS proposer un nom de modèle en "
    "dehors de la liste fournie, même s'il te semble plus pertinent."
)


def _build_arbitration_prompt(query_text: str, candidates: List[str]) -> str:
    candidates_block = "\n".join(f"- {c}" for c in candidates)
    return (
        f'Question métier utilisateur : "{query_text}"\n\n'
        f"Modèles techniques Odoo candidats (extraits par correspondance approximative, "
        f"scores proches, ambigus) :\n{candidates_block}\n\n"
        "Réponds UNIQUEMENT avec le nom technique exact d'UN SEUL de ces modèles "
        "s'il correspond clairement à la question, ou UNIQUEMENT le mot NONE si "
        "aucun ne correspond clairement. Pas d'explication, pas de ponctuation, "
        "pas de modèle hors de cette liste."
    )


def _llm_arbitrate(query_text: str, candidates: List[str], llm) -> Optional[str]:
    """
    Bounded LLM candidate selection over a closed list.

    Args:
        query_text: original user question.
        candidates: closed list of candidate technical model names (fuzzy top-N).
        llm: a LangChain-compatible chat model already instantiated by the
             caller (e.g. graph.py's ChatGroq client). Injected rather than
             built here so callers/tests control the client and its config.

    Returns:
        The chosen candidate (exact string from `candidates`), or None if
        the LLM said NONE, returned something outside the closed list, or
        the call failed. None is never treated as a guess — callers must
        fall back to "unresolved", never silently pick a default candidate.
    """
    if llm is None:
        _logger.warning("LLM arbitration requested but no llm client was provided; skipping.")
        return None

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        # Section 263 (todo/contexte.txt): route through the same
        # multi-key Groq rotation / rate-limit retry wrapper already used
        # by the Code Intelligence branch (core/llm_client.py), instead of
        # calling llm.invoke() directly. rebuild_llm rebuilds a plain
        # (non-tool-bound) client via get_chat_llm() -- reasonable default
        # for a short, single-shot arbitration call -- so a 429 on the
        # injected `llm` rotates to the next configured GROQ_API_KEYS entry
        # instead of failing this arbitration outright.
        from core.llm_client import get_chat_llm, invoke_with_rate_limit

        prompt = _build_arbitration_prompt(query_text, candidates)
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


@dataclass
class ResolvedConcept:
    user_term: str
    resolved_models: List[str] = field(default_factory=list)
    resolved_modules: List[str] = field(default_factory=list)
    confidence: float = 1.0
    source_step: str = "static_alias"
    is_resolved: bool = True
    reason: str = ""


_FUZZY_INDEX_CACHE: Dict[int, List[Tuple[str, str]]] = {}


def _build_fuzzy_index(G) -> List[Tuple[str, str]]:
    """
    Build (label, technical_model_name) pairs from graph nodes as targets
    for fuzzy matching.  Sources:
      - Model.description  (e.g. "Credit Note Approval")  -> model name
      - Field.label        (e.g. "Montant total")          -> parent model
      - Menu.name          (e.g. "Facturation / Avoirs")   -> model via OPENS_MODEL
    Labels shorter than 3 characters are skipped (too noisy).
    """
    cache_key = id(G)
    if cache_key in _FUZZY_INDEX_CACHE:
        return _FUZZY_INDEX_CACHE[cache_key]

    index: List[Tuple[str, str]] = []

    for node_id, data in G.nodes(data=True):
        node_type = data.get("node_type")

        if node_type == "Model":
            model_name = data.get("name", node_id.replace("model:", ""))
            desc = data.get("description", "")
            if desc and len(desc) >= 3:
                index.append((desc.lower(), model_name))

        elif node_type == "Field":
            label = data.get("label", "")
            model_name = data.get("model", "")
            if label and model_name and len(label) >= 3:
                index.append((label.lower(), model_name))

        elif node_type == "Menu":
            menu_name = data.get("name", "")
            if menu_name and len(menu_name) >= 3:
                for successor in G.successors(node_id):
                    edge_data = G.edges[node_id, successor]
                    if edge_data.get("edge_type") == "OPENS_MODEL":
                        model_name = successor.replace("model:", "")
                        index.append((menu_name.lower(), model_name))
                        break

        if node_type == "Model":
            technical_name = data.get("name", node_id.replace("model:", ""))
            if technical_name:
                index.append((technical_name.lower(), technical_name))
                spaced = technical_name.replace(".", " ").replace("_", " ")
                if spaced != technical_name:
                    index.append((spaced.lower(), technical_name))

    # injection des synonymes FR pour les modeles Odoo natifs (Phase 1), au meme titre que les entrees Model.description/Field.label/Menu.name ci-dessus -- meme forme de tuple (label.lower(), model_name), meme scorer, aucun traitement prioritaire. Garde G.has_node() pour ne pas injecter silencieusement un synonyme sur un modele absent du graphe charge (ex. module non installe sur cette instance) -- un synonyme fantome pointant vers un modele inexistant serait pire qu'une absence de synonyme.
    for model_name, synonyms in NATIVE_MODEL_SYNONYMS.items():
        if not G.has_node(f"model:{model_name}"):
            continue
        for synonym in synonyms:
            index.append((synonym.lower(), model_name))

    _FUZZY_INDEX_CACHE[cache_key] = index
    _logger.info("Built fuzzy index: %d entries from graph (%d nodes)", len(index), G.number_of_nodes())
    return index


def _find_exact_technical_model_mentions(query_lower: str, G) -> List[str]:
    if G is None:
        return []
    found = []
    for node_id, data in G.nodes(data=True):
        if data.get("node_type") != "Model":
            continue
        technical_name = data.get("name", node_id.replace("model:", ""))
        if not technical_name or len(technical_name) < 3:
            continue
        pattern = r"(?<!\w)" + re.escape(technical_name.lower()) + r"(?!\w)"
        if re.search(pattern, query_lower):
            found.append(technical_name)
    return found


def _specificity_score(technical_name: str, query_lower: str) -> Tuple[int, int, int, int]:
    """Deterministic specificity score for an exact technical model mention,
    higher is more specific/relevant. Compared as a tuple (segments, length,
    custom_prefix, occurrences) -- see rank_by_specificity's docstring for
    the rationale (todo/contexte.txt section 2xx)."""
    segments = technical_name.count(".") + 1
    length = len(technical_name)
    is_custom = 1 if technical_name.startswith(("custom.", "x_")) else 0
    pattern = r"(?<!\w)" + re.escape(technical_name.lower()) + r"(?!\w)"
    occurrences = len(re.findall(pattern, query_lower))
    return (segments, length, is_custom, occurrences)


def rank_by_specificity(matches: List[str], query_lower: str) -> List[str]:
    """
    Arbitrate between several exact technical model mentions found verbatim
    in the same question, instead of treating every exact match as equally
    valid (todo/contexte.txt section 2xx).

    Root cause: multiple exact matches can coexist in one query (e.g. a
    generic name like 'base' alongside a specific one like
    'custom.deep.document') with nothing choosing the more relevant one --
    the naive fix (blacklisting 'base') is ad hoc and would need to be
    re-applied for every future generic technical name ('mail', 'stock',
    'account', ...). The real signal is that matches are not equally
    informative: more segments, longer, custom/business-prefixed, and more
    frequently mentioned all indicate higher relevance.

    Deterministic criteria, most to least significant:
      1. number of dot-segments (custom.deep.document > base)
      2. technical name length
      3. presence of a business/custom prefix (custom., x_)
      4. number of verbatim occurrences in the question

    Only the strictly best-scoring match(es) are kept; ties (identical score
    tuple) are all kept rather than picking one arbitrarily. With a single
    match, this is a no-op.
    """
    if len(matches) <= 1:
        return matches
    scored = [(m, _specificity_score(m, query_lower)) for m in matches]
    top_score = max(score for _m, score in scored)
    return [m for m, score in scored if score == top_score]


def _fuzzy_match_graph(query: str, G, threshold: int = 75, limit: int = 5) -> List[Tuple[str, float]]:
    index = _build_fuzzy_index(G)
    if not index:
        return []

    labels = [entry[0] for entry in index]
    query_lower = query.lower()
    query_token_count = max(len(query_lower.split()), 1)

    model_scores: Dict[str, float] = {}

    for scorer in (fuzz.token_set_ratio, fuzz.token_sort_ratio):
        hits = process.extract(
            query_lower, labels,
            scorer=scorer,
            score_cutoff=threshold * 0.6,
            limit=limit * 5,
        )
        for _text, score, idx in (hits or []):
            label = index[idx][0]
            label_token_count = max(len(label.split()), 1)
            length_penalty = min(label_token_count / query_token_count, 1.0) ** 0.5
            adjusted = score * length_penalty
            if adjusted >= threshold:
                model = index[idx][1]
                model_scores[model] = max(model_scores.get(model, 0.0), adjusted)

    sorted_results = sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_results[:limit]


def resolve_business_term(query_text: str, G=None, llm=None) -> ResolvedConcept:
    if not query_text:
        return ResolvedConcept(
            user_term="",
            is_resolved=False,
            reason="Empty query text provided."
        )

    clean_query = _nfc(query_text.lower().strip())

    # Step 1: Static Business Alias Lookup (100% deterministic, zero latency)
    matched_models = []
    matched_modules = []
    matched_terms = []

    for alias, targets in BUSINESS_ALIASES_NFC.items():
        if _ALIAS_PATTERNS[alias].search(clean_query):
            matched_terms.append(alias)
            for t in targets:
                if G is not None:
                    if G.has_node(f"model:{t}"):
                        if t not in matched_models:
                            matched_models.append(t)
                    elif G.has_node(f"module:{t}"):
                        if t not in matched_modules:
                            matched_modules.append(t)
                    else:
                        if t not in matched_models:
                            matched_models.append(t)
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

    exact_mentions = _find_exact_technical_model_mentions(clean_query, G)
    if len(exact_mentions) > 1:
        # Section 2xx (todo/contexte.txt), option 2: several exact technical mentions can coexist in one query (e.g. a generic name like 'base' alongside a specific one like 'custom.deep.document') -- arbitrate by specificity instead of returning every exact match as equally valid. See rank_by_specificity's docstring for the rationale.
        exact_mentions = rank_by_specificity(exact_mentions, clean_query)
    if exact_mentions:
        return ResolvedConcept(
            user_term=query_text,
            resolved_models=exact_mentions,
            confidence=1.0,
            source_step="exact_technical_mention",
            is_resolved=True,
            reason=f"Exact technical model name(s) mentioned verbatim: {', '.join(exact_mentions)}",
        )

    # Step 2: Fuzzy matching against Graph Node labels (rapidfuzz)
    if G is not None:
        fuzzy_results = _fuzzy_match_graph(clean_query, G)
        if fuzzy_results:
            top_models = [model for model, _score in fuzzy_results]
            top_score = fuzzy_results[0][1]

            # Ambiguity check: is the top candidate clearly detached from
            # the runner-up, or are several candidates within the gap
            # threshold of each other?
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

            # Step 3: Bounded LLM Candidate Selection (only reached on genuine ambiguity — never for a clear top-1 fuzzy match).
            chosen = _llm_arbitrate(query_text, top_models, llm)
            if chosen is not None:
                return ResolvedConcept(
                    user_term=query_text,
                    resolved_models=[chosen],
                    confidence=0.6,  # bounded/low confidence — LLM interpretation, not a structural fact
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
            # the strict threshold above, combined with _fuzzy_match_graph's length_penalty, is mathematically unreachable for long natural-language questions matched against short indexed labels (verified by hand for 2 real H4 failures -- required raw score > 100, impossible). Rather than lowering the strict threshold globally (would start auto-accepting weak matches WITHOUT LLM confirmation -- a correctness regression), a second, deliberately loose fuzzy pass builds a bounded candidate shortlist ONLY for LLM arbitration -- the LLM still never picks outside this closed list (same _llm_arbitrate contract as the ambiguous-strict-match case above), and a chosen candidate is explicitly lower confidence than that case.
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
                        confidence=0.5,  # lower than "llm_arbitration": candidate list itself is weak evidence, not just ambiguous among strong matches
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
        reason="No business alias or graph model match found."
    )
