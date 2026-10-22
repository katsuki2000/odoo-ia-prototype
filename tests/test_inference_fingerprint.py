"""Empreinte du serveur d'inference (journal 1469) : hermetique, aucun reseau."""

from types import SimpleNamespace

from core.llm import server_fingerprint as fp


class _Models:
    def __init__(self, items):
        self._items = items

    def list(self):
        return SimpleNamespace(data=[SimpleNamespace(model_dump=(lambda d=d: d)) for d in self._items])


class _Client:
    def __init__(self, models=None, served="qwen3:8b", system_fingerprint="fp_a", fail=False):
        self.models = _Models(models or [{"id": "qwen3:8b", "created": 1, "owned_by": "x"}])
        self._served, self._sf, self._fail = served, system_fingerprint, fail
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        if self._fail:
            raise ConnectionError("down")
        return SimpleNamespace(model=self._served, system_fingerprint=self._sf)


def _get(client, base_url="http://aaa.example/v1", **kw):
    return fp.get_inference_fingerprint(base_url=base_url, model="qwen3:8b",
                                        embedding_model="bge-m3", client=client, **kw)


def test_id_is_stable_across_endpoint_and_time():
    a = _get(_Client(), base_url="http://aaa.example/v1")
    b = _get(_Client(), base_url="https://zzz.tunnel.example/v1")
    assert a["fingerprint_id"] == b["fingerprint_id"]
    assert a["llm"]["endpoint_hash"] != b["llm"]["endpoint_hash"]


def test_id_changes_with_served_model_metadata_or_system_fingerprint():
    base = _get(_Client())["fingerprint_id"]
    assert _get(_Client(served="qwen3:14b"))["fingerprint_id"] != base
    assert _get(_Client(system_fingerprint="fp_b"))["fingerprint_id"] != base
    assert _get(_Client(models=[{"id": "qwen3:8b", "created": 2, "owned_by": "x"}]))["fingerprint_id"] != base


def test_unreachable_server_never_raises_and_is_flagged():
    result = _get(_Client(fail=True))
    assert result["reachable"] is False and result["llm"]["error"] == "ConnectionError"
    assert result["fingerprint_id"]


def test_output_contains_no_url_or_secret():
    text = repr(_get(_Client(), base_url="http://user:secret@aaa.example:8000/v1", api_key="SECRETKEY"))
    assert "secret" not in text and "SECRETKEY" not in text and "aaa.example" not in text


def test_models_endpoint_missing_is_not_fatal():
    client = _Client()
    client.models = SimpleNamespace(list=lambda: (_ for _ in ()).throw(LookupError("404")))
    result = _get(client)
    assert result["reachable"] is True and result["llm"]["models_error"] == "LookupError"
    assert result["llm"]["canary"]["model"] == "qwen3:8b"


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload


def _ollama_http(version="0.40.6", digest="d1", ctx=32768, quant="Q4_K_M"):
    def get(url, **kwargs):
        if url.endswith("/api/version"):
            return _Resp({"version": version})
        if url.endswith("/api/tags"):
            return _Resp({"models": [{"name": "qwen3:8b", "digest": digest,
                                      "details": {"quantization_level": quant, "parameter_size": "8B"}}]})
        if url.endswith("/api/ps"):
            return _Resp({"models": [{"name": "qwen3:8b", "context_length": ctx, "runner": "llamacpp", "size": 5, "size_vram": 5}]})
        return _Resp({}, 404)
    return get


def _get_ollama(http_get, base_url="http://aaa.example/v1"):
    return fp.get_inference_fingerprint(base_url=base_url, model="qwen3:8b",
                                        embedding_model="bge-m3", client=_Client(), http_get=http_get)


def test_ollama_details_change_the_id_when_context_digest_or_version_change():
    base = _get_ollama(_ollama_http())
    assert base["ollama"]["loaded_context_length"] == 32768 and base["ollama"]["quantization_level"] == "Q4_K_M"
    for changed in (_ollama_http(ctx=8192), _ollama_http(digest="d2"), _ollama_http(version="0.41.0"), _ollama_http(quant="Q8_0")):
        assert _get_ollama(changed)["fingerprint_id"] != base["fingerprint_id"]
    assert _get_ollama(_ollama_http(), base_url="https://other.tunnel/v1")["fingerprint_id"] == base["fingerprint_id"]


def test_ollama_native_endpoints_failing_is_not_fatal():
    def broken(url, **kwargs):
        raise ConnectionError("down")
    result = _get_ollama(broken)
    assert result["reachable"] is True and result["ollama"] == {}
