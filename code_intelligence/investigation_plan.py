"""
code_intelligence/investigation_plan.py

Bloc P1 Jour 1-2 (todo/plan.md, Couche 3 architecture.md):
Serializable Investigation Plan schema, Question Intent classification,
and Semantic Planner logic.

Facade and core orchestration module re-exporting all submodules for complete
backward compatibility.
"""

from typing import Any, List, Optional
import logging

from code_intelligence.business_resolver import ResolvedConcept
from code_intelligence.investigation_plan_builders import (
    plan_automation_action,
    plan_calculation_logic,
    plan_general_code_inquiry,
    plan_governance_security,
    plan_inheritance_structure,
    plan_workflow_state,
)
from code_intelligence.investigation_plan_classifier import (
    _AUTOMATION_PATTERNS,
    _CALCULATION_AMOUNT_PATTERNS,
    _CALCULATION_CODE_PATTERNS,
    _DOC_ANCHOR_PATTERNS,
    _ERP_DATA_PATTERNS,
    _GOVERNANCE_PATTERNS,
    _INHERITANCE_PATTERNS,
    _WEAK_PROCESS_SIGNALS,
    _WORKFLOW_PATTERNS,
    classify_question_intent,
    concept_suggests_code_intelligence_v2,
    has_documentary_anchor,
)
from code_intelligence.investigation_plan_llm import (
    _INTENT_CLASSIFICATION_SYSTEM_PROMPT,
    IntentClassificationLLMResponse,
    IntentResolution,
    classify_question_intent_llm,
    resolve_question_intent,
)
from code_intelligence.investigation_plan_schemas import (
    INTENT_TO_ROUTE,
    InvestigationPlan,
    InvestigationStep,
    PlanAction,
    PlanGenerationSource,
    QuestionIntent,
    _fold_accents,
)
from code_intelligence.semantic_tags import BehavioralTag, TechnicalTag

logger = logging.getLogger(__name__)


# ── Deterministic Semantic Planner (A priori Plan Construction) ──────────────

def generate_investigation_plan(
    question: str,
    resolved_concept: Optional[ResolvedConcept] = None,
    G: Optional[Any] = None,
    user_groups: Optional[List[int]] = None,
    intent: Optional[QuestionIntent] = None,
) -> InvestigationPlan:
    """
    Constructs an explicit, serializable InvestigationPlan BEFORE tool execution.

    Uses deterministic semantic mapping based on:
      1. Resolved concept models (from business_resolver)
      2. Question semantic intent
      3. Graph Couche 3 tags (BehavioralTag / TechnicalTag)
    """
    target_models = resolved_concept.resolved_models if (resolved_concept and resolved_concept.is_resolved) else []
    primary_model = target_models[0] if target_models else ""
    if intent is None:
        import sys
        ip_mod = sys.modules.get("code_intelligence.investigation_plan")
        kw_classifier = getattr(ip_mod, "classify_question_intent", classify_question_intent) if ip_mod else classify_question_intent
        intent = kw_classifier(question, resolved_concept, G)
    steps: List[InvestigationStep] = []

    if not primary_model:
        if intent in (QuestionIntent.DOCUMENTARY_POLICY, QuestionIntent.ERP_DATA_QUERY):
            return InvestigationPlan(
                question=question,
                intent=intent,
                target_models=[],
                steps=[],
                rationale="Aucun signal Code Intelligence détecté et aucun modèle résolu -- pas de plan d'investigation applicable",
                confidence=1.0,
                source=PlanGenerationSource.FALLBACK_HEURISTIC,
            )
        steps.append(
            InvestigationStep(
                action=PlanAction.WHO_HAS_ACCESS_TO,
                target="<unknown_model>",
                justification="Résoudre le modèle cible à partir de la question utilisateur",
                behavioral_focus=BehavioralTag.VISIBILITY_RULE,
                technical_focus=TechnicalTag.ACL,
            )
        )
        return InvestigationPlan(
            question=question,
            intent=intent,
            target_models=[],
            steps=steps,
            rationale="Investigation générique sans modèle cible résolu",
            confidence=0.5,
            source=PlanGenerationSource.FALLBACK_HEURISTIC,
        )

    # ── Intent-Specific Investigation Step Strategy ──────────────────────────

    if intent == QuestionIntent.GOVERNANCE_SECURITY:
        steps = plan_governance_security(question, primary_model, resolved_concept, G)

    elif intent == QuestionIntent.WORKFLOW_STATE:
        steps = plan_workflow_state(primary_model)

    elif intent == QuestionIntent.CALCULATION_LOGIC:
        steps = plan_calculation_logic(primary_model)

    elif intent == QuestionIntent.INHERITANCE_STRUCTURE:
        steps = plan_inheritance_structure(primary_model)

    elif intent == QuestionIntent.AUTOMATION_ACTION:
        steps = plan_automation_action(primary_model)

    elif intent in (QuestionIntent.DOCUMENTARY_POLICY, QuestionIntent.ERP_DATA_QUERY):
        return InvestigationPlan(
            question=question,
            intent=intent,
            target_models=target_models,
            steps=[],
            rationale="Intention documentaire/ERP malgré un modèle résolu -- pas de plan Code Intelligence applicable (DOC-08)",
            confidence=resolved_concept.confidence if resolved_concept else 1.0,
            source=PlanGenerationSource.FALLBACK_HEURISTIC,
        )

    else:
        steps = plan_general_code_inquiry(primary_model)

    rationale = f"Plan d'investigation déterministe pour l'intention '{intent.value}' sur {primary_model} ({len(steps)} étapes planifiées)"

    return InvestigationPlan(
        question=question,
        intent=intent,
        target_models=target_models,
        steps=steps,
        rationale=rationale,
        confidence=resolved_concept.confidence if resolved_concept else 1.0,
        source=PlanGenerationSource.DETERMINISTIC_SEMANTIC,
    )


# ── Plan/Route Coherence Validation (todo/contexte.txt section 385/386) ──────

_ROUTES_WITHOUT_CI_EXECUTION = {"documentaire", "donnees_erp", "hybride"}


def validate_plan_against_route(plan: InvestigationPlan, route_decision: str) -> InvestigationPlan:
    """
    Reconciles the Planner's independently-classified InvestigationPlan
    against the route actually dispatched by route_decision() (core/routing.py).
    """
    if route_decision == "code_intelligence":
        return plan

    if route_decision in _ROUTES_WITHOUT_CI_EXECUTION and plan.steps:
        conflict_detail = (
            f"PLAN_ROUTE_CONFLICT: planned_intent={plan.intent.value} a produit "
            f"{len(plan.steps)} étape(s) Code Intelligence, mais route_decision="
            f"{route_decision} n'exécute jamais d'InvestigationStep -- plan neutralisé (steps=[])."
        )
        logger.warning(conflict_detail)
        return plan.model_copy(update={
            "steps": [],
            "plan_route_conflict": True,
            "conflict_detail": conflict_detail,
        })

    return plan


__all__ = [k for k in globals().keys() if not k.startswith("__")]
