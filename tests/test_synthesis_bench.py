from core.evaluation.synthesis_bench import (
    FrozenCase,
    ModelSpec,
    NO_THINK_MARKER,
    SynthesisPromptRecorder,
    generate_answer,
    replay,
    summarize,
)
from core.evaluation.synthesis_metrics import extract_identifiers, find_unsupported_claims, score_answer, strip_thinking


def test_strip_thinking_flags_closed_and_unclosed_blocks():
    assert strip_thinking("<think>plan</think>Answer") == ("Answer", True)
    assert strip_thinking("<think>never closed") == ("", True)
    assert strip_thinking("Plain answer") == ("Plain answer", False)


def test_extract_identifiers_keeps_dotted_and_snake_case_only():
    found = extract_identifiers("base.group_user reads equipment_rule_user, e.g. maintenance.equipment")
    assert found == {"base.group_user", "equipment_rule_user", "maintenance.equipment"}


def test_score_answer_separates_recall_from_unsupported_identifiers():
    prompt = "rule equipment_rule_user applies to maintenance.equipment"
    reference = "equipment_rule_user restricts access; also perm_unlink"
    score = score_answer("Only equipment_rule_user and invented_rule_admin", prompt, reference)
    assert score.reachable_reference_ids == 1
    assert score.identifier_recall == 1.0
    assert score.unsupported_identifiers == ["invented_rule_admin"]


def test_score_answer_recall_is_none_without_reachable_reference_identifiers():
    score = score_answer("anything", "no identifiers here", "perm_unlink only")
    assert score.identifier_recall is None


def test_model_spec_keeps_the_ollama_tag_whole():
    assert ModelSpec.parse("gpt-oss:20b") == ModelSpec(model="gpt-oss:20b")


def test_generate_answer_appends_no_think_only_for_qwen3(monkeypatch):
    sent = []

    class FakeResponse:
        content = "ok"

    def fake_invoke(llm, messages, rebuild_llm=None):
        sent.append(messages[0].content)
        return FakeResponse(), 0.0

    monkeypatch.setattr("core.evaluation.synthesis_bench.invoke_with_rate_limit", fake_invoke)
    monkeypatch.setattr("core.evaluation.synthesis_bench.get_chat_llm", lambda **kwargs: object())

    generate_answer(ModelSpec.parse("qwen3:14b"), "prompt", 0.0, None, allow_thinking=False)
    generate_answer(ModelSpec.parse("gpt-oss:20b"), "prompt", 0.0, None, allow_thinking=False)
    generate_answer(ModelSpec.parse("qwen3:14b"), "prompt", 0.0, None, allow_thinking=True)

    assert sent[0].endswith(NO_THINK_MARKER)
    assert sent[1] == "prompt"
    assert sent[2] == "prompt"


def test_replay_records_failures_without_scoring_them(monkeypatch):
    import core.evaluation.synthesis_bench as bench

    calls = iter([RuntimeError("gateway\nerror"), "uses equipment_rule_user"])

    def fake_generate(*args, **kwargs):
        outcome = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(bench, "generate_answer", fake_generate)
    case = FrozenCase("Q", "question", "rule equipment_rule_user", "equipment_rule_user")
    results = replay([case], [ModelSpec("m")], 2, 0.0, None, False)

    assert results[0].error == "gateway error" and results[0].score is None
    assert results[1].error is None and results[1].score.identifier_recall == 1.0
    stats = summarize(results)["m"]
    assert (stats["samples"], stats["valid_samples"], stats["errors"]) == (2, 1, 1)
    assert stats["mean_identifier_recall"] == 1.0


def test_summarize_handles_a_model_with_only_failures():
    from core.evaluation.synthesis_bench import SampleResult

    stats = summarize([SampleResult("Q", "m", 1, 1.0, "", error="down")])["m"]
    assert stats["valid_samples"] == 0 and stats["mean_identifier_recall"] == 0.0


SQL_EVIDENCE = "(code_intelligence.semgrep_rules.odoo-sql-constraints-declaration) _sql_constraints = [('x', 'CHECK(y)', 'm')]"


def test_sql_claim_without_supporting_evidence_is_flagged():
    answer = "Each line has an independent contrainte SQL forbidding a null quantity."
    assert find_unsupported_claims(answer, "@api.constrains only") == ["sql_constraint"]


def test_sql_claim_backed_by_evidence_is_accepted():
    assert find_unsupported_claims("La contrainte SQL impose une valeur.", SQL_EVIDENCE) == []


def test_negated_sql_statement_is_not_a_claim():
    answer = "Aucune contrainte SQL n'apparait dans les observations."
    assert find_unsupported_claims(answer, "@api.constrains only") == []


def test_answer_without_sql_topic_is_never_flagged():
    assert find_unsupported_claims("Only a Python guard applies.", "no evidence") == []
