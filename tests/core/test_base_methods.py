"""Base ORM method names the verifier accepts, read from the Odoo source tree when it is present."""

import logging

from core.verification.base_methods import load_base_model_methods


def test_methods_come_from_the_model_classes_only(tmp_path):
    source = tmp_path / "models.py"
    source.write_text(
        "class BaseModel:\n"
        "    def write(self): ...\n"
        "    async def create(self): ...\n"
        "\n"
        "class Helper:\n"
        "    def unrelated(self): ...\n",
        encoding="utf-8",
    )
    assert load_base_model_methods(source) == frozenset({"write", "create"})


def test_missing_odoo_source_gives_no_methods_and_a_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert load_base_model_methods(tmp_path / "absent" / "models.py") == frozenset()
    assert "Base model methods unavailable" in caplog.text


def test_unparsable_odoo_source_gives_no_methods(tmp_path):
    source = tmp_path / "models.py"
    source.write_text("def broken(:\n", encoding="utf-8")
    assert load_base_model_methods(source) == frozenset()
