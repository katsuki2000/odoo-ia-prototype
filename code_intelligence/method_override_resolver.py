"""
method_override_resolver.py

Facade re-exporting method override chain resolution, AST risk detection,
and composition across modular sub-units:
- override_types: MethodOverrideSite, MethodOverrideChainResult, resolve_method_override_chain
- override_unguarded_super: detect_unguarded_super, UNGUARDED_SUPER_WARNING_TEMPLATE
- override_relational_chains: detect_unchecked_relational_chain, find_methods_with_override_risk_findings
- override_llm_interpreter: interpret_override_chain_with_llm
- override_composer: analyze_method_override_chain, analyze_method_override_chain_with_evidence

Preserves complete backward compatibility for all callers and unit tests.
"""

from code_intelligence.override_types import (
    MethodOverrideSite,
    MethodOverrideChainResult,
    resolve_method_override_chain,
)

from code_intelligence.override_unguarded_super import (
    _branch_returns_or_raises,
    _STATE_MUTATING_CALL_NAMES,
    _branch_mutates_record_state,
    _UnguardedSuperVisitor,
    UNGUARDED_SUPER_WARNING_TEMPLATE,
    detect_unguarded_super,
)

from code_intelligence.override_relational_chains import (
    _RELATIONAL_CHAIN_MIN_DEPTH,
    _attribute_chain_depth,
    _attribute_chain_names,
    _UncheckedRelationalChainVisitor,
    _find_guarding_condition_for_helper_call,
    detect_unchecked_relational_chain,
    find_methods_with_override_risk_findings,
    find_methods_with_unguarded_super_and_relational_risk,
    find_methods_with_unguarded_super,
)

from code_intelligence.override_llm_interpreter import (
    _LLM_CONFIDENCE_CLOSED_SET,
    _INTERPRETATION_SYSTEM_PROMPT,
    interpret_override_chain_with_llm,
)

from code_intelligence.override_composer import (
    _build_override_chain_evidence_no_sites,
    _build_override_chain_site_evidence,
    _build_override_chain_check_evidence,
    _compose_compute_methods_overview,
    _compose_method_override_chain,
    analyze_method_override_chain,
    analyze_method_override_chain_with_evidence,
)

__all__ = [
    "MethodOverrideSite",
    "MethodOverrideChainResult",
    "resolve_method_override_chain",
    "detect_unguarded_super",
    "detect_unchecked_relational_chain",
    "find_methods_with_override_risk_findings",
    "find_methods_with_unguarded_super_and_relational_risk",
    "find_methods_with_unguarded_super",
    "UNGUARDED_SUPER_WARNING_TEMPLATE",
    "analyze_method_override_chain",
    "analyze_method_override_chain_with_evidence",
    "interpret_override_chain_with_llm",
    "_branch_returns_or_raises",
    "_STATE_MUTATING_CALL_NAMES",
    "_branch_mutates_record_state",
    "_UnguardedSuperVisitor",
    "_RELATIONAL_CHAIN_MIN_DEPTH",
    "_attribute_chain_depth",
    "_attribute_chain_names",
    "_UncheckedRelationalChainVisitor",
    "_find_guarding_condition_for_helper_call",
    "_build_override_chain_evidence_no_sites",
    "_build_override_chain_site_evidence",
    "_build_override_chain_check_evidence",
    "_compose_compute_methods_overview",
    "_compose_method_override_chain",
    "_LLM_CONFIDENCE_CLOSED_SET",
    "_INTERPRETATION_SYSTEM_PROMPT",
]
