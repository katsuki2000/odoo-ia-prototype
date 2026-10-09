"""
code_intelligence/investigation_plan_builders.py

Intent-specific step generators for the Code Intelligence investigation planner.
"""

from typing import Any, List, Optional

from code_intelligence.agent.resolver import ResolvedConcept
from code_intelligence.agent.investigation_schemas import (
    InvestigationStep,
    PlanAction,
)
from code_intelligence.rules.ontology import BehavioralTag, TechnicalTag


def plan_governance_security(
    question: str,
    primary_model: str,
    resolved_concept: Optional[ResolvedConcept],
    G: Optional[Any],
) -> List[InvestigationStep]:
    """Build investigation steps for GOVERNANCE_SECURITY intent."""
    from code_intelligence.agent.context_extractors import (
        _question_is_access_related,
        _question_is_approval_related,
        _extract_amount,
    )
    from code_intelligence.agent.dispatch_guards import _question_suggests_automation_bypass

    is_access_related = _question_is_access_related(question)
    is_approval_related = _question_is_approval_related(question)
    is_automation_bypass = _question_suggests_automation_bypass(question)
    amount = _extract_amount(question)

    has_security_lock_source = True  # conservative: assume present without a graph
    has_server_action_nodes = False
    has_override_cascade = False
    has_who_has_access_target = is_access_related
    if G is not None:
        try:
            from code_intelligence.agent.forced_dispatch_predicates import (
                security_locks_targets,
                server_actions_targets,
                override_chain_targets,
                who_has_access_targets,
            )
            has_security_lock_source = primary_model in security_locks_targets(resolved_concept, G)
            has_server_action_nodes = primary_model in server_actions_targets(question, resolved_concept, G)
            has_override_cascade = any(
                m == primary_model for m, _ in override_chain_targets(question, resolved_concept, G)
            )
            has_who_has_access_target = primary_model in who_has_access_targets(question, resolved_concept, G)
        except Exception:
            pass

    steps: List[InvestigationStep] = []

    # 1. ACL permissions
    if has_who_has_access_target:
        steps.append(
            InvestigationStep(
                action=PlanAction.WHO_HAS_ACCESS_TO,
                target=primary_model,
                justification=f"Évaluer la matrice des droits d'accès ACL (ir.model.access) pour {primary_model}",
                behavioral_focus=BehavioralTag.VISIBILITY_RULE,
                technical_focus=TechnicalTag.ACL,
            )
        )

    # 2. Record rules
    if is_access_related and amount is not None:
        steps.append(
            InvestigationStep(
                action=PlanAction.EVALUATE_RECORD_RULES,
                target=primary_model,
                justification=f"Évaluer les règles d'enregistrement actives (ir.rule) et filtrages multi-sociétés sur {primary_model}",
                behavioral_focus=BehavioralTag.VISIBILITY_RULE,
                technical_focus=TechnicalTag.RECORD_RULE,
            )
        )

    # 3. Python security locks
    if has_security_lock_source:
        steps.append(
            InvestigationStep(
                action=PlanAction.ANALYZE_SECURITY_LOCKS,
                target=primary_model,
                justification=f"Scanner les verrous Python, exceptions levées et contournements de groupe dans {primary_model}",
                behavioral_focus=BehavioralTag.BLOCKING_RULE,
                technical_focus=TechnicalTag.CONSTRAINT,
            )
        )

    # 4. can_view_amount_v2
    if is_access_related and amount is not None:
        steps.append(
            InvestigationStep(
                action=PlanAction.CAN_VIEW_AMOUNT,
                target=primary_model,
                justification=f"Calculer le verdict déterministe de visibilité avec montant sur {primary_model}",
                behavioral_focus=BehavioralTag.VISIBILITY_RULE,
                technical_focus=TechnicalTag.RECORD_RULE,
            )
        )

    # 5. Method override chain
    if is_approval_related and has_override_cascade:
        steps.append(
            InvestigationStep(
                action=PlanAction.ANALYZE_METHOD_OVERRIDE_CHAIN,
                target=primary_model,
                justification=f"Vérifier si un override cascade dilue ou contredit une condition d'approbation sur {primary_model}",
                behavioral_focus=BehavioralTag.APPROVAL_RULE,
                technical_focus=None,
            )
        )

    # 6. Server actions
    if is_automation_bypass and has_server_action_nodes:
        steps.append(
            InvestigationStep(
                action=PlanAction.ANALYZE_SERVER_ACTIONS,
                target=primary_model,
                justification=f"Vérifier si une action serveur ou automatisation contourne la condition évoquée sur {primary_model}",
                behavioral_focus=BehavioralTag.NOTIFICATION_RULE,
                technical_focus=TechnicalTag.SERVER_ACTION,
            )
        )

    if not steps:
        steps.append(
            InvestigationStep(
                action=PlanAction.READ_SOURCE_CODE,
                target=primary_model,
                justification=(
                    f"Aucun signal d'accès/approbation/automatisation/verrou structurel "
                    f"détecté par les détecteurs partagés pour {primary_model} -- "
                    f"inspection manuelle du code source recommandée en l'absence de "
                    f"correspondance avec un outil composite déterministe"
                ),
                behavioral_focus=None,
                technical_focus=None,
            )
        )

    return steps


def plan_workflow_state(primary_model: str) -> List[InvestigationStep]:
    """Build investigation steps for WORKFLOW_STATE intent."""
    return [
        InvestigationStep(
            action=PlanAction.DESCRIBE_WORKFLOW,
            target=primary_model,
            justification=f"Extraire le graphe d'états et de transitions du workflow pour {primary_model}",
            behavioral_focus=BehavioralTag.WORKFLOW_RULE,
            technical_focus=None,
        ),
        InvestigationStep(
            action=PlanAction.BUTTON_EXECUTION_PATH,
            target=primary_model,
            justification=f"Tracer les méthodes et permissions requises par les boutons de validation sur {primary_model}",
            behavioral_focus=BehavioralTag.APPROVAL_RULE,
            technical_focus=TechnicalTag.CONSTRAINT,
        ),
        InvestigationStep(
            action=PlanAction.ANALYZE_SERVER_ACTIONS,
            target=primary_model,
            justification=f"Vérifier les actions automatisées déclenchées lors des changements d'état sur {primary_model}",
            behavioral_focus=BehavioralTag.WORKFLOW_RULE,
            technical_focus=TechnicalTag.CRON,
        ),
    ]


def plan_navigation_howto(primary_model: str) -> List[InvestigationStep]:
    """Build investigation steps for NAVIGATION_HOWTO intent."""
    return [
        InvestigationStep(
            action=PlanAction.DESCRIBE_NAVIGATION_PATH,
            target=primary_model,
            justification=f"Trouver les menus et les boutons qui mènent à {primary_model} dans l'interface",
            behavioral_focus=BehavioralTag.VISIBILITY_RULE,
            technical_focus=None,
        ),
    ]


def plan_calculation_logic(primary_model: str) -> List[InvestigationStep]:
    """Build investigation steps for CALCULATION_LOGIC intent."""
    return [
        InvestigationStep(
            action=PlanAction.FIELD_CHANGE_IMPACT,
            target=primary_model,
            justification=f"Analyser l'arbre de calcul et les dépendances des champs calculés sur {primary_model}",
            behavioral_focus=BehavioralTag.CALCULATION_RULE,
            technical_focus=TechnicalTag.COMPUTED_FIELD,
        ),
        InvestigationStep(
            action=PlanAction.ANALYZE_METHOD_OVERRIDE_CHAIN,
            target=primary_model,
            justification=f"Vérifier les surcharges Python de calcul dans la cascade des modules pour {primary_model}",
            behavioral_focus=BehavioralTag.CALCULATION_RULE,
            technical_focus=None,
        ),
    ]


def plan_inheritance_structure(primary_model: str) -> List[InvestigationStep]:
    """Build investigation steps for INHERITANCE_STRUCTURE intent."""
    return [
        InvestigationStep(
            action=PlanAction.TRACE_FULL_INHERITANCE,
            target=primary_model,
            justification=f"Reconstituer la hiérarchie complète _inherit et _inherits pour {primary_model}",
            behavioral_focus=None,
            technical_focus=None,
        ),
        InvestigationStep(
            action=PlanAction.ANALYZE_METHOD_OVERRIDE_CHAIN,
            target=primary_model,
            justification=f"Résoudre l'ordre MRO d'exécution des méthodes surchargées pour {primary_model}",
            behavioral_focus=BehavioralTag.BLOCKING_RULE,
            technical_focus=None,
        ),
    ]


def plan_automation_action(primary_model: str) -> List[InvestigationStep]:
    """Build investigation steps for AUTOMATION_ACTION intent."""
    return [
        InvestigationStep(
            action=PlanAction.ANALYZE_SERVER_ACTIONS,
            target=primary_model,
            justification=f"Inspecter les Server Actions et Automated Actions associées à {primary_model}",
            behavioral_focus=BehavioralTag.NOTIFICATION_RULE,
            technical_focus=TechnicalTag.SERVER_ACTION,
        ),
    ]


def plan_general_code_inquiry(primary_model: str) -> List[InvestigationStep]:
    """Build investigation steps for GENERAL_CODE_INQUIRY intent fallback."""
    return [
        InvestigationStep(
            action=PlanAction.WHO_HAS_ACCESS_TO,
            target=primary_model,
            justification=f"Inspecter les permissions de base pour {primary_model}",
            behavioral_focus=BehavioralTag.VISIBILITY_RULE,
            technical_focus=TechnicalTag.ACL,
        ),
    ]

# ── Planner ─────────────────────────────────────────────────────────────

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

from code_intelligence.agent.resolver import ResolvedConcept
from code_intelligence.agent.investigation_classifier import (
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
from code_intelligence.agent.investigation_llm import (
    _INTENT_CLASSIFICATION_SYSTEM_PROMPT,
    IntentClassificationLLMResponse,
    IntentResolution,
    classify_question_intent_llm,
    resolve_question_intent,
)
from code_intelligence.agent.investigation_schemas import (
    INTENT_TO_ROUTE,
    InvestigationPlan,
    InvestigationStep,
    PlanAction,
    PlanGenerationSource,
    QuestionIntent,
    _fold_accents,
)
from code_intelligence.rules.ontology import BehavioralTag, TechnicalTag

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
        ip_mod = sys.modules.get("code_intelligence.agent.investigation_planner")
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

    elif intent == QuestionIntent.NAVIGATION_HOWTO:
        steps = plan_navigation_howto(primary_model)

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
