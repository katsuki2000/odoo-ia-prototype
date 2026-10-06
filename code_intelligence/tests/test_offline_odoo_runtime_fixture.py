import pytest

from code_intelligence.graph.loader import _read_runtime_module_inventory
from code_intelligence.tests._live_odoo import skip_unless_modules_installed


@pytest.fixture(scope="module")
def inventory_seen_at_module_scope(offline_odoo_runtime):
    return _read_runtime_module_inventory()


def test_module_scoped_fixture_sees_no_live_odoo(inventory_seen_at_module_scope):
    assert inventory_seen_at_module_scope is None


class _FakeClient:
    def __init__(self, installed):
        self.installed = set(installed)

    def execute_kw(self, uid, model, method, args, kwargs):
        name = args[0][0][2]
        return [1] if name in self.installed else []


def test_skip_helper_passes_when_every_module_is_installed():
    skip_unless_modules_installed(_FakeClient({"a", "b"}), 1, ("a", "b"))


def test_skip_helper_skips_and_names_the_missing_module():
    with pytest.raises(pytest.skip.Exception) as raised:
        skip_unless_modules_installed(_FakeClient({"a"}), 1, ("a", "b"))
    assert "b" in str(raised.value)
