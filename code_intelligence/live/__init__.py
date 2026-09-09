"""
Live Odoo XML-RPC Subpackage -- RPC client plus static-vs-live security
comparison/validation (J5, A4.1.2).
"""

from code_intelligence.live.rpc_client import OdooRpcClient, OdooRpcError, VALID_OPERATIONS
from code_intelligence.live.comparator import (
    DivergenceDetail,
    DivergenceComparisonResult,
    CACHE_TTL_SECONDS,
    clear_live_cache,
    fetch_live_model_security,
    compare_static_vs_live_rules,
)
from code_intelligence.live.validator import (
    LiveRuleReference,
    LiveRuleValidationResult,
    validate_live_rule_prediction,
)

__all__ = [
    "OdooRpcClient",
    "OdooRpcError",
    "VALID_OPERATIONS",
    "DivergenceDetail",
    "DivergenceComparisonResult",
    "CACHE_TTL_SECONDS",
    "clear_live_cache",
    "fetch_live_model_security",
    "compare_static_vs_live_rules",
    "LiveRuleReference",
    "LiveRuleValidationResult",
    "validate_live_rule_prediction",
]
