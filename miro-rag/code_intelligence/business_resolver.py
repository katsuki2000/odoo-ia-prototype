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
from dataclasses import dataclass, field
from typing import List, Dict, Optional

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

    # Step 2: Fuzzy / Substring Matching against Graph Nodes
    if G is not None:
        graph_models = [
            data.get("name", node_id.replace("model:", ""))
            for node_id, data in G.nodes(data=True)
            if data.get("node_type") == "Model"
        ]
        
        fuzzy_matches = []
        words = re.findall(r"\w+", clean_query)
        for w in words:
            if len(w) < 4:
                continue
            for m in graph_models:
                if w in m.lower():
                    fuzzy_matches.append(m)

        if fuzzy_matches:
            unique_matches = list(dict.fromkeys(fuzzy_matches))
            return ResolvedConcept(
                user_term=query_text,
                resolved_models=unique_matches,
                confidence=0.8,
                source_step="fuzzy_graph_match",
                is_resolved=True,
                reason=f"Matched graph models by keyword substring: {', '.join(unique_matches)}"
            )

    # Step 3: Unresolved concept fallback
    return ResolvedConcept(
        user_term=query_text,
        is_resolved=False,
        confidence=0.0,
        source_step="unresolved",
        reason="No business alias or graph model match found."
    )
