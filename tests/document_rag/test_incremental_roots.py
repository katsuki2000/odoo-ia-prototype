from document_rag.ingestion.incremental import _is_under_roots


def test_relative_source_is_resolved_against_the_requested_root(tmp_path):
    custom_root = tmp_path / "custom-documents"
    custom_root.mkdir()

    assert _is_under_roots("manual/guide.md", [custom_root])


def test_absolute_source_outside_the_requested_root_is_rejected(tmp_path):
    custom_root = tmp_path / "custom-documents"
    other_root = tmp_path / "other-documents"
    custom_root.mkdir()
    other_root.mkdir()
    source = other_root / "manual" / "guide.md"

    assert not _is_under_roots(str(source), [custom_root])


def test_remote_source_is_never_treated_as_a_local_file(tmp_path):
    assert not _is_under_roots("https://drive.google.com/file/d/example/view", [tmp_path])
