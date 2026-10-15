"""Section 1196: deterministic pre-dispatch of describe_navigation_path
for the `navigation_howto` intent, and prompt/intent invariant."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from code_intelligence.agent import predispatch_structure as ps
from code_intelligence.agent.investigation_llm import _INTENT_CLASSIFICATION_SYSTEM_PROMPT
from code_intelligence.agent.investigation_schemas import QuestionIntent


def _ctx(intent, models=("account.move",), resolved=True):
    ctx = MagicMock()
    ctx.intent = intent
    ctx.concept = SimpleNamespace(is_resolved=resolved, resolved_models=list(models))
    ctx.hop_budget_exhausted = False
    ctx.seen_calls = set()
    ctx.matched_dispatchers = []
    ctx.resolved_user_group_xmlids = []
    return ctx


def _fake_result():
    return SimpleNamespace(evidence=[], summary_text="Pour 'account.move': menu A -> B", execution_steps=["s1"])


def test_every_intent_is_offered_in_the_classifier_prompt():
    for intent in QuestionIntent:
        assert intent.value in _INTENT_CLASSIFICATION_SYSTEM_PROMPT, intent.value


def test_dispatch_fires_on_navigation_howto():
    ctx = _ctx("navigation_howto")
    with patch("code_intelligence.rules.navigation.describe_navigation_path", return_value=_fake_result()), \
         patch.object(ps, "record_evidence"), \
         patch.object(ps, "_resolve_model_param", side_effect=lambda m: m):
        ps.dispatch_navigation_path(ctx)
    assert ctx.matched_dispatchers == ["dispatch_navigation_path"]
    ctx.record_observation.assert_called_once()
    assert ctx.record_observation.call_args[0][0] == "describe_navigation_path"


def test_navigation_availability_keeps_unknown_requester_groups_unknown():
    ctx = _ctx("navigation_howto")
    ctx.resolved_user_group_xmlids = None
    with patch("code_intelligence.rules.navigation.describe_navigation_path", return_value=_fake_result()) as describe, \
         patch.object(ps, "record_evidence"), \
         patch.object(ps, "_resolve_model_param", side_effect=lambda m: m):
        ps.dispatch_navigation_path(ctx)
    assert describe.call_args.kwargs["user_groups"] is None


def test_dispatch_skipped_for_other_intents():
    ctx = _ctx("documentary_policy")
    ps.dispatch_navigation_path(ctx)
    assert ctx.matched_dispatchers == []
    ctx.record_observation.assert_not_called()


def test_dispatch_skipped_when_concept_unresolved():
    ctx = _ctx("navigation_howto", resolved=False)
    ps.dispatch_navigation_path(ctx)
    ctx.record_observation.assert_not_called()


# --- Section 1198: requester ACL verdict for navigation_howto -------------

def _acl_patches(summary="[AUTHENTICATED REQUESTER ACL VERDICT]\nCREATE: GRANTED (through g).", verdicts={"create": True}):
    from code_intelligence.agent import predispatch_access as pa
    return (
        patch("code_intelligence.rules.access_evaluator.requester_acl_summary",
              return_value=(summary, [], verdicts)),
        patch("core.evidence.evidence_collector.record_evidence"),
        pa,
    )


def test_requester_acl_recorded_as_observation_without_verdict_override():
    ctx = _ctx("navigation_howto")
    ctx.question = "Est-ce que je peux créer une facture ?"
    ctx.requester_groups_known = True
    ctx.system_prompt_suffix = ""
    ctx.requester_acl_verdicts = {}
    p1, p2, pa = _acl_patches()
    with p1 as summ, p2:
        pa.dispatch_navigation_requester_acl(ctx)
    summ.assert_called_once()
    assert ctx.record_observation.call_args[0][0] == "requester_acl_summary"
    assert ctx.matched_dispatchers == ["dispatch_navigation_requester_acl"]
    assert ctx.requester_acl_verdicts == {}  # never replaces the whole answer
    assert "AUTHENTICATED REQUESTER ACL" in ctx.system_prompt_suffix
    assert "CREATE: GRANTED" in ctx.system_prompt_suffix
    assert "FIRST sentence" in ctx.system_prompt_suffix
    assert "generic condition" in ctx.system_prompt_suffix


def test_requester_acl_passes_unknown_groups_through():
    ctx = _ctx("navigation_howto")
    ctx.question = "Est-ce que je peux créer une facture ?"
    ctx.requester_groups_known = False
    ctx.resolved_user_group_xmlids = None
    ctx.system_prompt_suffix = ""
    p1, p2, pa = _acl_patches("[REQUESTER ACL STATUS] groups could not be fully resolved", verdicts=None)
    with p1 as summ, p2:
        pa.dispatch_navigation_requester_acl(ctx)
    assert summ.call_args[0][2] is None and summ.call_args[0][3] is False
    assert "CREATE: UNKNOWN" in ctx.system_prompt_suffix
    assert "explicitly say that it cannot be determined" in ctx.system_prompt_suffix


def test_requester_acl_skipped_for_other_intents_and_unresolved_concept():
    from code_intelligence.agent import predispatch_access as pa
    for ctx in (_ctx("governance_security"), _ctx("navigation_howto", resolved=False)):
        pa.dispatch_navigation_requester_acl(ctx)
        ctx.record_observation.assert_not_called()
        assert ctx.matched_dispatchers == []
