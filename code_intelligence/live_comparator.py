"""
code_intelligence/live_comparator.py

Live Odoo Database Comparator for Odoo Code Intelligence.
Compares static security graph declarations against live database rules via XML-RPC.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
import logging

from code_intelligence.cross_file_resolver import ResolvedSymbolRegistry
from code_intelligence.graph_builder import OdooGraphBuilder

_logger = logging.getLogger(__name__)


@dataclass
class DivergenceDetail:
    divergence_type: str # "GROUP_ADDED_IN_LIVE", "DOMAIN_MODIFIED", "RULE_DISABLED_IN_LIVE"
    symbol_name: str
    static_value: str
    live_value: str
    explanation: str


@dataclass
class DivergenceComparisonResult:
    model_name: str
    has_divergence: bool
    divergences: List[DivergenceDetail] = field(default_factory=list)
    summary_text: str = ""


# TTL Cache storage
_LIVE_CACHE: Dict[str, Tuple[float, Any]] = {}
CACHE_TTL_SECONDS = 300.0 # 5 minutes


def clear_live_cache():
    """Manual cache invalidation for A4.1.2."""
    global _LIVE_CACHE
    _LIVE_CACHE.clear()
    _logger.info("Cleared Live XML-RPC TTL cache.")


def fetch_live_model_security(model_name: str, odoo_client: Optional[Any] = None) -> Dict[str, Any]:
    """
    Fetch live security rules and ACLs from Odoo database via XML-RPC.
    Uses 5-minute TTL cache (A4.1.2).
    """
    cache_key = f"live_sec:{model_name}"
    now = time.time()

    if cache_key in _LIVE_CACHE:
        ts, cached_data = _LIVE_CACHE[cache_key]
        if now - ts < CACHE_TTL_SECONDS:
            _logger.info("Returned live security for '%s' from TTL cache.", model_name)
            return cached_data

    # Perform live fetching if client available or simulate
    live_data: Dict[str, Any] = {"rules": [], "acls": []}

    if odoo_client:
        try:
            # Query ir.rule for model
            rule_ids = odoo_client.search("ir.rule", [("model_id.model", "=", model_name)])
            rules = odoo_client.read("ir.rule", rule_ids, ["name", "domain_force", "active", "groups"])
            live_data["rules"] = rules

            # Query ir.model.access for model
            acl_ids = odoo_client.search("ir.model.access", [("model_id.model", "=", model_name)])
            acls = odoo_client.read("ir.model.access", acl_ids, ["name", "group_id", "perm_read", "perm_write", "perm_create", "perm_unlink"])
            live_data["acls"] = acls

        except Exception as e:
            _logger.error("XML-RPC call failed for model %s: %s", model_name, e)

    _LIVE_CACHE[cache_key] = (now, live_data)
    return live_data


def compare_static_vs_live_rules(
    registry: ResolvedSymbolRegistry,
    model_name: str,
    live_data: Dict[str, Any]
) -> DivergenceComparisonResult:
    """
    Compares static code security graph against live database rules.
    Detects divergence types: GROUP_ADDED_IN_LIVE, DOMAIN_MODIFIED, RULE_DISABLED_IN_LIVE.
    """
    divergences: List[DivergenceDetail] = []

    clean_model_target = model_name.replace(".", "_")
    static_rules = [
        r for r in registry.rules.values()
        if r.model_id and clean_model_target in r.model_id.replace(".", "_")
    ]
    live_rules = live_data.get("rules", [])

    # 1. Compare Rules
    for l_rule in live_rules:
        l_name = l_rule.get("name", "")
        l_domain = l_rule.get("domain_force", "")
        l_active = l_rule.get("active", True)

        # Check if disabled in live
        if not l_active:
            divergences.append(
                DivergenceDetail(
                    divergence_type="RULE_DISABLED_IN_LIVE",
                    symbol_name=l_name,
                    static_value="active: True (XML)",
                    live_value="active: False (DB)",
                    explanation=f"Rule '{l_name}' is active in static XML but disabled (active=False) in live database."
                )
            )

        # Find matching static rule
        matching_static = None
        for s_rule in static_rules:
            if s_rule.name == l_name or s_rule.xml_id in l_name:
                matching_static = s_rule
                break

        if matching_static:
            # Check domain force modification
            if matching_static.domain_force.strip() != l_domain.strip():
                divergences.append(
                    DivergenceDetail(
                        divergence_type="DOMAIN_MODIFIED",
                        symbol_name=l_name,
                        static_value=matching_static.domain_force,
                        live_value=l_domain,
                        explanation=f"Domain for rule '{l_name}' was modified in database: Static='{matching_static.domain_force}' vs Live='{l_domain}'."
                    )
                )
        else:
            # Rule created in live DB
            divergences.append(
                DivergenceDetail(
                    divergence_type="GROUP_ADDED_IN_LIVE",
                    symbol_name=l_name,
                    static_value="Not in Code",
                    live_value=f"Domain: {l_domain}",
                    explanation=f"Rule '{l_name}' exists in live database but is absent from static source code."
                )
            )

    has_divergence = len(divergences) > 0
    summary = (
        f"Divergence Analysis for '{model_name}': {len(divergences)} divergences detected."
        if has_divergence
        else f"Divergence Analysis for '{model_name}': Static code and live database are 100% in sync."
    )

    return DivergenceComparisonResult(
        model_name=model_name,
        has_divergence=has_divergence,
        divergences=divergences,
        summary_text=summary,
    )
