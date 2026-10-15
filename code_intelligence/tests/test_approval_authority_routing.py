from types import SimpleNamespace

import networkx as nx

from code_intelligence.agent.context_extractors import (
    _question_is_access_related,
    _question_is_approval_authority_related,
)
from code_intelligence.agent.forced_dispatch_predicates import who_has_access_targets
from code_intelligence.agent.investigation_planner import generate_investigation_plan
from code_intelligence.agent.investigation_schemas import PlanAction, QuestionIntent
from code_intelligence.agent.predispatch_access import dispatch_security_distinction_guard
from code_intelligence.agent.prompts import CI_SYSTEM_PROMPT, build_synthesis_prompt
from code_intelligence.agent.resolver import ResolvedConcept


def _resolved_order_concept(models=("purchase.order",)):
    return ResolvedConcept(
        user_term="purchase order",
        resolved_models=list(models),
        is_resolved=True,
    )


def test_approval_authority_detector_handles_french_and_english_wording():
    assert _question_is_approval_authority_related(
        "Qui est censé approuver les ventes et les achats ?"
    )
    assert _question_is_approval_authority_related("Who approves purchase orders?")
    assert _question_is_approval_authority_related("Qui valide cette commande ?")


def test_approval_authority_does_not_dispatch_generic_acl_matrix():
    graph = nx.DiGraph()
    concept = _resolved_order_concept()
    question = "Qui peut approuver les commandes ?"

    assert _question_is_access_related(question)
    assert who_has_access_targets(question, concept, graph) == []


def test_approval_plan_uses_workflow_and_button_evidence_not_acl():
    plan = generate_investigation_plan(
        "Qui est censé approuver les ventes et les achats ?",
        resolved_concept=_resolved_order_concept(("sale.order", "purchase.order")),
        intent=QuestionIntent.GOVERNANCE_SECURITY,
    )
    steps = {(step.action, step.target) for step in plan.steps}

    for model in ("sale.order", "purchase.order"):
        assert (PlanAction.DESCRIBE_WORKFLOW, model) in steps
        assert (PlanAction.BUTTON_EXECUTION_PATH, model) in steps
    assert not any(action == PlanAction.WHO_HAS_ACCESS_TO for action, _ in steps)


def test_approval_predispatch_collects_workflow_and_warns_against_acl_inference():
    class WorkflowTool:
        def __init__(self):
            self.calls = []

        def invoke(self, args):
            self.calls.append(args)
            return "No workflow transitions found."

    workflow_tool = WorkflowTool()
    ctx = SimpleNamespace(
        G=nx.DiGraph(),
        concept=_resolved_order_concept(),
        question="Qui est censé approuver les achats ?",
        hop_budget_exhausted=False,
        tool_map={"describe_workflow": workflow_tool, "button_execution_path": object()},
        matched_dispatchers=[],
        system_prompt_suffix="",
        tool_observations=[],
        seen_calls=set(),
        record_observation=lambda tool, args, text, model, key, elapsed: (
            ctx.tool_observations.append(text),
            ctx.seen_calls.add(key),
        ),
    )

    dispatch_security_distinction_guard(ctx)

    assert workflow_tool.calls == [{"model_name": "purchase.order"}]
    assert "dispatch_security_distinction_guard" in ctx.matched_dispatchers
    assert "do not infer approvers from write access" in ctx.system_prompt_suffix


def test_approval_answers_use_business_terms_and_hide_technical_identifiers():
    prompt = build_synthesis_prompt(
        "Qui est censé approuver les ventes et les achats ?",
        [
            "Role: [All Users] on the Confirm button.",
            "Approval button group: purchase.group_purchase_manager.",
            "The manager group is one path; one-step validation or two-step validation below the configured threshold also allows confirmation.",
        ],
    )

    assert "ERP consultant" in CI_SYSTEM_PROMPT
    assert "verify behavior against its source code or available internal documentation" in CI_SYSTEM_PROMPT
    assert "source identifiers in the evidence record, not in user-facing prose" in CI_SYSTEM_PROMPT
    assert "prefix it exactly as 'xml_id:" not in CI_SYSTEM_PROMPT
    assert "Do NOT translate exact technical identifiers" not in prompt
    assert "Do NOT include technical model names, XML-IDs, Python method names" in prompt
    assert "no group restriction was extracted from that button's interface declaration" in prompt
    assert "does NOT prove every user can perform the operation" in prompt
    assert "Never say an action is unrestricted or needs no approval solely" in prompt
    assert "do not present it as the sole path" in prompt
    assert "do not omit a bypass path" in prompt
