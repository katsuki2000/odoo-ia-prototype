"""
Investigation Planning & Intent Classification Subpackage.
"""

from code_intelligence.investigation.schemas import (
    PlanAction,
    QuestionIntent,
    INTENT_TO_ROUTE,
    PlanGenerationSource,
    InvestigationStep,
    InvestigationPlan,
    _fold_accents,
)
from code_intelligence.investigation.classifier import (
    classify_question_intent,
    has_documentary_anchor,
    concept_suggests_code_intelligence_v2,
)
from code_intelligence.investigation.llm import (
    classify_question_intent_llm,
    resolve_question_intent,
    IntentResolution,
    IntentClassificationLLMResponse,
)
from code_intelligence.investigation.planner import (
    generate_investigation_plan,
    validate_plan_against_route,
)

# Alias for convenience
build_investigation_plan = generate_investigation_plan

__all__ = [
    "PlanAction",
    "QuestionIntent",
    "INTENT_TO_ROUTE",
    "PlanGenerationSource",
    "InvestigationStep",
    "InvestigationPlan",
    "_fold_accents",
    "classify_question_intent",
    "has_documentary_anchor",
    "concept_suggests_code_intelligence_v2",
    "classify_question_intent_llm",
    "resolve_question_intent",
    "IntentResolution",
    "IntentClassificationLLMResponse",
    "generate_investigation_plan",
    "build_investigation_plan",
    "validate_plan_against_route",
]
