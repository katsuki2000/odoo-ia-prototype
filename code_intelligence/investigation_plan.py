"""
code_intelligence/investigation_plan.py

Bloc P1 Jour 1-2 (todo/plan.md, Couche 3 architecture.md):
Serializable Investigation Plan schema, Question Intent classification,
and Semantic Planner logic.

Replaces the ad-hoc GOVERNANCE_SIGNAL_TERMS list with a principled
intent + ontology-grounded classifier, and provides structured a priori
investigation plans before tool execution.
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from code_intelligence.business_resolver import ResolvedConcept
from code_intelligence.semantic_tags import BehavioralTag, TechnicalTag


# ── Closed Action Vocabulary (The 9 core tools + composite mechanisms) ────────

class PlanAction(str, Enum):
    """Closed vocabulary of investigation actions for the Code Intelligence engine."""
    WHO_HAS_ACCESS_TO = "who_has_access_to"
    EVALUATE_RECORD_RULES = "evaluate_record_rules"
    ANALYZE_SECURITY_LOCKS = "analyze_security_locks"
    CAN_VIEW_AMOUNT = "can_view_amount_v2"
    FIELD_CHANGE_IMPACT = "field_change_impact"
    BUTTON_EXECUTION_PATH = "button_execution_path"
    TRACE_FULL_INHERITANCE = "trace_full_inheritance"
    DESCRIBE_WORKFLOW = "describe_workflow"
    ANALYZE_SERVER_ACTIONS = "analyze_server_actions"
    ANALYZE_METHOD_OVERRIDE_CHAIN = "analyze_method_override_chain"
    READ_SOURCE_CODE = "read_source_code"
    ANALYZE_DATA_CONSTRAINTS = "analyze_data_constraints"


class QuestionIntent(str, Enum):
    """High-level semantic intent of the user question."""
    GOVERNANCE_SECURITY = "governance_security"     # Access, permissions, record rules, locks
    WORKFLOW_STATE = "workflow_state"               # States, transitions, validation buttons
    CALCULATION_LOGIC = "calculation_logic"         # Computed fields, dependencies, amounts
    INHERITANCE_STRUCTURE = "inheritance_structure" # Model extension, override chains, MRO
    AUTOMATION_ACTION = "automation_action"         # Server actions, automations, crons
    ERP_DATA_QUERY = "erp_data_query"               # Live records, counts, aggregations
    DOCUMENTARY_POLICY = "documentary_policy"       # Wiki, general guidelines, how-to
    GENERAL_CODE_INQUIRY = "general_code_inquiry"   # Other technical inspections


class PlanGenerationSource(str, Enum):
    """Source that produced the investigation plan."""
    DETERMINISTIC_SEMANTIC = "deterministic_semantic"
    LLM_BOUNDED_PLANNER = "llm_bounded_planner"
    FALLBACK_HEURISTIC = "fallback_heuristic"


# ── Pydantic & Dataclass Schemas for Serialization ───────────────────────────

class InvestigationStep(BaseModel):
    """
    A single typed investigation step in the a priori plan.
    Matches {action, cible, justification} defined in todo/plan.md.
    """
    model_config = ConfigDict(strict=True)

    action: PlanAction = Field(
        ...,
        description="The specific deterministic or composite tool action to execute",
    )
    target: str = Field(
        ...,
        description="Target entity (model name, field name, method name, or XML-ID)",
    )
    justification: str = Field(
        ...,
        description="Human-readable explanation of why this step is required based on the question",
    )
    behavioral_focus: Optional[BehavioralTag] = Field(
        default=None,
        description="Couche 3 behavioral tag targeted by this step",
    )
    technical_focus: Optional[TechnicalTag] = Field(
        default=None,
        description="Couche 3 technical mechanism targeted by this step",
    )


class InvestigationPlan(BaseModel):
    """
    Complete serializable investigation plan produced BEFORE tool execution.
    Fulfills the Investigation Planner node in architecture.md.
    """
    model_config = ConfigDict(strict=True)

    question: str = Field(
        ...,
        description="Original user question being investigated",
    )
    intent: QuestionIntent = Field(
        ...,
        description="Classified semantic intent of the query",
    )
    target_models: List[str] = Field(
        default_factory=list,
        description="Odoo models identified for investigation via business_resolver",
    )
    steps: List[InvestigationStep] = Field(
        default_factory=list,
        description="Ordered list of investigation steps to perform",
    )
    rationale: str = Field(
        default="",
        description="High-level synthesis of the investigation strategy",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score of the plan formulation (0.0 to 1.0)",
    )
    source: PlanGenerationSource = Field(
        default=PlanGenerationSource.DETERMINISTIC_SEMANTIC,
        description="Mechanism used to generate the plan",
    )

    def to_display_dict(self) -> Dict[str, Any]:
        """Format the plan for Discuss UI verification widget and API exposure."""
        return {
            "intent": self.intent.value,
            "target_models": self.target_models,
            "rationale": self.rationale,
            "source": self.source.value,
            "confidence": self.confidence,
            "steps": [
                {
                    "step_index": idx + 1,
                    "action": step.action.value,
                    "target": step.target,
                    "justification": step.justification,
                    "behavioral_focus": step.behavioral_focus.value if step.behavioral_focus else None,
                    "technical_focus": step.technical_focus.value if step.technical_focus else None,
                }
                for idx, step in enumerate(self.steps)
            ],
        }


# ── Accent Normalization & Token Helpers ─────────────────────────────────────

def _fold_accents(text: str) -> str:
    """Strip diacritics and lowercase text for robust matching."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


# ── Question Intent Classification (Replaces GOVERNANCE_SIGNAL_TERMS) ────────

_GOVERNANCE_PATTERNS = [
    r"\bqui\s+peut\b",
    r"\bqui\s+a\s+(le\s+)?(droit|acces|accès|permission|pouvoir)\b",
    r"\bqui\s+est\s+autoris[eé]\b",
    r"\b(peut|peuvent)[-\s](il|elle|on|ils|elles)\s+(voir|acceder|accéder|modifier|supprimer|creer|créer)\b",
    r"\b(a|ont)[-\s]t[-\s](il|elle|ils|elles)\s+le\s+droit\b",
    r"\b(verrou|verrouill[eé]|bloqu[eé]|interdit|restreint)\b",
    r"\b(regle|règle|ir\.rule|ir_rule|securite|sécurité|acl|permission)\b",
    r"\b(approbation|approuver|valider|validation|signer|signature)\b",
    r"\b(plafond|seuil|limite\s+montant|depasse|dépasse)\b",
    r"\b(masqu[eé]|cach[eé]|invisible|visibilit[eé])\b",
]

_WORKFLOW_PATTERNS = [
    r"\b(etape|étape|workflow|cycle\s+de\s+vie|statut|etat|état)\b",
    r"\b(transition|passer\s+de|bouton|action_valider|action_)\b",
    r"\b(brouillon|draft|confirme|confirmé|annule|annulé|valide|validé)\b",
]

_CALCULATION_PATTERNS = [
    r"\b(calcul[eé]|formule|compute|d[eé]pend|impact|recalcul)\b",
    r"\b(montant\s+total|somme|prix|taxe|tva|pourcentage)\b",
]

_INHERITANCE_PATTERNS = [
    r"\b(heritage|héritage|inherit|override|surcharge|cascade|mro|classe\s+mere|classe\s+parente)\b",
    r"\b(super\(|arbre\s+d'heritage|arbre\s+d'héritage)\b",
]

_AUTOMATION_PATTERNS = [
    r"\b(action\s+automatique|automatisation|cron|declencheur|déclencheur|base\.automation|ir\.actions\.server)\b",
    r"\b(automatiquement|en\s+arriere[- ]plan|tache\s+planifiee|tâche\s+planifiée)\b",
]

_ERP_DATA_PATTERNS = [
    r"\b(combien\s+de|liste\s+des|donne[- ]moi\s+les|quels\s+sont\s+les\s+(derniers|clients|factures|devis|avoirs))\b",
    r"\b(montant\s+total\s+des\s+ventes|chiffre\s+d'affaires|ca\s+de|dans\s+la\s+base)\b",
]

_DOC_ANCHOR_PATTERNS = [
    r"\b(selon\s+le\s+wiki|dans\s+le\s+wiki|wiki\s+interne|guide\s+utilisateur|documentation|procedure|procédure)\b",
    r"\b(ou\s+est\s+documente|où\s+est\s+documenté|politique\s+interne)\b",
]


def classify_question_intent(
    question: str,
    resolved_concept: Optional[ResolvedConcept] = None,
    G: Optional[Any] = None,
) -> QuestionIntent:
    """
    Classifies the user query into a structured QuestionIntent.
    Combines text patterns, resolved concept properties, and graph ontology tags.
    """
    folded = _fold_accents(question)

    # 1. Check explicit documentary anchors (e.g. DOC-08)
    if any(re.search(p, folded) for p in _DOC_ANCHOR_PATTERNS):
        # Unless it specifically asks a quantitative query alongside
        if not any(re.search(p, folded) for p in _ERP_DATA_PATTERNS):
            return QuestionIntent.DOCUMENTARY_POLICY

    # 2-3. Governance vs. workflow disambiguation (section 205 bug: "validation" is an
    # ambiguous term shared by both domains -- it means "approval" in a governance sense
    # but also names a workflow transition ("workflow de validation"). A bare first-match
    # order let a single ambiguous hit on "validation" silently outrank explicit, unambiguous
    # workflow anchors ("workflow", "etape", "bouton", "transition"...) present in the same
    # question. Rather than reordering the two checks (which would just flip which side gets
    # silently outranked) or stripping "validation" from governance (where it legitimately
    # belongs in many other questions), count hits on both sides and let unambiguous workflow
    # anchors win when they co-occur with the ambiguous governance signal.
    governance_hits = sum(1 for p in _GOVERNANCE_PATTERNS if re.search(p, folded))
    workflow_hits = sum(1 for p in _WORKFLOW_PATTERNS if re.search(p, folded))

    if workflow_hits >= 1 and governance_hits == 0:
        return QuestionIntent.WORKFLOW_STATE

    if workflow_hits >= 1 and governance_hits >= 1:
        # _WORKFLOW_PATTERNS are themselves unambiguous workflow anchors ("workflow", "etape",
        # "bouton", "transition", "draft"...) -- none of them overlap with the ambiguous
        # governance term "validation", so a workflow hit here is always a strong anchor.
        return QuestionIntent.WORKFLOW_STATE

    if governance_hits >= 1:
        return QuestionIntent.GOVERNANCE_SECURITY

    # 4. Check calculation / compute patterns
    if any(re.search(p, folded) for p in _CALCULATION_PATTERNS):
        return QuestionIntent.CALCULATION_LOGIC

    # 5. Check inheritance / override patterns
    if any(re.search(p, folded) for p in _INHERITANCE_PATTERNS):
        return QuestionIntent.INHERITANCE_STRUCTURE

    # 6. Check automation / server action patterns
    if any(re.search(p, folded) for p in _AUTOMATION_PATTERNS):
        return QuestionIntent.AUTOMATION_ACTION

    # 7. Check quantitative / ERP live data patterns
    if any(re.search(p, folded) for p in _ERP_DATA_PATTERNS):
        return QuestionIntent.ERP_DATA_QUERY

    # 8. Concept + Graph Tag affinity fallback
    if resolved_concept and resolved_concept.is_resolved and G is not None:
        for model_name in resolved_concept.resolved_models:
            model_node = f"model:{model_name}"
            if model_node in G:
                # If model has workflow state nodes or behavioral tags
                b_tags = G.nodes[model_node].get("behavioral_tags", [])
                if BehavioralTag.WORKFLOW_RULE.value in b_tags:
                    return QuestionIntent.WORKFLOW_STATE

    # 9. No explicit code intelligence signal found, regardless of concept resolution.
    # DOC-08 protection: a resolved concept alone (e.g. "mise à disposition" → custom.asset.loan)
    # does NOT imply a governance/code question — the old GOVERNANCE_SIGNAL_TERMS gate
    # enforced this by requiring a second explicit keyword hit alongside concept resolution.
    return QuestionIntent.DOCUMENTARY_POLICY


def concept_suggests_code_intelligence_v2(
    question: str,
    resolved_concept: Optional[ResolvedConcept],
    G: Optional[Any] = None,
) -> bool:
    """
    Principled replacement for _concept_suggests_code_intelligence() / GOVERNANCE_SIGNAL_TERMS.

    Evaluates whether a query with a resolved concept should route to CODE_INTELLIGENCE:
      - Returns False if concept is unresolved.
      - Returns False if query is explicitly anchored to documentation (e.g. DOC-08).
      - Returns True if classified intent is a Code Intelligence domain
        (GOVERNANCE_SECURITY, WORKFLOW_STATE, CALCULATION_LOGIC, INHERITANCE_STRUCTURE, AUTOMATION_ACTION).
    """
    if resolved_concept is None or not getattr(resolved_concept, "is_resolved", False):
        return False

    intent = classify_question_intent(question, resolved_concept, G)

    # Documentary and ERP live queries do not route to code intelligence via this fallback
    if intent in (QuestionIntent.DOCUMENTARY_POLICY, QuestionIntent.ERP_DATA_QUERY):
        return False

    return True


# ── Deterministic Semantic Planner (A priori Plan Construction) ──────────────

def generate_investigation_plan(
    question: str,
    resolved_concept: Optional[ResolvedConcept] = None,
    G: Optional[Any] = None,
    user_groups: Optional[List[int]] = None,
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
    intent = classify_question_intent(question, resolved_concept, G)
    steps: List[InvestigationStep] = []

    if not primary_model:
        # Fallback plan when no specific model is resolved
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
        # 1. ACL permissions
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
        steps.append(
            InvestigationStep(
                action=PlanAction.ANALYZE_SECURITY_LOCKS,
                target=primary_model,
                justification=f"Scanner les verrous Python, exceptions levées et contournements de groupe dans {primary_model}",
                behavioral_focus=BehavioralTag.BLOCKING_RULE,
                technical_focus=TechnicalTag.CONSTRAINT,
            )
        )
        # 4. If amount present, add can_view_amount_v2 step
        if any(w in question.lower() for w in ("montant", "€", "euro", "seuil", "plafond", "000")):
            steps.append(
                InvestigationStep(
                    action=PlanAction.CAN_VIEW_AMOUNT,
                    target=primary_model,
                    justification=f"Calculer le verdict déterministe de visibilité avec montant sur {primary_model}",
                    behavioral_focus=BehavioralTag.VISIBILITY_RULE,
                    technical_focus=TechnicalTag.RECORD_RULE,
                )
            )

    elif intent == QuestionIntent.WORKFLOW_STATE:
        # 1. Workflow transitions
        steps.append(
            InvestigationStep(
                action=PlanAction.DESCRIBE_WORKFLOW,
                target=primary_model,
                justification=f"Extraire le graphe d'états et de transitions du workflow pour {primary_model}",
                behavioral_focus=BehavioralTag.WORKFLOW_RULE,
                technical_focus=None,
            )
        )
        # 2. Button execution paths
        steps.append(
            InvestigationStep(
                action=PlanAction.BUTTON_EXECUTION_PATH,
                target=primary_model,
                justification=f"Tracer les méthodes et permissions requises par les boutons de validation sur {primary_model}",
                behavioral_focus=BehavioralTag.APPROVAL_RULE,
                technical_focus=TechnicalTag.CONSTRAINT,
            )
        )
        # 3. Automations
        steps.append(
            InvestigationStep(
                action=PlanAction.ANALYZE_SERVER_ACTIONS,
                target=primary_model,
                justification=f"Vérifier les actions automatisées déclenchées lors des changements d'état sur {primary_model}",
                behavioral_focus=BehavioralTag.WORKFLOW_RULE,
                technical_focus=TechnicalTag.CRON,
            )
        )

    elif intent == QuestionIntent.CALCULATION_LOGIC:
        # 1. Field change impact / compute chain
        steps.append(
            InvestigationStep(
                action=PlanAction.FIELD_CHANGE_IMPACT,
                target=primary_model,
                justification=f"Analyser l'arbre de calcul et les dépendances des champs calculés sur {primary_model}",
                behavioral_focus=BehavioralTag.CALCULATION_RULE,
                technical_focus=TechnicalTag.COMPUTED_FIELD,
            )
        )
        # 2. Method overrides
        steps.append(
            InvestigationStep(
                action=PlanAction.ANALYZE_METHOD_OVERRIDE_CHAIN,
                target=primary_model,
                justification=f"Vérifier les surcharges Python de calcul dans la cascade des modules pour {primary_model}",
                behavioral_focus=BehavioralTag.CALCULATION_RULE,
                technical_focus=None,
            )
        )

    elif intent == QuestionIntent.INHERITANCE_STRUCTURE:
        # 1. Full inheritance tree
        steps.append(
            InvestigationStep(
                action=PlanAction.TRACE_FULL_INHERITANCE,
                target=primary_model,
                justification=f"Reconstituer la hiérarchie complète _inherit et _inherits pour {primary_model}",
                behavioral_focus=None,
                technical_focus=None,
            )
        )
        # 2. Method override chain
        steps.append(
            InvestigationStep(
                action=PlanAction.ANALYZE_METHOD_OVERRIDE_CHAIN,
                target=primary_model,
                justification=f"Résoudre l'ordre MRO d'exécution des méthodes surchargées pour {primary_model}",
                behavioral_focus=BehavioralTag.BLOCKING_RULE,
                technical_focus=None,
            )
        )

    elif intent == QuestionIntent.AUTOMATION_ACTION:
        # 1. Server actions & automations
        steps.append(
            InvestigationStep(
                action=PlanAction.ANALYZE_SERVER_ACTIONS,
                target=primary_model,
                justification=f"Inspecter les Server Actions et Automated Actions associées à {primary_model}",
                behavioral_focus=BehavioralTag.NOTIFICATION_RULE,
                technical_focus=TechnicalTag.SERVER_ACTION,
            )
        )

    else:
        # General code inquiry fallback
        steps.append(
            InvestigationStep(
                action=PlanAction.WHO_HAS_ACCESS_TO,
                target=primary_model,
                justification=f"Inspecter les permissions de base pour {primary_model}",
                behavioral_focus=BehavioralTag.VISIBILITY_RULE,
                technical_focus=TechnicalTag.ACL,
            )
        )

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
