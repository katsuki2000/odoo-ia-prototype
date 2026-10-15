"""
test_action_extension_merge.py

Unit tests for the action extension merge fix (Bug B0 / Cross-File Reference Resolver Pass 1):
Ensures that <record> extensions (e.g. <record id="base.action_partner_form"
re-defined in a dependent module to tweak view_mode/domain/context)
do NOT blow away existing fields (_fields are only overridden by
actual values in the extending record). Tests base.action_partner_form / mail
and sales_team.crm_team_action_pipeline patterns.
"""


from code_intelligence.graph.symbols import build_module_symbol_registry
from code_intelligence.graph.nodes import ParsedModule
from code_intelligence.extractor.xml_models import OdooActionRecord


def _fake_module(actions, depends=None):
    """Create a temporary ParsedModule with minimal manifest for testing."""
    class _Manifest:
        def __init__(self, depends):
            self.depends = depends or []
            self.filepath = "fake/__manifest__.py"

    mod = ParsedModule(manifest=_Manifest(depends))
    mod.actions = actions
    return mod


def test_action_extension_preserves_res_model():
    """
    Exact reproduction of base.action_partner_form / mail pattern:
    - base declares action with res_model="res.partner"
    - mail (depends on base) re-opens same xml_id to tweak view_mode only
    Registry should keep original res_model intact.
    """
    base_action = OdooActionRecord(
        xml_id="action_partner_form",
        filepath="base/views/res_partner_views.xml",
        lineno=530,
        name="Customers",
        res_model="res.partner",
        view_mode="kanban,tree,form",
    )
    mail_extension = OdooActionRecord(
        xml_id="base.action_partner_form",  # Full xml_id as present in real XML
        filepath="mail/views/res_partner_views.xml",
        lineno=12,
        name="",
        res_model="",  # <-- Extension does NOT redefine res_model
        view_mode="kanban,tree,form,activity",
    )

    modules_dict = {
        "base": _fake_module([base_action]),
        "mail": _fake_module([mail_extension], depends=["base"]),
    }

    registry = build_module_symbol_registry(modules_dict)

    resolved = registry.actions.get("base.action_partner_form")
    assert resolved is not None, "Action should remain indexed after extension"
    assert resolved.res_model == "res.partner", (
        f"res_model lost after merge: expected 'res.partner', got "
        f"{resolved.res_model!r}"
    )
    # Field actually redefined by extension should be updated
    assert resolved.view_mode == "kanban,tree,form,activity", (
        f"Extension's view_mode not applied: {resolved.view_mode!r}"
    )


def test_action_extension_without_prior_declaration_keeps_own_values():
    """
    Edge case: action with new xml_id that has never been defined before.
    Merge logic should not affect this unrelated new record.
    """
    orphan_action = OdooActionRecord(
        xml_id="some_module.some_action",
        filepath="some_module/views/x.xml",
        lineno=1,
        name="Orphan",
        res_model="",
        view_mode="tree,form",
    )
    modules_dict = {"some_module": _fake_module([orphan_action])}

    registry = build_module_symbol_registry(modules_dict)

    resolved = registry.actions.get("some_module.some_action")
    assert resolved is not None
    assert resolved.res_model == "", "Empty field should stay empty"
    assert resolved.view_mode == "tree,form"


def test_action_declared_after_extension_in_load_order_wins_if_nonempty():
    """
    Guard: If (in a degenerate scenario) extension appears earlier due to
    topological order issues, a non-empty later declaration should still
    win over empty earlier, never the other way. Ensures monotonicity.
    """
    partial_first = OdooActionRecord(
        xml_id="mod_a.shared_action",
        filepath="mod_a/x.xml",
        lineno=1,
        res_model="",  # Empty at first
    )
    full_second = OdooActionRecord(
        xml_id="mod_a.shared_action",
        filepath="mod_a/y.xml",
        lineno=2,
        res_model="res.partner",
    )
    modules_dict = {
        "mod_a": _fake_module([partial_first, full_second]),
    }

    registry = build_module_symbol_registry(modules_dict)
    resolved = registry.actions.get("mod_a.shared_action")
    assert resolved.res_model == "res.partner", (
        f"Second non-empty declaration should win. Got {resolved.res_model!r}"
    )


def test_action_extension_overwrites_with_nonempty_fields():
    """
    Guard: When an extension does have a non-empty value, that value should
    override the existing one (the merge works both ways).
    """
    base_action = OdooActionRecord(
        xml_id="my.action",
        filepath="base/views/x.xml",
        lineno=1,
        res_model="res.partner",
        view_mode="kanban,tree",
    )
    extension = OdooActionRecord(
        xml_id="my.action",
        filepath="mod/y.xml",
        lineno=2,
        name="Different Name",  # explicit new name
        view_mode="",  # explicit empty for view_mode
    )
    modules_dict = {
        "base": _fake_module([base_action]),
        "mod": _fake_module([extension], depends=["base"]),
    }

    registry = build_module_symbol_registry(modules_dict)
    resolved = registry.actions.get("my.action")
    assert resolved is not None
    assert resolved.name == "Different Name", "New name should win"
    assert resolved.view_mode == "kanban,tree", "Empty extension value should keep old"
    assert resolved.res_model == "res.partner", "Non-extension field should persist"
