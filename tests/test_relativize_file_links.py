import pytest

from code_intelligence.utils import relativize_file_links

ROOTS = ("/srv/odoo/addons", "/srv/odoo/odoo/addons", "/home/dev/project/odoo_addons")


@pytest.mark.parametrize("link, expected", [
    ("(file:///home/dev/project/odoo_addons/custom_loan/models/loan.py#L1-L30)",
     "(file://odoo_addons/custom_loan/models/loan.py#L1-L30)"),
    ("(file:///srv/odoo/addons/sale/models/sale_order.py#L6-L6)",
     "(file://addons/sale/models/sale_order.py#L6-L6)"),
    ("(file:///srv/odoo/odoo/addons/base/models/res_users.py)",
     "(file://addons/base/models/res_users.py)"),
])
def test_absolute_link_keeps_the_path_from_the_addons_folder(link, expected):
    assert relativize_file_links(f"[x]{link}", ROOTS) == f"[x]{expected}"


def test_the_same_output_is_produced_on_another_machine():
    other = ("/opt/app/odoo_addons",)
    assert relativize_file_links("[a](file:///opt/app/odoo_addons/m/a.py#L1-L2)", other) == \
        relativize_file_links("[a](file:///home/dev/project/odoo_addons/m/a.py#L1-L2)", ROOTS)


@pytest.mark.parametrize("text", [
    "[a](file://odoo_addons/m/a.py#L1-L2)",
    "[a](file:///elsewhere/m/a.py#L1-L2)",
    "no link at all",
])
def test_relative_unknown_and_absent_links_are_unchanged(text):
    assert relativize_file_links(text, ROOTS) == text
