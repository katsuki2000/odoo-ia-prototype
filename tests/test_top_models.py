from types import SimpleNamespace

from code_intelligence.evaluation.e1 import pipeline_components, systems
from code_intelligence.evaluation.e1.projection import top_models

PARENT = {
    "field:a1": ("model:a",), "field:a2": ("model:a",), "field:b1": ("model:b",),
    "menu:ab": ("model:a", "model:b"), "group:g": (),
}


def project(ref):
    return PARENT.get(ref, (ref,) if ref.startswith("model:") else ())


def test_models_are_distinct_and_keep_their_best_rank():
    assert top_models(["field:b1", "field:a1", "field:a2", "model:b"], project, 5) == ["model:b", "model:a"]


def test_stops_once_the_limit_is_reached():
    seen = []

    def spy(ref):
        seen.append(ref)
        return project(ref)

    assert top_models(["field:a1", "field:b1", "model:c", "model:d"], spy, 2) == ["model:a", "model:b"]
    assert seen == ["field:a1", "field:b1"]


def test_a_reference_with_several_models_never_exceeds_the_limit():
    assert top_models(["menu:ab"], project, 1) == ["model:a"]


def test_references_without_model_are_skipped_and_empty_input_gives_nothing():
    assert top_models(["group:g", "field:a1"], project, 3) == ["model:a"]
    assert top_models([], project, 3) == []


def test_bm25_stage_reads_every_card_and_counts_models(monkeypatch):
    refs = ["field:a1", "field:a2", "field:b1", "model:c"]
    calls = []

    class FakeIndex:
        cards = tuple(range(100))

        def search(self, question, *, top_k):
            calls.append(top_k)
            return [SimpleNamespace(object_ref=ref) for ref in refs]

    monkeypatch.setattr(systems, "_bm25_index", lambda *args, **kwargs: FakeIndex())
    monkeypatch.setattr(pipeline_components, "ModelProjector", lambda graph: project)
    components = pipeline_components.build_components(
        None, config={"bm25_top_models": 2, "card_node_types": ["Model"]},
    )
    assert components.bm25("question", "fr_FR") == ["model:a", "model:b"]
    assert calls == [100]
