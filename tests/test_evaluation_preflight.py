import pytest

from core.evaluation.preflight import BackendUnavailable, require_backends


def _failing(message):
    def probe():
        raise ConnectionError(message)
    return probe


def test_returns_quietly_when_every_backend_answers():
    require_backends({"llm": lambda: None, "embeddings": lambda: None})


def test_names_every_unavailable_backend():
    probes = {"llm": lambda: None, "embeddings": _failing("read timed out")}

    with pytest.raises(BackendUnavailable) as raised:
        require_backends(probes)

    assert "embeddings: ConnectionError: read timed out" in str(raised.value)
    assert "llm" not in str(raised.value)


def test_reports_all_failures_in_one_error():
    probes = {"llm": _failing("refused"), "embeddings": _failing("timed out")}

    with pytest.raises(BackendUnavailable) as raised:
        require_backends(probes)

    assert "llm: ConnectionError: refused" in str(raised.value)
    assert "embeddings: ConnectionError: timed out" in str(raised.value)
