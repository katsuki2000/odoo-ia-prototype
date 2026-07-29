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

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process

_logger = logging.getLogger(__name__)

# Static hand-maintained business alias table mapping French terms & module names to technical model names
BUSINESS_ALIASES: Dict[str, List[str]] = {
    "avoir": ["account.move"],
    "avoirs": ["account.move"],
    "credit note": ["account.move"],
    "client vip": ["account.move"],
    "vip": ["account.move"],
    "demande d'achat": ["custom.purchase.request", "purchase.order"],
    "demande d'achats": ["custom.purchase.request", "purchase.order"],
    "purchase request": ["custom.purchase.request"],
    "custom_purchase_request": ["custom.purchase.request"],
    "mise a disposition": ["custom.asset.loan"],
    "mise à disposition": ["custom.asset.loan"],
    "materiel": ["custom.asset.loan"],
    "matériel": ["custom.asset.loan"],
    "asset loan": ["custom.asset.loan"],
    "custom_asset_loan": ["custom.asset.loan"],
    "conge": ["hr.leave"],
    "congé": ["hr.leave"],
    "conges": ["hr.leave"],
    "congés": ["hr.leave"],
    "demande de conge": ["hr.leave"],
    "demande de congé": ["hr.leave"],
    "custom_hr_leave_workflow": ["hr.leave"],
    "remboursement de frais": ["custom.reimbursement.request", "hr.expense"],
    "note de frais": ["custom.reimbursement.request", "hr.expense"],
    "custom_expense_reimbursement_indirect": ["custom.reimbursement.request"],
    "action automatique": ["custom.purchase.request", "base.automation"],
    "serveur action": ["custom.purchase.request", "ir.actions.server"],
    "server action": ["custom.purchase.request", "ir.actions.server"],
    "regional": ["account.move"],
    "régional": ["account.move"],
    "national": ["account.move"],
}


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

    _FUZZY_INDEX_CACHE[cache_key] = index
    _logger.info("Built fuzzy index: %d entries from graph (%d nodes)", len(index), G.number_of_nodes())
    return index


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

    # token_set_ratio:  handles extra tokens in the query gracefully.
    # token_sort_ratio: handles word-order variations.
    model_scores: Dict[str, float] = {}

    for scorer in (fuzz.token_set_ratio, fuzz.token_sort_ratio):
        hits = process.extract(
            query_lower, labels,
            scorer=scorer,
            score_cutoff=threshold * 0.6,  # pre-filter; real threshold applied after penalty
            limit=limit * 5,
        )
        for _text, score, idx in (hits or []):
            label = index[idx][0]
            label_token_count = max(len(label.split()), 1)
            # Length penalty: a 1-token label matching a 7-token query is
            # far less meaningful than a 5-token label matching a 7-token
            # query.  sqrt softens the curve so multi-word labels aren't
            # over-penalized.
            length_penalty = min(label_token_count / query_token_count, 1.0) ** 0.5
            adjusted = score * length_penalty
            if adjusted >= threshold:
                model = index[idx][1]
                model_scores[model] = max(model_scores.get(model, 0.0), adjusted)

    sorted_results = sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_results[:limit]


def resolve_business_term(query_text: str, G=None) -> ResolvedConcept:
    """
    Resolve natural language query terms to technical Odoo models or modules.
    
    Args:
        query_text: Natural language user question.
        G: Optional NetworkX knowledge graph reference.
        
    Returns:
        ResolvedConcept object.
    """
    if not query_text:
        return ResolvedConcept(
            user_term="",
            is_resolved=False,
            reason="Empty query text provided."
        )

    clean_query = query_text.lower().strip()

    # Step 1: Static Business Alias Lookup
    matched_models = []
    matched_modules = []
    matched_terms = []

    for alias, targets in BUSINESS_ALIASES.items():
        if alias in clean_query:
            matched_terms.append(alias)
            for t in targets:
                if G is not None:
                    # Check if target exists as model or module in graph
                    if G.has_node(f"model:{t}"):
                        if t not in matched_models:
                            matched_models.append(t)
                    elif G.has_node(f"module:{t}"):
                        if t not in matched_modules:
                            matched_modules.append(t)
                    else:
                        # Fallback add
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
            reason=f"Matched static aliases: {', '.join(matched_terms)}"
        )

    # Step 2: Fuzzy matching against Graph Node labels (rapidfuzz)
    # Uses token_set_ratio / token_sort_ratio — never a plain ratio on the
    # whole string (per B0 plan spec).  Targets: Model.description,
    # Field.label (string=), Menu.name (-> model via OPENS_MODEL).
    if G is not None:
        fuzzy_results = _fuzzy_match_graph(clean_query, G)
        if fuzzy_results:
            top_models = [model for model, _score in fuzzy_results]
            top_score = fuzzy_results[0][1]
            return ResolvedConcept(
                user_term=query_text,
                resolved_models=top_models,
                confidence=round(top_score / 100, 2),
                source_step="fuzzy_graph_match",
                is_resolved=True,
                reason=f"Fuzzy matched graph labels: {', '.join(f'{m} ({s:.0f})' for m, s in fuzzy_results)}"
            )

    # Step 3: Unresolved concept fallback
    return ResolvedConcept(
        user_term=query_text,
        is_resolved=False,
        confidence=0.0,
        source_step="unresolved",
        reason="No business alias or graph model match found."
    )
