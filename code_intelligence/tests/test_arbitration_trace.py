from types import SimpleNamespace

from code_intelligence.agent.resolution.arbitration import (
    ARBITRATION_CALL_FAILED,
    ARBITRATION_NO_LLM,
    ARBITRATION_NONE,
    ARBITRATION_OUT_OF_LIST,
    ArbitrationTrace,
    _llm_arbitrate,
)

CANDIDATES = ["sale.order", "purchase.order"]


def _answer_with(monkeypatch, content=None, error=None):
    def fake_invoke(llm, messages, rebuild_llm=None):
        if error is not None:
            raise error
        return SimpleNamespace(content=content), 0.0

    monkeypatch.setattr("core.llm.llm_client.invoke_with_rate_limit", fake_invoke)


def test_no_llm_gives_the_no_llm_status_and_no_raw_answer():
    trace = _llm_arbitrate("q", CANDIDATES, None)

    assert trace == ArbitrationTrace(None, ARBITRATION_NO_LLM, None)


def test_none_answer_is_an_explicit_abstention(monkeypatch):
    _answer_with(monkeypatch, "NONE")

    trace = _llm_arbitrate("q", CANDIDATES, object())

    assert trace == ArbitrationTrace(None, ARBITRATION_NONE, "NONE")


def test_an_answer_outside_the_list_keeps_its_exact_raw_value(monkeypatch):
    _answer_with(monkeypatch, "`purchase.order`")

    trace = _llm_arbitrate("q", CANDIDATES, object())

    assert trace == ArbitrationTrace(None, ARBITRATION_OUT_OF_LIST, "`purchase.order`")


def test_a_failed_call_is_told_apart_from_an_abstention(monkeypatch):
    _answer_with(monkeypatch, error=RuntimeError("tunnel down"))

    trace = _llm_arbitrate("q", CANDIDATES, object())

    assert trace == ArbitrationTrace(None, ARBITRATION_CALL_FAILED, None)
