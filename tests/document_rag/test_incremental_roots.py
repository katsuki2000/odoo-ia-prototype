from document_rag.ingestion.incremental import _is_under_roots


def test_relative_source_is_resolved_against_the_requested_root(tmp_path):
    custom_root = tmp_path / "custom-documents"
    custom_root.mkdir()

    assert _is_under_roots("manual/guide.md", [custom_root])


def test_relative_source_is_not_associated_with_another_root(tmp_path):
    custom_root = tmp_path / "custom-documents"
    other_root = tmp_path / "other-documents"
    custom_root.mkdir()
    other_root.mkdir()

    assert not _is_under_roots("manual/guide.md", [other_root])


def test_remote_source_is_never_treated_as_a_local_file(tmp_path):
    assert not _is_under_roots("https://drive.google.com/file/d/example/view", [tmp_path])
