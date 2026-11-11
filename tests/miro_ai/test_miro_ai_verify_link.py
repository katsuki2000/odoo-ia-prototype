import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "odoo_addons/miro_ai/controllers/verify_link.py"


@pytest.fixture(scope="module")
def verify_link():
    spec = importlib.util.spec_from_file_location("miro_verify_link", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_link


def _evidence(method, model="product.template", **request):
    return {"scope": {"method": method, "model": model, "request": {"model": model, **request}}}


def test_last_read_is_linked(verify_link):
    dossier = [
        _evidence("search_count", domain=[["sale_ok", "=", True]]),
        _evidence("search_read", model="res.partner", domain=[["customer_rank", ">", 0]]),
    ]
    assert verify_link(dossier) == {"model": "res.partner", "domain": [["customer_rank", ">", 0]]}


@pytest.mark.parametrize("method", ["search", "search_read", "search_count", "read_group"])
def test_domain_methods_are_linked(verify_link, method):
    link = verify_link([_evidence(method, domain=[["purchase_ok", "=", True]])])
    assert link == {"model": "product.template", "domain": [["purchase_ok", "=", True]]}


def test_empty_domain_is_linked(verify_link):
    assert verify_link([_evidence("search_read", domain=[])]) == {"model": "product.template", "domain": []}


def test_tuples_become_lists(verify_link):
    link = verify_link([_evidence("search", domain=[("a", "=", 1)])])
    assert link["domain"] == [["a", "=", 1]]


def test_read_uses_ids(verify_link):
    link = verify_link([_evidence("read", ids=[6, 2], fields=["name"])])
    assert link == {"model": "product.template", "domain": [["id", "in", [6, 2]]]}


@pytest.mark.parametrize("ids", [[], None, "6", [1, "2"], [True]])
def test_read_without_valid_ids_has_no_link(verify_link, ids):
    assert verify_link([_evidence("read", ids=ids)]) is None


def test_schema_read_is_skipped_for_the_last_data_read(verify_link):
    dossier = [_evidence("search_count", domain=[]), _evidence("fields_get")]
    assert verify_link(dossier) == {"model": "product.template", "domain": []}


def test_schema_only_has_no_link(verify_link):
    assert verify_link([_evidence("fields_get"), _evidence("list_models")]) is None


def test_name_search_has_no_link_even_after_an_earlier_read(verify_link):
    dossier = [_evidence("search_read", domain=[]), _evidence("name_search", domain=[])]
    assert verify_link(dossier) is None


@pytest.mark.parametrize("dossier", [None, [], "x", {}, [None], [{}], [{"scope": None}], [{"scope": {}}]])
def test_empty_or_malformed_dossier_has_no_link(verify_link, dossier):
    assert verify_link(dossier) is None


def test_missing_or_invalid_domain_has_no_link(verify_link):
    assert verify_link([_evidence("search_read")]) is None
    assert verify_link([_evidence("search_read", domain="[]")]) is None


def test_link_never_reads_llm_text(verify_link):
    item = _evidence("search_read", domain=[["a", "=", 1]])
    item["claim"] = "open res.users"
    item["value"] = {"model": "res.users"}
    assert verify_link([item]) == {"model": "product.template", "domain": [["a", "=", 1]]}
