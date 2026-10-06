import logging

import pytest

from core.verification import checkers
from core.verification.base_methods import load_base_model_methods
from core.verification.claims import ClaimType
from core.verification.context import VerificationContext, flatten_numeric_values
from core.verification.extractors import extract_claims
from tests.t2_graph_factory import build_graph


def _verdict(text, context, claim_type):
    claim = next(claim for claim in extract_claims(text) if claim.claim_type is claim_type)
    return checkers.CHECKERS[claim_type](claim, context)


def _context(**kwargs):
    kwargs.setdefault("graph", build_graph())
    return VerificationContext(**kwargs)


@pytest.mark.parametrize("text, evidence, expected", [
    ("Total : 12 500", {"numeric_values": (12500.4,)}, None),
    ("Total : 12 500,5", {"numeric_values": (12500.47,)}, None),
    ("Total : 13 000", {"numeric_values": (12500.0,)}, checkers.REASON_NO_MATCHING_VALUE),
    ("Total : 30", {"numeric_values": (10.0, 20.0)}, checkers.REASON_NO_MATCHING_VALUE),
    ("Montant : 15 000", {"texts": ("Qui peut approuver 15 000 € ?",)}, None),
    ("Seuil : 10 000", {"texts": ("if amount > 10000:",)}, None),
    ("Valeur : 1,234", {"texts": ("rate = 1.234",)}, None),
    ("Valeur : 1,234", {"texts": ("rate = 1.5",)}, checkers.REASON_NO_MATCHING_VALUE),
])
def test_number_check(text, evidence, expected):
    assert _verdict(text, _context(**evidence), ClaimType.NUMBER) == expected


def test_flatten_numeric_values_skips_booleans_and_walks_containers():
    assert sorted(flatten_numeric_values({"a": [1, 2.5, True], "b": ({"c": 3},), "d": "x"})) == [1.0, 2.5, 3.0]


@pytest.mark.parametrize("graph, evidence, expected", [
    ("graph", ("(groupes: account.group_account_manager)",), None),
    ("graph", (), checkers.REASON_NOT_IN_EVIDENCE),
    ("none", (), checkers.REASON_NOT_IN_EVIDENCE),
])
def test_group_check_for_a_group_in_the_graph(graph, evidence, expected):
    context = _context(texts=evidence, graph=build_graph() if graph == "graph" else None)
    assert _verdict("Groupe account.group_account_manager.", context, ClaimType.GROUP) == expected


def test_unknown_group_is_reported_as_fabricated():
    verdict = _verdict("Groupe purchase.group_purchase_director.", _context(), ClaimType.GROUP)
    assert verdict == checkers.REASON_UNKNOWN_GROUP


def test_group_grounded_in_evidence_is_kept_even_when_the_graph_lacks_it():
    context = _context(texts=("has_group('stock.group_stock_manager')",))
    assert _verdict("Groupe stock.group_stock_manager.", context, ClaimType.GROUP) is None


@pytest.mark.parametrize("text, evidence, expected", [
    ("`super()`", {}, None),
    ("`write()`", {"base_methods": frozenset({"write"})}, None),
    ("`has_group()`", {}, None),
    ("`account.move.action_post()`", {}, None),
    ("`account.move.message_post()`", {}, None),
    ("`account.move.has_group()`", {}, checkers.REASON_NOT_ON_MODEL),
    ("`account.move.has_group()`", {"texts": ("account.move.has_group is called",)}, None),
    ("`action_invented()`", {}, checkers.REASON_UNKNOWN_METHOD),
    ("`action_invented()`", {"texts": ("def action_invented(self):",)}, None),
])
def test_method_check(text, evidence, expected):
    assert _verdict(text, _context(**evidence), ClaimType.METHOD) == expected


def test_method_check_without_a_graph_relies_on_evidence_only():
    assert _verdict("`action_post()`", _context(graph=None), ClaimType.METHOD) == checkers.REASON_UNKNOWN_METHOD
    context = _context(graph=None, texts=("action_post",))
    assert _verdict("`action_post()`", context, ClaimType.METHOD) is None


def test_base_model_methods_come_from_the_models_source(tmp_path):
    source = tmp_path / "models.py"
    source.write_text(
        "class BaseModel:\n    def create(self): ...\n    def write(self): ...\n"
        "class Model(BaseModel):\n    def extra(self): ...\n"
        "class Helper:\n    def hidden(self): ...\n",
        encoding="utf-8",
    )
    assert load_base_model_methods(source) == {"create", "write", "extra"}


def test_missing_models_source_gives_an_empty_set_and_a_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert load_base_model_methods(tmp_path / "absent.py") == frozenset()
    assert "Base model methods unavailable" in caplog.text
