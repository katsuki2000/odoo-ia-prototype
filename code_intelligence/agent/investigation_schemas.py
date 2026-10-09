"""
code_intelligence/investigation_schemas.py

Serializable Investigation Plan schema, Question Intent classification,
and closed action vocabulary.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from code_intelligence.rules.ontology import BehavioralTag, TechnicalTag
from core.schemas import QueryRoute


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
    DESCRIBE_NAVIGATION_PATH = "describe_navigation_path"
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
    # Bloc 17 (todo/contexte.txt section 645, reconstruction du mandat manquant
    # todo/bloc17_jour1_perimetre.md) -- additive only, never reclassifies an
    # existing benchmark question (see TestBenchmarkRegressionPin in
    # code_intelligence/tests/test_bloc17_navigation_howto_intent.py).
    NAVIGATION_HOWTO = "navigation_howto"           # UI menu/screen/tab location ("ou se trouve X")


# Bloc P1 Tranche 2 (todo/contexte.txt section 394+): closed mapping from
# QuestionIntent to QueryRoute, replacing route()'s own keyword cascade as
# the single source of truth for the route decision.
INTENT_TO_ROUTE: Dict[QuestionIntent, str] = {
    QuestionIntent.GOVERNANCE_SECURITY: QueryRoute.CODE_INTELLIGENCE.value,
    QuestionIntent.WORKFLOW_STATE: QueryRoute.CODE_INTELLIGENCE.value,
    QuestionIntent.CALCULATION_LOGIC: QueryRoute.CODE_INTELLIGENCE.value,
    QuestionIntent.INHERITANCE_STRUCTURE: QueryRoute.CODE_INTELLIGENCE.value,
    QuestionIntent.AUTOMATION_ACTION: QueryRoute.CODE_INTELLIGENCE.value,
    QuestionIntent.GENERAL_CODE_INQUIRY: QueryRoute.CODE_INTELLIGENCE.value,
    QuestionIntent.ERP_DATA_QUERY: QueryRoute.DONNEES_ERP.value,
    QuestionIntent.DOCUMENTARY_POLICY: QueryRoute.DOCUMENTAIRE.value,
    QuestionIntent.NAVIGATION_HOWTO: QueryRoute.CODE_INTELLIGENCE.value,
}


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
