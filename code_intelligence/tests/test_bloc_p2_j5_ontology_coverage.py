"""
code_intelligence/tests/test_bloc_p2_j5_ontology_coverage.py

Bloc P2 Jour 5 (todo/plan.md, todo/contexte.txt section 174): coverage
tests for the semantic-tag ontology itself, not for one tagging rule in
isolation (that's already locked by test_bloc_p2_j2_3_graph_tagging.py
and test_bloc_p2_j4_composite_tools_tag_exposure.py). Jour 5's own
wording: "chaque type de noeud produit par l'extraction a-t-il au moins
un tag ? Detecter les noeuds non classes (gap de couverture de
l'ontologie elle-meme)."

Original finding (section 174), by direct reading of graph_builder.py:
4 of the 11 node types OdooGraphBuilder.build_graph() can produce
(Module, Group, Menu, WorkflowState) never received a behavioral_tags/
technical_tags attribute at all, as opposed to receiving one that is
sometimes an empty list.

User decision (section 179): 2 of those 4 -- WorkflowState and Menu --
are now tagged, per explicit mandate. WorkflowState's tag is
tautological (the node only exists because the model has a 'state'
field, the same precondition that already gives the Model node
WORKFLOW_RULE). Menu's tags are a pure propagation of the tags already
computed on the Model node it opens (via the existing OPENS_MODEL edge
resolution in _add_menu_nodes -- no new observation, no guess). Group
and Module remain untagged: no justifiable signal was identified for
either without guessing or without a heavier inverse-traversal
aggregation (Group is only ever referenced BY Rule/AccessEntry, never
the reverse; Module carries nothing that maps to a behavioral/technical
tag). See todo/contexte.txt section 179 for the full case-by-case
analysis.

Not executed in this session -- filesystem access only:
    pytest code_intelligence/tests/test_bloc_p2_j5_ontology_coverage.py -v
"""

from pathlib import Path

import pytest

from code_intelligence.extractor.python_extractor import (
    OdooModelDeclaration,
    OdooFieldDeclaration,
    OdooMethodDeclaration,
)
from code_intelligence.extractor.xml_extractor import (
    OdooRuleRecord,
    OdooGroupRecord,
    OdooServerActionRecord,
    OdooBaseAutomationRecord,
    OdooMenuItemRecord,
    OdooViewRecord,
    OdooFormButton,
)
from code_intelligence.extractor.csv_extractor import OdooAccessEntry
from code_intelligence.cross_file_resolver import ParsedModule, build_module_symbol_registry
from code_intelligence.graph_builder import OdooGraphBuilder

# The complete, closed set of node_type values OdooGraphBuilder can
# currently produce, per direct reading of graph_builder.py's five
# _add_*_nodes methods. Any node_type appearing in a real build that is
# NOT in this set means the extraction grew a new artifact kind without
# this coverage file being updated to classify it -- the exact
# "detecter les noeuds non classes" failure mode Jour 5 asks to guard
# against.
ALL_KNOWN_NODE_TYPES = {
    "Module", "Model", "Field", "Method", "Group",
    "Rule", "AccessEntry", "ServerAction", "AutomationRule",
    "Menu", "WorkflowState", "Button",
}

# Node types whose nodes carry a behavioral_tags/technical_tags
# attribute (even if the list is legitimately empty for a given
# instance, e.g. a Model with no 'state' field, or a ServerAction whose
# behavioral_tags is always [] by the "don't guess" design already
# locked in test_bloc_p2_j2_3_graph_tagging.py). Extended section 179
# to include WorkflowState (tautological tag) and Menu (propagated from
# the Model it opens) -- see module docstring.
TAG_CAPABLE_NODE_TYPES = {
    "Model", "Field", "Method", "Rule", "AccessEntry",
    "ServerAction", "AutomationRule", "WorkflowState", "Menu",
}

# Node types with NO tag attribute at all -- the remaining, deliberate
# part of the Jour 5 finding after section 179's decision. Structural/
# navigational nodes with no justifiable tag signal identified (Module:
# nothing extracted maps to a tag; Group: only ever referenced BY
# Rule/AccessEntry, never the reverse, no non-guessed signal of its
# own; Button: form view action button with no tags). See module docstring.
NON_TAG_CAPABLE_NODE_TYPES = {"Module", "Group", "Button"}

METHOD_SOURCE = """class CustomTestFull(models.Model):
    _name = "custom.test.full"
    _inherit = "custom.test.base"

    def action_validate(self):
        if not self.env.user.has_group("base.group_system"):
            raise UserError("Not allowed")
        return True
"""
# action_validate: lineno=5, end_lineno=8 (has_group + raise both in slice)


@pytest.fixture
def full_graph(tmp_path):
    """
    Build one graph exercising every node_type OdooGraphBuilder can
    produce -- Module, Model, Field, Method, Group, Rule, AccessEntry,
    ServerAction, AutomationRule, Menu, WorkflowState -- so the coverage
    tests below inspect a real build, not an assumption about what
    build_graph() emits.
    """
    src_file = tmp_path / "custom_test_full.py"
    src_file.write_text(METHOD_SOURCE, encoding="utf-8")

    model_workflow = OdooModelDeclaration(
        class_name="CustomTestFull",
        filepath=str(src_file),
        lineno=1,
        name="custom.test.full",
        fields=[
            OdooFieldDeclaration(name="name", field_type="Char"),
            OdooFieldDeclaration(name="state", field_type="Selection"),
        ],
        methods=[
            OdooMethodDeclaration(name="action_validate", lineno=5, end_lineno=8),
        ],
    )

    group = OdooGroupRecord(
        xml_id="custom_test.group_full_manager",
        filepath="",
        lineno=1,
        name="Full Test Manager",
        category_id="custom_test.module_category_full",
    )

    rule = OdooRuleRecord(
        xml_id="custom_test.rule_full",
        filepath="",
        lineno=1,
        name="Full rule",
        model_id="custom.test.full",
        domain_force="[('company_id', '=', 1)]",
        groups_id=["custom_test.group_full_manager"],
    )

    acl = OdooAccessEntry(
        xml_id="access_custom_test_full",
        filepath="",
        lineno=1,
        name="access.custom.test.full",
        model_id="custom.test.full",
        all_authenticated=True,
        perm_read=True,
    )

    server_action = OdooServerActionRecord(
        xml_id="custom_test.action_server_full",
        filepath="",
        lineno=1,
        name="Full Server Action",
        model_id="custom.test.full",
        state="code",
        code="pass",
    )

    automation = OdooBaseAutomationRecord(
        xml_id="custom_test.automation_full",
        filepath="",
        lineno=1,
        name="Full Automation",
        model_id="custom.test.full",
        trigger="on_create",
        action_server_ids=["custom_test.action_server_full"],
    )

    menu = OdooMenuItemRecord(
        xml_id="custom_test.menu_full",
        filepath="",
        lineno=1,
        name="Full Menu",
        action="custom_test.action_server_full",
    )

    view = OdooViewRecord(
        xml_id="custom_test.view_full_form",
        filepath="",
        lineno=1,
        name="custom.test.full.form",
        model="custom.test.full",
        view_type="form",
        buttons=[
            OdooFormButton(
                name="action_validate",
                string="Validate",
                states="draft",
            )
        ],
    )

    mod = ParsedModule(
        manifest=None,
        models=[model_workflow],
        rules=[rule],
        groups=[group],
        server_actions=[server_action],
        base_automations=[automation],
        menuitems=[menu],
        views=[view],
        acl_entries=[acl],
    )

    modules_dict = {"custom_test": mod}
    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    return builder.build_graph()


def _node_types_present(graph):
    return {data["node_type"] for _, data in graph.nodes(data=True)}


def test_all_node_types_produced_match_known_closed_set(full_graph):
    """
    Locks the full surface of node_type values a real build can emit.
    Fails if a future graph_builder.py change introduces a new artifact
    kind without this file being updated to classify its tag coverage --
    the "detecter les noeuds non classes" requirement of Jour 5.
    """
    present = _node_types_present(full_graph)
    assert present == ALL_KNOWN_NODE_TYPES, (
        f"graph_builder.py now produces node types not classified here: "
        f"{present - ALL_KNOWN_NODE_TYPES}. Update ALL_KNOWN_NODE_TYPES "
        f"and decide whether the new type is tag-capable before closing "
        f"this test."
    )


def test_tag_capable_and_non_tag_capable_sets_are_exhaustive_and_disjoint():
    """The two classification sets defined at module level must together
    cover every known node type exactly once -- a type miscounted in
    both, or in neither, would silently invalidate the two coverage
    tests below."""
    assert TAG_CAPABLE_NODE_TYPES | NON_TAG_CAPABLE_NODE_TYPES == ALL_KNOWN_NODE_TYPES
    assert TAG_CAPABLE_NODE_TYPES & NON_TAG_CAPABLE_NODE_TYPES == set()


def test_tag_capable_node_types_all_carry_tag_attributes(full_graph):
    """Every node of a type classified as tag-capable must expose both
    behavioral_tags and technical_tags (as a list, possibly empty for a
    given instance -- e.g. a Model without 'state', or ServerAction's
    always-empty behavioral_tags by design). Missing the attribute
    entirely on an instance of a tag-capable type would be a real
    regression, distinct from a legitimately empty list."""
    for node_id, data in full_graph.nodes(data=True):
        if data["node_type"] in TAG_CAPABLE_NODE_TYPES:
            assert "behavioral_tags" in data, f"{node_id} missing behavioral_tags"
            assert "technical_tags" in data, f"{node_id} missing technical_tags"
            assert isinstance(data["behavioral_tags"], list)
            assert isinstance(data["technical_tags"], list)


def test_non_tag_capable_node_types_have_no_tag_attributes_at_all(full_graph):
    """
    The actual Jour 5 finding: Module/Group/Menu/WorkflowState nodes
    carry NEITHER behavioral_tags NOR technical_tags -- not an empty
    list, the attribute is simply absent. Locked here as a documented,
    known gap (not silently fixed) so that if a future change starts
    tagging one of these types, this test breaks and forces an explicit
    decision to move that type into TAG_CAPABLE_NODE_TYPES rather than
    the change going unnoticed.
    """
    seen_non_tag_capable_types = set()
    for node_id, data in full_graph.nodes(data=True):
        if data["node_type"] in NON_TAG_CAPABLE_NODE_TYPES:
            seen_non_tag_capable_types.add(data["node_type"])
            assert "behavioral_tags" not in data, (
                f"{node_id} ({data['node_type']}) now has behavioral_tags -- "
                f"update NON_TAG_CAPABLE_NODE_TYPES/TAG_CAPABLE_NODE_TYPES."
            )
            assert "technical_tags" not in data, (
                f"{node_id} ({data['node_type']}) now has technical_tags -- "
                f"update NON_TAG_CAPABLE_NODE_TYPES/TAG_CAPABLE_NODE_TYPES."
            )
    # The fixture is built specifically to exercise every non-tag-capable
    # type at least once -- if one is missing here, the fixture itself
    # regressed, not just this assertion's target.
    assert seen_non_tag_capable_types == NON_TAG_CAPABLE_NODE_TYPES


def test_criteria_de_fin_scope_rule_and_access_entry_always_carry_both_tag_kinds(full_graph):
    """
    Bloc P2's own Critere de fin (todo/plan.md) requires 100% coverage
    on Rule/AccessEntry/Method-avec-verrou/ServerAction specifically --
    narrower than "every tag-capable type always non-empty" (Model and
    plain Fields/Methods are legitimately untagged when they don't
    match a rule). Rule and AccessEntry are the two types where the
    plan's own wording ("au moins un tag comportemental ET un tag
    technique") implies both lists must be non-empty on every instance,
    unconditionally -- verified directly here rather than assumed from
    test_bloc_p2_j2_3_graph_tagging.py's narrower per-rule checks.
    """
    for node_id, data in full_graph.nodes(data=True):
        if data["node_type"] in {"Rule", "AccessEntry"}:
            assert data["behavioral_tags"], f"{node_id} has empty behavioral_tags"
            assert data["technical_tags"], f"{node_id} has empty technical_tags"


def test_criteria_de_fin_scope_server_action_always_carries_technical_tag(full_graph):
    """ServerAction's technical_tags must always be non-empty (it IS the
    artifact); behavioral_tags is allowed to stay empty by the
    already-locked "don't guess" design (rules.md Regle 5) -- not
    re-asserted here, only that this test doesn't regress that design
    into requiring a guess."""
    for node_id, data in full_graph.nodes(data=True):
        if data["node_type"] == "ServerAction":
            assert data["technical_tags"], f"{node_id} has empty technical_tags"


def test_method_with_lock_pattern_is_the_criteria_de_fin_scope_not_every_method(full_graph):
    """Confirms the plan's "Method-avec-verrou" wording is a subset, not
    "every Method node" -- the method matching the has_group()+raise
    heuristic is tagged, but a tag-capable Method with no matching
    override site legitimately stays untagged (already covered per-rule
    in test_bloc_p2_j2_3_graph_tagging.py; re-verified here against this
    file's own fixture for internal consistency)."""
    node = full_graph.nodes["method:custom.test.full.action_validate"]
    assert node["behavioral_tags"] == ["blocking_rule"]


def test_workflow_state_always_carries_workflow_rule_tag(full_graph):
    """Section 179: every WorkflowState node's behavioral_tags is exactly
    ['workflow_rule'] -- tautological per the module docstring (the node
    only exists because the model has a 'state' field), not just
    'non-empty'. technical_tags stays empty (no technical tag of the
    closed enumeration applies to a state value itself)."""
    seen_any = False
    for node_id, data in full_graph.nodes(data=True):
        if data["node_type"] == "WorkflowState":
            seen_any = True
            assert data["behavioral_tags"] == ["workflow_rule"], node_id
            assert data["technical_tags"] == [], node_id
    assert seen_any, "fixture produced no WorkflowState node -- fixture regressed"


def test_menu_inherits_exact_tags_of_the_model_it_opens(full_graph):
    """Section 179: custom_test.menu_full's action resolves (via the
    server_action fallback in _add_menu_nodes) to custom.test.full, the
    same model tagged ['workflow_rule']/[] elsewhere in this fixture.
    The Menu node must carry an exact copy of those same two lists --
    not just 'non-empty' -- confirming the propagation reads the real
    Model node's tags rather than recomputing or guessing them."""
    menu_node = full_graph.nodes["menu:custom_test.menu_full"]
    model_node = full_graph.nodes["model:custom.test.full"]
    assert menu_node["behavioral_tags"] == model_node["behavioral_tags"] == ["workflow_rule"]
    assert menu_node["technical_tags"] == model_node["technical_tags"] == []
    # Copied, not aliased -- mutating one must never affect the other.
    assert menu_node["behavioral_tags"] is not model_node["behavioral_tags"]
