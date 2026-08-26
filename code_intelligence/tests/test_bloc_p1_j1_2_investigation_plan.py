"""
code_intelligence/tests/test_bloc_p1_j1_2_investigation_plan.py

Unit tests for Bloc P1 Jour 1-2:
1. InvestigationPlan and InvestigationStep serializable schemas.
2. QuestionIntent classification across domains.
3. concept_suggests_code_intelligence_v2 replacing GOVERNANCE_SIGNAL_TERMS.
4. Deterministic plan generation for each intent.
"""

import pytest

from code_intelligence.business_resolver import ResolvedConcept
from code_intelligence.investigation_plan import (
    InvestigationPlan,
    InvestigationStep,
    PlanAction,
    PlanGenerationSource,
    QuestionIntent,
    classify_question_intent,
    concept_suggests_code_intelligence_v2,
    generate_investigation_plan,
)
from code_intelligence.semantic_tags import BehavioralTag, TechnicalTag


# ── 1. Schema Validation & Serialization ─────────────────────────────────────

def test_investigation_step_schema_instantiation():
    step = InvestigationStep(
        action=PlanAction.WHO_HAS_ACCESS_TO,
        target="custom.purchase.request",
        justification="Vérifier les ACLs",
        behavioral_focus=BehavioralTag.VISIBILITY_RULE,
        technical_focus=TechnicalTag.ACL,
    )
    assert step.action == PlanAction.WHO_HAS_ACCESS_TO
    assert step.target == "custom.purchase.request"
    assert step.behavioral_focus == BehavioralTag.VISIBILITY_RULE
    assert step.technical_focus == TechnicalTag.ACL

    d = step.model_dump()
    assert d["action"] == "who_has_access_to"
    assert d["target"] == "custom.purchase.request"


def test_investigation_plan_serialization_and_display_dict():
    step = InvestigationStep(
        action=PlanAction.EVALUATE_RECORD_RULES,
        target="account.move",
        justification="Vérifier les règles multi-sociétés",
        behavioral_focus=BehavioralTag.VISIBILITY_RULE,
        technical_focus=TechnicalTag.RECORD_RULE,
    )
    plan = InvestigationPlan(
        question="Qui peut voir un avoir de 80 000€ ?",
        intent=QuestionIntent.GOVERNANCE_SECURITY,
        target_models=["account.move"],
        steps=[step],
        rationale="Plan d'accès et visibilité",
        confidence=1.0,
        source=PlanGenerationSource.DETERMINISTIC_SEMANTIC,
    )

    display = plan.to_display_dict()
    assert display["intent"] == "governance_security"
    assert display["target_models"] == ["account.move"]
    assert len(display["steps"]) == 1
    assert display["steps"][0]["step_index"] == 1
    assert display["steps"][0]["action"] == "evaluate_record_rules"
    assert display["steps"][0]["behavioral_focus"] == "visibility_rule"
    assert display["steps"][0]["technical_focus"] == "record_rule"


# ── 2. Question Intent Classification ────────────────────────────────────────

@pytest.mark.parametrize("question, expected_intent", [
    ("Qui a le droit d'approuver un avoir de 25000€ ?", QuestionIntent.GOVERNANCE_SECURITY),
    ("Est-ce qu'un utilisateur peut voir ce document ?", QuestionIntent.GOVERNANCE_SECURITY),
    ("Pourquoi ce montant est masqué pour l'employé ?", QuestionIntent.GOVERNANCE_SECURITY),
    ("Quelles sont les étapes du workflow de validation des congés ?", QuestionIntent.WORKFLOW_STATE),
    ("Quel bouton permet de passer de draft à confirme ?", QuestionIntent.WORKFLOW_STATE),
    ("Comment est calculé le montant total et quel est l'impact ?", QuestionIntent.CALCULATION_LOGIC),
    ("Quelles sont les surcharges et l'arbre d'héritage de account.move ?", QuestionIntent.INHERITANCE_STRUCTURE),
    ("Quelles actions automatiques ou cron sont configurés ?", QuestionIntent.AUTOMATION_ACTION),
    ("Combien de factures impayées avons-nous ce mois-ci ?", QuestionIntent.ERP_DATA_QUERY),
    ("Quelle est la procédure selon le wiki interne ?", QuestionIntent.DOCUMENTARY_POLICY),
    ("Selon le wiki, comment fonctionne la mise à disposition ?", QuestionIntent.DOCUMENTARY_POLICY),
])
def test_classify_question_intent_patterns(question, expected_intent):
    concept = ResolvedConcept(
        user_term="test",
        resolved_models=["account.move"],
        source_step="static_alias",
        is_resolved=True,
    )
    intent = classify_question_intent(question, resolved_concept=concept)
    assert intent == expected_intent


# ── 3. Replacement of GOVERNANCE_SIGNAL_TERMS ────────────────────────────────

def test_concept_suggests_code_intelligence_v2_with_unresolved_concept():
    concept = ResolvedConcept(
        user_term="inconnu",
        resolved_models=[],
        source_step="unresolved",
        is_resolved=False,
    )
    assert not concept_suggests_code_intelligence_v2("Qui peut valider ?", concept)
    assert not concept_suggests_code_intelligence_v2("Qui peut valider ?", None)


def test_concept_suggests_code_intelligence_v2_protects_doc08_counterexample():
    """
    DOC-08 counter-example: question asks about procedures 'selon le wiki' for
    'mise a disposition' (resolves to custom.asset.loan). Must NOT route to Code Intelligence.
    """
    concept = ResolvedConcept(
        user_term="mise a disposition",
        resolved_models=["custom.asset.loan"],
        source_step="static_alias",
        is_resolved=True,
    )
    question = "Quelles sont les procédures de mise à disposition de matériel selon le wiki ?"
    assert not concept_suggests_code_intelligence_v2(question, concept)


@pytest.mark.parametrize("h4_question, model_name", [
    ("Qui a le droit d'approuver les avoirs VIP ?", "account.move"),
    ("Est-ce qu'une règle de gestion bloque la validation des congés urgents ?", "hr.leave"),
    ("Qui peut valider une demande d'achat de plus de 15000€ ?", "custom.purchase.request"),
    ("Quelles sont les règles de visibilité pour les prêts de matériel ?", "custom.asset.loan"),
    ("Un employé peut-il voir les documents deep sans autorisation ?", "custom.deep.document"),
])
def test_concept_suggests_code_intelligence_v2_covers_all_h4_questions(h4_question, model_name):
    concept = ResolvedConcept(
        user_term=model_name,
        resolved_models=[model_name],
        source_step="static_alias",
        is_resolved=True,
    )
    assert concept_suggests_code_intelligence_v2(h4_question, concept)


# ── 4. Plan Generation Tests ─────────────────────────────────────────────────

def test_generate_investigation_plan_governance_with_amount():
    concept = ResolvedConcept(
        user_term="avoir",
        resolved_models=["account.move"],
        source_step="static_alias",
        is_resolved=True,
    )
    plan = generate_investigation_plan(
        question="Qui peut voir un avoir de 80 000€ pour la société Alpha ?",
        resolved_concept=concept,
    )
    assert plan.intent == QuestionIntent.GOVERNANCE_SECURITY
    assert plan.target_models == ["account.move"]
    actions = [s.action for s in plan.steps]
    assert PlanAction.WHO_HAS_ACCESS_TO in actions
    assert PlanAction.EVALUATE_RECORD_RULES in actions
    assert PlanAction.ANALYZE_SECURITY_LOCKS in actions
    assert PlanAction.CAN_VIEW_AMOUNT in actions


def test_generate_investigation_plan_workflow():
    concept = ResolvedConcept(
        user_term="demande d'achat",
        resolved_models=["custom.purchase.request"],
        source_step="static_alias",
        is_resolved=True,
    )
    plan = generate_investigation_plan(
        question="Quelles sont les étapes du workflow et boutons de validation ?",
        resolved_concept=concept,
    )
    assert plan.intent == QuestionIntent.WORKFLOW_STATE
    actions = [s.action for s in plan.steps]
    assert PlanAction.DESCRIBE_WORKFLOW in actions
    assert PlanAction.BUTTON_EXECUTION_PATH in actions
    assert PlanAction.ANALYZE_SERVER_ACTIONS in actions


def test_generate_investigation_plan_calculation():
    concept = ResolvedConcept(
        user_term="facture",
        resolved_models=["account.move"],
        source_step="static_alias",
        is_resolved=True,
    )
    plan = generate_investigation_plan(
        question="Comment est calculé le montant et quel est l'impact des modifications ?",
        resolved_concept=concept,
    )
    assert plan.intent == QuestionIntent.CALCULATION_LOGIC
    actions = [s.action for s in plan.steps]
    assert PlanAction.FIELD_CHANGE_IMPACT in actions
    assert PlanAction.ANALYZE_METHOD_OVERRIDE_CHAIN in actions


def test_generate_investigation_plan_unresolved_concept_fallback():
    plan = generate_investigation_plan(
        question="Question sans modèle identifié",
        resolved_concept=None,
    )
    assert plan.source == PlanGenerationSource.FALLBACK_HEURISTIC
    assert len(plan.steps) >= 1
    assert plan.target_models == []
