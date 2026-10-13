import numpy as np
import pytest

from code_intelligence.agent.semantic_index_store import SemanticIndexStore, text_key


def test_saved_vectors_are_loaded_back(tmp_path):
    store = SemanticIndexStore(str(tmp_path), "model-a")
    store.save({text_key("alpha"): [0.5, 0.25], text_key("beta"): [1.0, 0.0]})

    loaded = SemanticIndexStore(str(tmp_path), "model-a").load()

    assert loaded[text_key("alpha")] == pytest.approx([0.5, 0.25])
    assert loaded[text_key("beta")] == pytest.approx([1.0, 0.0])


def test_missing_cache_loads_as_empty(tmp_path):
    assert SemanticIndexStore(str(tmp_path / "absent"), "model-a").load() == {}


def test_embedding_models_never_share_a_file(tmp_path):
    SemanticIndexStore(str(tmp_path), "model-a").save({text_key("alpha"): [1.0]})

    assert SemanticIndexStore(str(tmp_path), "model-b").load() == {}


def test_corrupt_cache_is_ignored(tmp_path):
    store = SemanticIndexStore(str(tmp_path), "model-a")
    store.save({text_key("alpha"): [1.0]})
    next(tmp_path.glob("*.npz")).write_bytes(b"not an archive")

    assert store.load() == {}


def test_unwritable_directory_does_not_raise(tmp_path):
    blocker = tmp_path / "occupied"
    blocker.write_text("file, not a directory")

    SemanticIndexStore(str(blocker), "model-a").save({text_key("alpha"): [1.0]})

    assert list(tmp_path.iterdir()) == [blocker]


def test_inconsistent_vector_sizes_do_not_raise(tmp_path):
    SemanticIndexStore(str(tmp_path), "model-a").save({"a": [1.0, 0.0], "b": [1.0]})

    assert list(tmp_path.glob("*")) == []


def test_arrays_round_trip_as_float32_and_stay_readable_as_a_dict(tmp_path):
    store = SemanticIndexStore(str(tmp_path), "model-a")
    store.save_arrays(["a", "b"], np.array([[0.5, 0.25], [1.0, 0.0]]))

    keys, matrix = SemanticIndexStore(str(tmp_path), "model-a").load_arrays()

    assert keys == ["a", "b"]
    assert matrix.dtype == np.float32
    assert matrix.tolist() == [[0.5, 0.25], [1.0, 0.0]]
    assert store.load()["b"] == pytest.approx([1.0, 0.0])


def test_dict_save_is_readable_as_arrays(tmp_path):
    store = SemanticIndexStore(str(tmp_path), "model-a")
    store.save({"a": [0.5, 0.25], "b": [1.0, 0.0]})

    keys, matrix = store.load_arrays()

    assert keys == ["a", "b"]
    assert matrix.shape == (2, 2)


def test_missing_or_corrupt_cache_loads_as_empty_arrays(tmp_path):
    keys, matrix = SemanticIndexStore(str(tmp_path / "absent"), "model-a").load_arrays()
    assert (keys, matrix.shape) == ([], (0, 0))

    store = SemanticIndexStore(str(tmp_path), "model-a")
    store.save_arrays(["a"], np.ones((1, 2)))
    next(tmp_path.glob("*.npz")).write_bytes(b"not an archive")

    keys, matrix = store.load_arrays()
    assert (keys, matrix.shape) == ([], (0, 0))


def test_arrays_with_a_mismatched_row_count_are_not_written(tmp_path):
    SemanticIndexStore(str(tmp_path), "model-a").save_arrays(["a"], np.zeros((2, 3)))

    assert list(tmp_path.glob("*")) == []
