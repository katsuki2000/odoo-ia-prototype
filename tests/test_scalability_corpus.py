"""Hermetic checks of the scalability benchmark corpus preparation (no Drive, no embedding)."""

import pytest

from scripts.run_scalability_test import CorpusUnavailable, prepare_duplicated_corpus


def test_empty_corpus_is_refused(tmp_path):
    source = tmp_path / "empty"
    (source / "nested").mkdir(parents=True)
    with pytest.raises(CorpusUnavailable):
        prepare_duplicated_corpus(source, tmp_path / "target", multiplier=3)


def test_corpus_is_duplicated_multiplier_times(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("alpha", encoding="utf-8")
    (source / "b.md").write_text("beta", encoding="utf-8")
    roots = prepare_duplicated_corpus(source, tmp_path / "target", multiplier=4)
    assert roots == [tmp_path / "target" / "docs"]
    copies = sorted(path.name for path in roots[0].iterdir())
    assert copies == ["copy_1", "copy_2", "copy_3", "copy_4"]
    assert all((roots[0] / name / "a.txt").read_text(encoding="utf-8") == "alpha" for name in copies)
