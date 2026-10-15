"""confine_to_scan_roots rejects paths outside configured corpus roots."""


import pytest

from document_rag.ingestion.scan_root import confine_to_scan_roots


def test_path_under_root_is_accepted(tmp_path):
    root = tmp_path / "docs"
    nested = root / "a" / "b.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("x", encoding="utf-8")

    resolved = confine_to_scan_roots(nested, candidate_roots=[root])
    assert resolved == nested.resolve()


def test_root_itself_is_accepted(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    assert confine_to_scan_roots(root, candidate_roots=[root]) == root.resolve()


def test_path_outside_roots_is_rejected(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    outside = tmp_path / "other" / "file.txt"
    outside.parent.mkdir()
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError, match="outside configured ingestion roots"):
        confine_to_scan_roots(outside, candidate_roots=[root])


def test_symlink_escape_is_rejected(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("leak", encoding="utf-8")
    link = root / "escape"
    link.symlink_to(secret)

    with pytest.raises(ValueError, match="outside configured ingestion roots"):
        confine_to_scan_roots(link, candidate_roots=[root])
