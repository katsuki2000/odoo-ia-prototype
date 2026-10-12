from pathlib import Path

from code_intelligence.graph.loader import _normalize_addon_roots
from config.odoo_conf import read_addons_path


def _conf(tmp_path: Path, addons_path: str) -> Path:
    conf = tmp_path / "odoo-17.0" / "odoo.conf"
    conf.parent.mkdir()
    conf.write_text(f"[options]\naddons_path = {addons_path}\n", encoding="utf-8")
    return conf


def test_relative_entry_is_read_from_the_directory_of_odoo_conf(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    conf = _conf(tmp_path, "/abs/custom,addons")
    assert read_addons_path(conf) == [Path("/abs/custom").resolve(), (conf.parent / "addons").resolve()]


def test_loader_normalizer_reads_relative_entries_from_the_base_directory(tmp_path):
    assert _normalize_addon_roots(["addons", "/abs/x"], tmp_path) == [
        (tmp_path / "addons").resolve(), Path("/abs/x").resolve(),
    ]


def test_without_a_base_directory_behaviour_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _normalize_addon_roots(["addons"]) == [(tmp_path / "addons").resolve()]
