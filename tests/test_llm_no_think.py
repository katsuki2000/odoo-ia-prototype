import pytest

from core.llm import llm_client
from code_intelligence.agent.investigation_llm import build_intent_classification_messages
from code_intelligence.agent.resolution import arbitration


@pytest.mark.parametrize("marker, expected", [("/no_think", "prompt /no_think"), ("", "prompt")])
def test_with_no_think_appends_the_marker_only_when_configured(monkeypatch, marker, expected):
    monkeypatch.setattr(llm_client, "LLM_NO_THINK_MARKER", marker)

    assert llm_client.with_no_think("prompt") == expected


def test_intent_classification_system_prompt_carries_the_marker(monkeypatch):
    monkeypatch.setattr(llm_client, "LLM_NO_THINK_MARKER", "/no_think")

    assert build_intent_classification_messages("question")[0].content.endswith("/no_think")


def test_arbitration_system_prompt_carries_the_marker(monkeypatch):
    monkeypatch.setattr(llm_client, "LLM_NO_THINK_MARKER", "/no_think")
    seen = {}

    class Llm:
        def invoke(self, messages):
            seen["system"] = messages[0].content
            return type("Response", (), {"content": "[]"})()

    arbitration._llm_arbitrate("question", ["sale.order"], Llm())

    assert seen["system"].endswith("/no_think")
