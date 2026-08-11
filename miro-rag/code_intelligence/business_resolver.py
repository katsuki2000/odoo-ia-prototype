"""
code_intelligence/business_resolver.py

Story S2.0: Business Term to Technical Symbol Resolver.
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

# Static hand-maintained business alias table.
# ONLY for synonyms with zero lexical overlap between the French business
# term and the English technical name, where fuzzy matching cannot help.
# Keep this short — if a term can be found via graph labels, it belongs
# in the graph, not here.
BUSINESS_ALIASES: Dict[str, List[str]] = {
    # Comptabilité / avoirs
    "avoir": ["account.move"],
    "avoirs": ["account.move"],
    "credit note": ["account.move"],
    "facture": ["account.move"],
    "factures": ["account.move"],
    "facturation": ["account.move"],
    # Achats
    # Bloc 9 gap (2026-08-10, module 4/8, bloc9-04a/04c): this alias used to
    # also resolve to the real standard Odoo "purchase.order" model. In
    # French Odoo terminology "demande d'achat" is not actually a synonym
    # for "purchase.order" (a bon de commande) -- it is the literal name of
    # this custom module's own _description ("Demande d'achat interne",
    # custom_purchase_request/models/purchase_request.py). Forcing both
    # models through the deterministic pre-dispatch in rag/graph.py meant
    # every question about this custom approval/threshold workflow also
    # dragged in the entire unrelated 1101-line standard purchase.order
    # lock analysis (a different mechanism, different required group) --
    # confirmed via check_bloc9_04_purchase_request_e2e.py to drown the
    # 10 000e threshold fact specific to custom.purchase.request in noise,
    # and in the trap question (bloc9-04c) to make the synthesis answer
    # off the wrong (irrelevant) model entirely. Zero lexical-overlap
    # principle from this table's own docstring: custom.purchase.request
    # is the exact, unambiguous match, so it is the only static alias
    # target here -- a genuine "bon de commande"/purchase.order question
    # remains resolvable on its own merits via fuzzy graph matching.
    "demande d'achat": ["custom.purchase.request"],
    "demande d'achats": ["custom.purchase.request"],
    # Prêt matériel
    "mise a disposition": ["custom.asset.loan"],
    "mise à disposition": ["custom.asset.loan"],
    # Congés
    "conge": ["hr.leave"],
    "congé": ["hr.leave"],
    "conges": ["hr.leave"],
    "congés": ["hr.leave"],
    "demande de conge": ["hr.leave"],
    "demande de congé": ["hr.leave"],
    # Frais
    # Bloc 9 gap (2026-08-11, module 7/8, bloc9-07c-sudo-scope-trap): the
    # original alias key was the fixed phrase "remboursement de frais" --
    # matched as a literal substring, so it never fires on a question that
    # says "demande de remboursement" (different word order, "de frais"
    # dropped entirely), which is how a real user just as plausibly phrases
    # it. Confirmed live: this exact phrasing fell through static alias AND
    # exact-technical-mention (07c never names the module/model), leaving
    # only fuzzy matching -- which did not resolve to custom.reimbursement.
    # request at all, so the forced, structural (no question-wording gate)
    # analyser_verrous_securite pre-dispatch never ran, and the getattr()
    # uncertainty guardrail never triggered either -- the synthesis LLM
    # answered from evaluer_regles_enregistrement alone and asserted the
    # dangerous inverse ("sans restriction"). Added the bare noun
    # "remboursement" as its own alias key (zero lexical overlap with the
    # English technical names, same principle as every other entry here) so
    # any phrasing containing that single word resolves deterministically,
    # without needing to guess every possible surrounding phrase.
    "remboursement": ["custom.reimbursement.request", "hr.expense"],
    "remboursement de frais": ["custom.reimbursement.request", "hr.expense"],
    "note de frais": ["custom.reimbursement.request", "hr.expense"],
    # Automatismes Odoo
    "action automatique": ["base.automation"],
    "serveur action": ["ir.actions.server"],
    "server action": ["ir.actions.server"],
}


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


BUSINESS_ALIASES_NFC: Dict[str, List[str]] = {_nfc(k): v for k, v in BUSINESS_ALIASES.items()}

# Word-boundary pattern: \w is Unicode-aware by default in Python 3.
# Prevents "avoir" from matching inside longer unrelated words,
# while preserving token order for multi-word phrases ("mise à disposition").
_ALIAS_PATTERNS: Dict[str, re.Pattern] = {
    alias: re.compile(r"(?<!\w)" + re.escape(alias) + r"(?!\w)")
    for alias in BUSINESS_ALIASES_NFC
}

# Bug #1 (J1) regression note: static alias lookup MUST run before fuzzy
# matching. Do not reorder these steps — see test_s2_0_alias_not_shadowed_by_fuzzy_single_token.

# --- J2: bounded LLM arbitration ------------------------------------------

# Below this score gap between the top-1 and top-2 fuzzy candidates, the
# result is considered ambiguous and is escalated to LLM arbitration
# instead of being returned directly.
AMBIGUITY_GAP_THRESHOLD = 10.0

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

        prompt = _build_arbitration_prompt(query_text, candidates)
        response = llm.invoke([
            SystemMessage(content=_ARBITRATION_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        raw = (response.content or "").strip()
    except Exception:
        _logger.exception("LLM arbitration call failed for query=%r candidates=%r", query_text, candidates)
        return None

    if raw == "NONE":
        return None
    if raw in candidates:
        return raw

    # Hallucinated or malformed output (e.g. a model not in the closed
    # list, or extra text). Never trust it — treat as a failed arbitration,
    # not a resolved concept, per the plan's "jamais présenté comme fait
    # structurel certain" rule for LLM-derived results.
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
            # Gap found 2026-08-06 (custom.deep.document E2E check): the
            # raw technical model name itself was never indexed, only its
            # human-readable _description. A question stating the exact
            # technical name verbatim (e.g. "dans le modèle
            # custom.deep.document") had no reliable resolution path --
            # is_resolved stayed False, so every J8/J9/Bloc-9 forced
            # dispatch (analyser_verrous_securite, analyser_actions_serveur,
            # analyser_chaine_surcharge_methode) silently never fired, and
            # the LLM was left to freelance tool selection alone -- exactly
            # the unreliable behavior J8 exists to remove. Index both the
            # dotted technical name and its dot-to-space token form so
            # fuzzy matching (which tokenizes on whitespace) can score it.
            technical_name = data.get("name", node_id.replace("model:", ""))
            if technical_name:
                index.append((technical_name.lower(), technical_name))
                spaced = technical_name.replace(".", " ").replace("_", " ")
                if spaced != technical_name:
                    index.append((spaced.lower(), technical_name))

    _FUZZY_INDEX_CACHE[cache_key] = index
    _logger.info("Built fuzzy index: %d entries from graph (%d nodes)", len(index), G.number_of_nodes())
    return index


def _find_exact_technical_model_mentions(query_lower: str, G) -> List[str]:
    """
    Step 1.5 (added 2026-08-06, same gap as the fuzzy-index fix above):
    before falling back to fuzzy matching against descriptions/labels,
    check whether the query mentions a real technical model name verbatim
    (e.g. "custom.deep.document"). This is strictly more reliable than
    fuzzy matching for this specific case -- an exact technical identifier
    in the question is unambiguous and should never depend on how well a
    model's _description happens to read.

    Returns the list of technical model names found as whole-word
    substrings (dots included, so "custom.deep.document" won't spuriously
    match inside a longer dotted identifier). Deliberately does not use
    fuzzy scoring here -- this is an exact-mention check only.
    """
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


def _fuzzy_match_graph(query: str, G, threshold: int = 75, limit: int = 5) -> List[Tuple[str, float]]:
    """
    Match query against graph labels using rapidfuzz token_set_ratio and
    token_sort_ratio (never a plain ratio on the whole string — per B0 spec).

    Applies a length penalty when the label is much shorter than the query
    to prevent single-word labels (e.g. field "comment") from scoring 100
    against long queries where that word happens to appear.

    Returns list of (model_name, best_score) tuples, sorted by score desc,
    deduplicated by model (keeps the highest score per model).
    """
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
    """
    Resolve natural language query terms to technical Odoo models or modules.

    Args:
        query_text: Natural language user question.
        G: Optional NetworkX knowledge graph reference.
        llm: Optional LangChain-compatible chat client (e.g. graph.py's
             ChatGroq instance), used only for bounded arbitration when
             fuzzy matching returns ambiguous candidates. If None,
             ambiguous cases fall through to "unresolved" rather than
             guessing.

    Returns:
        ResolvedConcept object.
    """
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

    # Step 1.5 (2026-08-06 fix): exact technical model-name mention.
    # Strictly more reliable than fuzzy matching when the question already
    # names the technical identifier verbatim -- see
    # _find_exact_technical_model_mentions docstring for the gap this closes.
    exact_mentions = _find_exact_technical_model_mentions(clean_query, G)
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

            # Step 3: Bounded LLM Candidate Selection (only reached on
            # genuine ambiguity — never for a clear top-1 fuzzy match).
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

            # LLM declined (NONE / invalid / call failure): fall through to
            # unresolved rather than silently keeping the fuzzy top-1.
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

    # Step 4: Unresolved concept fallback
    return ResolvedConcept(
        user_term=query_text,
        is_resolved=False,
        confidence=0.0,
        source_step="unresolved",
        reason="No business alias or graph model match found."
    )
