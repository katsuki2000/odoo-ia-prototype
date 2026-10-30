"""Portable source identifiers and scan-root selection."""

from document_rag.ingestion.scan_root import compute_source, resolve_scan_root


def test_compute_source_is_relative_to_the_configured_root(tmp_path):
    root = tmp_path / "documents"
    file_path = root / "procedures" / "guide.md"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    assert compute_source(file_path, root) == "procedures/guide.md"


def test_compute_source_never_exposes_an_absolute_path(tmp_path):
    file_path = tmp_path / "private" / "guide.md"
    file_path.parent.mkdir()
    file_path.touch()

    assert compute_source(file_path) == "guide.md"


def test_resolve_scan_root_prefers_the_most_specific_root(tmp_path):
    root = tmp_path / "documents"
    nested = root / "odoo_addons"
    file_path = nested / "module" / "guide.md"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    assert resolve_scan_root(file_path, [root, nested]) == nested
