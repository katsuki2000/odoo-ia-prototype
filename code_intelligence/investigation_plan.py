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
import logging
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from code_intelligence.business_resolver import ResolvedConcept
from code_intelligence.semantic_tags import BehavioralTag, TechnicalTag

logger = logging.getLogger(__name__)


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
    plan_route_conflict: bool = Field(
        default=False,
        description=(
            "True when validate_plan_against_route() neutralized this plan's "
            "steps because route_decision never executes InvestigationStep "
            "actions (todo/contexte.txt section 385/386)"
        ),
    )
    conflict_detail: Optional[str] = Field(
        default=None,
        description="Human-readable explanation of the plan/route conflict, if any",
    )

    def to_display_dict(self) -> Dict[str, Any]:
        """Format the plan for Discuss UI verification widget and API exposure."""
        return {
            "intent": self.intent.value,
            "target_models": self.target_models,
            "rationale": self.rationale,
            "source": self.source.value,
            "confidence": self.confidence,
            "plan_route_conflict": self.plan_route_conflict,
            "conflict_detail": self.conflict_detail,
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
    # Section 214: non-inverted French construction ("un utilisateur peut voir",
    # subject before the verb) -- the pattern above only covers the inverted
    # interrogative form ("peut-il voir"). Both ask the same access/permission
    # question; only the word order differs.
    r"\b(peut|peuvent)\s+(voir|acceder|accéder|modifier|supprimer|creer|créer|valider|approuver)\b",
    r"\b(a|ont)[-\s]t[-\s](il|elle|ils|elles)\s+le\s+droit\b",
    r"\b(verrou|verrouill[eé]|bloqu[eé]|interdit|restreint)\b",
    r"\b(regle|règle|ir\.rule|ir_rule|securite|sécurité|acl|permission)\b",
    r"\b(approbation|approuver|valider|validation|signer|signature)\b",
    r"\b(plafond|seuil|limite\s+montant|depasse|dépasse)\b",
    r"\b(masqu[eé]|cach[eé]|invisible|visibilit[eé])\b",
    # Section 208-bis: troubleshooting questions ("je n'arrive pas à démarrer/valider")
    # express an access/governance problem even without explicit governance keywords.
    r"(?:n.arrive|ne\s+(?:peut|peux|parvien[st])\s+pas|impossible|empeche|empêche)\s.*?(?:demarrer|démarrer|valider|approuver|confirmer|creer|créer|modifier|supprimer|lancer)",
    # Section 208-bis: explicit condition inspection ("conditions vérifiées par action_X")
    r"\bconditions?\s+(?:verifiees?|vérifiées?|requises?|necessaires?|nécessaires?)\b",
    # Section 208-bis: direct method name reference (action_demarrer, action_valider, etc.)
    r"\baction_[a-z_]+\b",
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

# Section 379 (todo/contexte.txt): weak process-inquiry signals for Step 8's
# "Concept + Graph Tag affinity" fallback. A resolved_concept alone (even at
# confidence=1.0) is NOT proof of intent -- section 378 documented "avoir" as
# a static alias matching the common French verb, which let Step 8 return
# WORKFLOW_STATE for "pour avoir du code de qualité" purely because
# account.move carries the WORKFLOW_RULE tag, with zero textual signal in the
# question itself. Step 8 is only ever reached once _GOVERNANCE_PATTERNS,
# _WORKFLOW_PATTERNS, _CALCULATION_PATTERNS, _INHERITANCE_PATTERNS,
# _AUTOMATION_PATTERNS, _ERP_DATA_PATTERNS and _DOC_ANCHOR_PATTERNS have ALL
# already failed to match -- so requiring one of those same strict patterns
# again would be vacuous. This list is intentionally looser: generic
# process-inquiry wording ("comment ça marche", "quelle est la procédure")
# that a legitimate workflow-adjacent question (e.g. "et pour les congés, ça
# se passe comment ?") would carry even without naming "workflow"/"étape"
# explicitly, while a sentence that merely happens to contain a homonymic
# alias ("avoir", "pour avoir...") without any process wording will not.
_WEAK_PROCESS_SIGNALS = [
    r"\b(comment|process|processus|procedure|procédure|demarche|démarche|deroulement|déroulement|fonctionne|fonctionnement|se\s+passe|ca\s+marche|ça\s+marche)\b",
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
    # Section 379 (todo/contexte.txt): a resolved_concept's tag is a
    # model-side signal, never a substitute for question-side intent -- see
    # section 378 ("avoir" -> account.move -> WORKFLOW_RULE misfiring on
    # "pour avoir du code de qualité", zero textual signal present). This
    # fallback now additionally requires a weak process-inquiry signal in the
    # question text (_WEAK_PROCESS_SIGNALS) before trusting the tag affinity;
    # without it, execution falls through to step 9 (neutral
    # DOCUMENTARY_POLICY) instead of manufacturing an intent from the model
    # side alone.
    if resolved_concept and resolved_concept.is_resolved and G is not None:
        has_weak_process_signal = any(re.search(p, folded) for p in _WEAK_PROCESS_SIGNALS)
        if has_weak_process_signal:
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
        # Section 289 (todo/contexte.txt): a missing resolved model does NOT by
        # itself justify a Code Intelligence investigation plan -- a pure
        # greeting ("Bonjour"), an off-topic question, or any documentary/ERP
        # query with no resolvable model must not receive a fabricated
        # WHO_HAS_ACCESS_TO<unknown_model> plan (previous behavior: this
        # branch fired unconditionally for ANY question with no model, which
        # is exactly the case for "Bonjour"). Mirrors the SAME
        # DOCUMENTARY_POLICY/ERP_DATA_QUERY exclusion already used by
        # concept_suggests_code_intelligence_v2() for the resolved-concept
        # case, instead of introducing a second, independently-drifting
        # boundary.
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
        # Fallback plan when no specific model is resolved, but the intent
        # itself still reads as a Code Intelligence domain (e.g. a governance
        # question whose business_resolver lookup failed to match a model).
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
        # Bloc P1 Jour 6 (todo/contexte.txt section 209): these gates now reuse
        # the EXACT SAME predicate functions as the real deterministic
        # pre-dispatch in code_intelligence/ci_agent_node.py, instead of a
        # second, independently-drifting set of regexes/keyword lists. This
        # closes the plan/execution divergence found before Jour 6 (e.g. a
        # question using "modifier"/"supprimer" was classified GOVERNANCE_SECURITY
        # by intent but never triggered who_has_access_to in real dispatch,
        # which only recognizes "voir/accéder/consulter/lire/visualiser").
        # Scope of this alignment, per explicit decision: only the 4 categories
        # already identified as common and stable across both sides (accès,
        # approbation/gouvernance, automatisation/contournement, verrous
        # structurels) -- the QuestionIntent classification itself (which
        # bucket a question falls into) stays a Planner-only heuristic, since
        # it has no operational equivalent on the execution side.
        from code_intelligence.ci_helpers import (
            _question_is_access_related,
            _question_is_approval_related,
            _question_suggests_automation_bypass,
            _extract_amount,
        )

        is_access_related = _question_is_access_related(question)
        is_approval_related = _question_is_approval_related(question)
        is_automation_bypass = _question_suggests_automation_bypass(question)
        amount = _extract_amount(question)

        # Structural graph checks -- mirror the same structural guards used by
        # ci_agent_node.py's forced pre-dispatch (find_security_lock_source_files/
        # find_server_action_nodes/find_methods_with_override_cascade) so the
        # plan never promises a step the real dispatch structurally cannot
        # fire. Bloc P1 Jour 6 (todo/contexte.txt section 210): call the same
        # forced_dispatch_predicates wrapper functions the real pre-dispatch
        # uses, instead of a second, independently-maintained per-model loop
        # around the same underlying ci_agent_tools finders. Conservative
        # defaults below apply whenever G is unavailable (e.g. unit tests
        # exercising generate_investigation_plan without a real graph) --
        # never crash plan generation on a missing graph.
        has_security_lock_source = True  # conservative: assume present without a graph to check against
        has_server_action_nodes = False
        has_override_cascade = False
        has_who_has_access_target = is_access_related  # conservative: assume present without a graph to check against
        if G is not None:
            try:
                from code_intelligence.forced_dispatch_predicates import (
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
                # Never let a graph-lookup failure break plan generation --
                # degrade to the conservative defaults set above.
                pass

        # 1. ACL permissions -- gated on the SAME shared predicate
        # (who_has_access_targets) as who_has_access_to's real forced
        # pre-dispatch, which additionally excludes any model already more
        # specifically governed by a real Python security lock (section 226
        # fix: this step previously used the raw is_access_related detector
        # alone, promising who_has_access_to even for lock-governed models
        # that real dispatch always skips in favor of analyze_security_locks).
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

        # 2. Record rules -- real dispatch additionally requires an
        # extractable monetary amount before firing evaluate_record_rules.
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

        # 3. Python security locks -- real dispatch fires this independently
        # of question wording, gated only by the structural presence of
        # lock-relevant source files on the model.
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

        # 4. can_view_amount_v2 -- tightly coupled to evaluate_record_rules in
        # real dispatch (same access-related + amount gate); replaces the
        # previous ad hoc keyword list ("montant", "€", "000"...) with the
        # same shared amount extractor used everywhere else in the pipeline.
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

        # 5. Method override chain -- real dispatch fires this when the
        # question reads as approval-related AND a real override cascade
        # exists on the model (new step for this branch: previously only
        # reachable via the CALCULATION_LOGIC/INHERITANCE_STRUCTURE intents,
        # even though real dispatch triggers it independently of intent).
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

        # 6. Server actions -- real dispatch fires this when the question
        # suggests an automation/bypass AND ServerAction nodes exist on the
        # model (new step for this branch, same rationale as #5 above).
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
            # Never ship an empty plan for a governance-classified question --
            # same "always at least one step" contract as the no-model
            # fallback above. Can legitimately happen when a governance-worded
            # question resolves to a model with no lock source, no override
            # cascade, no server actions, and no access/amount signal
            # recognized by the shared detectors (e.g. a question whose
            # vocabulary -- "règles", "visibilité", "sécurité"... -- reads as
            # governance-flavored to the intent classifier but never trips any
            # of the 6 stricter shared gates). Section 230 (todo/contexte.txt):
            # this fallback previously defaulted to WHO_HAS_ACCESS_TO
            # unconditionally, which could promise a step the real forced
            # dispatch would never fire whenever who_has_access_targets()
            # itself excludes the model -- a coherence violation of the exact
            # same class already fixed for step 1 in section 226.
            # READ_SOURCE_CODE is used here instead because it carries no
            # shared-gate coherence contract on the execution side (it is not
            # one of the 6 actions in _CHECKED_ACTIONS, see
            # test_bloc_p1_j6_plan_execution_coherence.py) -- an honest "no
            # specific shared signal fired, fall back to manual source
            # inspection" step, rather than a false promise that a specific
            # composite tool would fire.
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

    elif intent in (QuestionIntent.DOCUMENTARY_POLICY, QuestionIntent.ERP_DATA_QUERY):
        # Section 327-329 (todo/contexte.txt): DOC-08 guard, symmetric case.
        # The `if not primary_model:` branch above already refuses to fabricate
        # a Code Intelligence plan for a documentary/ERP-data question with no
        # resolved model. This mirrors the same guard for the opposite case --
        # a model IS resolved (e.g. "mise à disposition" -> custom.asset.loan)
        # but the question's classified intent is still DOCUMENTARY_POLICY or
        # ERP_DATA_QUERY (e.g. "qui en a le droit ?", missed by the governance
        # regex due to the intercalated "en"). A resolved concept alone must not
        # imply a governance/code investigation plan, regardless of which side
        # (model vs. intent) is missing. Previously fell through to the `else`
        # fallback below and emitted an unconditional WHO_HAS_ACCESS_TO plan
        # even though the real route taken is `documentaire`, not Code Intelligence.
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


# ── Plan/Route Coherence Validation (todo/contexte.txt section 385/386) ──────
#
# route() (core/routing.py) and classify_question_intent() (this module) are
# two INDEPENDENTLY-maintained classifiers -- one keyword-based (route()'s
# own if/elif chain), one concept+intent-based (classify_question_intent(),
# called from generate_investigation_plan() above). They can and do diverge:
# section 385 traced a real case ("comment créer une demande de facture ?")
# where the word "comment" sent route_decision to DOCUMENTAIRE (DOC_KEYWORDS)
# while the SAME word sent classify_question_intent() to WORKFLOW_STATE via
# _WEAK_PROCESS_SIGNALS + account.move's WORKFLOW_RULE tag -- producing a
# full Code Intelligence investigation plan attached to a documentary answer
# that never executes a single InvestigationStep.
#
# Only the "code_intelligence" branch of core/graph.py's StateGraph (the
# code_intelligence_agent node) ever executes InvestigationStep actions.
# documentaire (generate), donnees_erp (orm_agent_loop) and hybride
# (hybrid_node) never do -- hybrid_node only orchestrates the documentary and
# ERP branches (erp_data/orm_agent_node.py), never code_intelligence_agent.
# A plan promising steps on those branches is not cosmetic: it actively
# misinforms anyone inspecting the a priori plan, which is the entire point
# of Bloc P1.
#
# Explicit decision (section 386): detect and flag the conflict rather than
# silently overwriting plan.steps. A silent overwrite would hide how often
# the two classifiers actually disagree; an explicit plan_route_conflict/
# conflict_detail field keeps the divergence observable and measurable,
# ahead of any future decision to merge the two classifiers.

_ROUTES_WITHOUT_CI_EXECUTION = {"documentaire", "donnees_erp", "hybride"}


def validate_plan_against_route(plan: InvestigationPlan, route_decision: str) -> InvestigationPlan:
    """
    Reconciles the Planner's independently-classified InvestigationPlan
    against the route actually dispatched by route_decision() (core/routing.py).

    - "code_intelligence": plan is authorized as-is -- this IS the branch
      that executes InvestigationStep actions.
    - "documentaire" / "donnees_erp" / "hybride": none of these branches ever
      execute an InvestigationStep. A non-empty plan here is a genuine
      plan/route conflict (see module docstring above), not a valid a priori
      plan -- neutralized to steps=[] with plan_route_conflict=True, while
      `intent`/`rationale` are preserved unchanged so the divergence stays
      visible for measurement rather than silently disappearing.
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
