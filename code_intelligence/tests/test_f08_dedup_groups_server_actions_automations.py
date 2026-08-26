"""
code_intelligence/tests/test_f08_dedup_groups_server_actions_automations.py

Regression test for the F-08 finding , extended on 2026-08-07.

J7 found and fixed F-08 only for `rules`: cross_file_resolver's
build_module_symbol_registry indexes each record under BOTH its full
xml_id and its short (unqualified) xml_id, both keys pointing to the same
object. Iterating .items() naively over such a registry therefore builds
TWO graph nodes per real record, and the short-key duplicate has no '.' in
it, so any code deriving a module prefix from it silently falls back to a
wrong/hardcoded prefix.

todo/revue_code_20260806_override_chain.md (finding F5) found that the
same defect was never fixed for `server_actions`, `groups`, or
`base_automations` -- and confirmed it actively manifesting in production
(benchmark_run_bloc9_predispatch_v3_20260806_1145.log, Q5.1: the same
sudo() server action analysed and reported twice).

This test locks in the 2026-08-07 fix that replicates the J7 guard
(`if "." not in full_xml_id: continue`) on groups, server_actions, and
base_automations in graph_builder.py::_add_security_group_nodes.
"""

from code_intelligence.cross_file_resolver import ParsedModule, build_module_symbol_registry
from code_intelligence.graph_builder import OdooGraphBuilder
from code_intelligence.manifest_parser import OdooManifest
from code_intelligence.xml_extractor import (
    OdooGroupRecord,
    OdooServerActionRecord,
    OdooBaseAutomationRecord,
)


def _manifest(mod_name: str) -> OdooManifest:
    return OdooManifest(module_name=mod_name, filepath="", name=mod_name, depends=[])


def _build_single_module_graph(mod_name: str, mod: ParsedModule):
    modules_dict = {mod_name: mod}
    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    G = builder.build_graph()
    return registry, G


def test_group_double_indexing_produces_single_graph_node():
    mod_name = "custom_f08_regression"
    grp = OdooGroupRecord(
        xml_id="group_avoir_regional",  # short xml_id as written in XML
        filepath="fake/security/groups.xml",
        lineno=1,
        name="Avoirs - Visibilite Regionale",
    )
    mod = ParsedModule(manifest=_manifest(mod_name), groups=[grp])

    registry, G = _build_single_module_graph(mod_name, mod)

    # Upstream double-indexing confirmed: both keys resolve to the same object.
    assert registry.groups["group_avoir_regional"] is registry.groups[f"{mod_name}.group_avoir_regional"]

    group_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "Group"]
    assert group_nodes == [f"group:{mod_name}.group_avoir_regional"], (
        f"Expected exactly one Group node for the real group, got {group_nodes}"
    )


def test_server_action_double_indexing_produces_single_graph_node():
    """Direct regression test for the Q5.1 duplicate reported in
    todo/revue_code_20260806_override_chain.md finding F5."""
    mod_name = "custom_automation_traps"
    sa = OdooServerActionRecord(
        xml_id="ir_action_server_avoir_fournisseur_privilegie",
        filepath="fake/data/server_actions.xml",
        lineno=1,
        name="Avoir fournisseur privilegie",
        model_id="account.move",
    )
    mod = ParsedModule(manifest=_manifest(mod_name), server_actions=[sa])

    registry, G = _build_single_module_graph(mod_name, mod)

    assert (
        registry.server_actions["ir_action_server_avoir_fournisseur_privilegie"]
        is registry.server_actions[f"{mod_name}.ir_action_server_avoir_fournisseur_privilegie"]
    )

    sa_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "ServerAction"]
    assert sa_nodes == [f"server_action:{mod_name}.ir_action_server_avoir_fournisseur_privilegie"], (
        f"Expected exactly one ServerAction node (this is the exact Q5.1 duplicate-analysis "
        f"bug from revue_code_20260806_override_chain.md finding F5), got {sa_nodes}"
    )


def test_base_automation_double_indexing_produces_single_graph_node():
    mod_name = "custom_hr_leave_workflow"
    ba = OdooBaseAutomationRecord(
        xml_id="automation_conge_urgent",
        filepath="fake/data/automations.xml",
        lineno=1,
        name="Conge urgent",
        model_id="hr.leave",
        trigger="on_create",
    )
    mod = ParsedModule(manifest=_manifest(mod_name), base_automations=[ba])

    registry, G = _build_single_module_graph(mod_name, mod)

    assert (
        registry.base_automations["automation_conge_urgent"]
        is registry.base_automations[f"{mod_name}.automation_conge_urgent"]
    )

    ba_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "AutomationRule"]
    assert ba_nodes == [f"automation:{mod_name}.automation_conge_urgent"], (
        f"Expected exactly one AutomationRule node, got {ba_nodes}"
    )
