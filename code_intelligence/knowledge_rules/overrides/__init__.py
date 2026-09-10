"""
Method Override Resolution & Cascade Subpackage.
"""

from code_intelligence.knowledge_rules.overrides.types import (
    MethodOverrideSite,
    MethodOverrideChainResult,
    resolve_method_override_chain,
)
from code_intelligence.knowledge_rules.overrides.unguarded_super import (
    UNGUARDED_SUPER_WARNING_TEMPLATE,
    detect_unguarded_super,
)
from code_intelligence.knowledge_rules.overrides.relational_chains import (
    detect_unchecked_relational_chain,
    find_methods_with_override_risk_findings,
    find_methods_with_unguarded_super_and_relational_risk,
    find_methods_with_unguarded_super,
)
from code_intelligence.knowledge_rules.overrides.interpreter import (
    interpret_override_chain_with_llm,
)
from code_intelligence.knowledge_rules.overrides.composer import (
    analyze_method_override_chain,
    analyze_method_override_chain_with_evidence,
)
from code_intelligence.knowledge_rules.overrides.cascade import (
    _extract_override_modules,
    _backfill_missing_override_modules,
    _extract_override_chain_amounts,
    _backfill_missing_override_chain_amount,
    _correct_override_cascade_contradictions,
    _rank_and_cap_override_methods,
    _backfill_missing_unguarded_super,
    _extract_unguarded_super_findings,
)

__all__ = [
    "MethodOverrideSite",
    "MethodOverrideChainResult",
    "resolve_method_override_chain",
    "UNGUARDED_SUPER_WARNING_TEMPLATE",
    "detect_unguarded_super",
    "detect_unchecked_relational_chain",
    "find_methods_with_override_risk_findings",
    "find_methods_with_unguarded_super_and_relational_risk",
    "find_methods_with_unguarded_super",
    "interpret_override_chain_with_llm",
    "analyze_method_override_chain",
    "analyze_method_override_chain_with_evidence",
    "_extract_override_modules",
    "_backfill_missing_override_modules",
    "_extract_override_chain_amounts",
    "_backfill_missing_override_chain_amount",
    "_correct_override_cascade_contradictions",
    "_rank_and_cap_override_methods",
    "_backfill_missing_unguarded_super",
    "_extract_unguarded_super_findings",
]
