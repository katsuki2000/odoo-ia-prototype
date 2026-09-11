"""
code_intelligence/investigation_plan_builders.py

Intent-specific step generators for the Code Intelligence investigation planner.
"""

from typing import Any, List, Optional

from code_intelligence.agent.business_resolver import ResolvedConcept
from code_intelligence.agent.investigation.schemas import (
    InvestigationStep,
    PlanAction,
)
from code_intelligence.knowledge_rules.ontology import BehavioralTag, TechnicalTag


def plan_governance_security(
    question: str,
    primary_model: str,
    resolved_concept: Optional[ResolvedConcept],
    G: Optional[Any],
) -> List[InvestigationStep]:
    """Build investigation steps for GOVERNANCE_SECURITY intent."""
    from code_intelligence.agent.ci_agent_node.context.context_extractors import (
        _question_is_access_related,
        _question_is_approval_related,
        _extract_amount,
    )
    from code_intelligence.agent.ci_agent_node.guards.dispatch_utils import _question_suggests_automation_bypass

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
            from code_intelligence.agent.ci_agent_node.predispatch.forced_dispatch_predicates import (
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
