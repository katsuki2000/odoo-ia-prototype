from core.evaluation.synthesis_bench import ModelSpec, NO_THINK_MARKER, SynthesisPromptRecorder, generate_answer
from core.evaluation.synthesis_metrics import extract_identifiers, score_answer, strip_thinking


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


def test_model_spec_parse_splits_known_provider_only():
    assert ModelSpec.parse("ollama:gpt-oss:20b") == ModelSpec(model="gpt-oss:20b", provider="ollama")
    assert ModelSpec.parse("qwen3:14b") == ModelSpec(model="qwen3:14b")


def test_recorder_captures_and_restores_the_synthesis_prompt_builder():
    import code_intelligence.agent.loop as loop_module

    original = loop_module.build_synthesis_prompt
    recorder = SynthesisPromptRecorder()
    with recorder.attached():
        prompt = loop_module.build_synthesis_prompt("question?", ["observation"], ["who_has_access_to"])
    assert recorder.last_prompt == prompt
    assert loop_module.build_synthesis_prompt is original


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
