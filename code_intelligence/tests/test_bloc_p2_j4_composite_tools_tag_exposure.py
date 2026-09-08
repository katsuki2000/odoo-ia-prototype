"""
code_intelligence/tests/test_bloc_p2_j4_composite_tools_tag_exposure.py

Regression lock for Bloc P2 Jour 4 (todo/plan.md, todo/contexte.txt
section 172): the 5 composite tools (who_has_access_to,
field_change_impact, button_execution_path, trace_full_inheritance,
describe_workflow -- deterministic_tools.py) expose the
behavioral_tags/technical_tags already written onto graph nodes by Bloc P2
Jour 2-3 (graph_builder.py), via new default-empty dataclass fields
(RuleDetail.tags, FieldImpactResult.field_tags,
ButtonExecutionPathResult.method_tags, InheritanceChainResult.model_tags,
WorkflowProcessResult.model_tags).

Found on disk already wired for 3/5 tools (who_has_access_to,
field_change_impact, button_execution_path) -- same parallel-session
pattern already documented several times in contexte.txt (sections
85/107/135/136/158/170). trace_full_inheritance and describe_workflow
were missing model_tags entirely; that gap was closed this tour (see
contexte.txt section 172) and is covered here alongside the 3 already
wired, plus semantic_tag_query.get_tagged_nodes_for_model (present on
disk, unused/untested until now).

Reuses the same synthetic fixture shape as
test_bloc_p2_j2_3_graph_tagging.py (isolated ParsedModule, not a real
corpus parse) so each assertion targets exactly one tool's tag exposure.
"""

import pytest

from code_intelligence.extractor.python_extractor import (
    OdooModelDeclaration,
    OdooFieldDeclaration,
    OdooMethodDeclaration,
    OdooMethodDecoration,
)
from code_intelligence.extractor.xml_extractor import (
    OdooRuleRecord,
    OdooServerActionRecord,
    OdooBaseAutomationRecord,
)
from code_intelligence.extractor.csv_extractor import OdooAccessEntry
from code_intelligence.cross_file_resolver import ParsedModule, build_module_symbol_registry
from code_intelligence.graph_builder import OdooGraphBuilder
from code_intelligence.semantic_tags import BehavioralTag, TechnicalTag
from code_intelligence.semantic_tag_query import get_tagged_nodes_for_model
from code_intelligence.deterministic_tools import (
    who_has_access_to,
    field_change_impact,
    button_execution_path,
    trace_full_inheritance,
    describe_workflow,
    QueryStatus,
)

METHOD_SOURCE = """class CustomTestPlain(models.Model):
    _name = "custom.test.plain"

    def action_validate(self):
        if not self.env.user.has_group("base.group_system"):
            raise UserError("Not allowed")
        return True

    def action_noop(self):
        return True
"""
# action_validate: lineno=4, end_lineno=7 (has_group + raise both in slice)
# action_noop: lineno=9, end_lineno=10 (neither present)


@pytest.fixture
def tagged_graph(tmp_path):
    """Same fixture shape as test_bloc_p2_j2_3_graph_tagging.py: one small
    graph exercising every Jour 2-3 tagging rule, reused here to check
    that Jour 4's tool-level exposure matches the underlying node tags."""
    src_file = tmp_path / "custom_test_plain.py"
    src_file.write_text(METHOD_SOURCE, encoding="utf-8")

    model_plain = OdooModelDeclaration(
        class_name="CustomTestPlain",
        filepath=str(src_file),
        lineno=1,
        name="custom.test.plain",
        fields=[
            OdooFieldDeclaration(name="name", field_type="Char"),
            OdooFieldDeclaration(name="total", field_type="Float", compute="_compute_total", store=True),
        ],
        methods=[
            OdooMethodDeclaration(name="action_validate", lineno=4, end_lineno=7),
            OdooMethodDeclaration(name="action_noop", lineno=9, end_lineno=10),
            OdooMethodDeclaration(
                name="_check_amount",
                lineno=1,
                end_lineno=None,
                decorators=[OdooMethodDecoration(decorator_type="constrains", trigger_fields=["total"])],
            ),
        ],
    )

    model_workflow = OdooModelDeclaration(
        class_name="CustomTestWorkflow",
        filepath=str(src_file),
        lineno=1,
        name="custom.test.workflow",
        fields=[OdooFieldDeclaration(name="state", field_type="Selection")],
    )

    rule_workflow = OdooRuleRecord(
        xml_id="custom_test.rule_workflow",
        filepath="",
        lineno=1,
        name="Workflow rule",
        model_id="custom.test.plain",
        domain_force="[('state', '=', 'draft')]",
    )
    rule_plain = OdooRuleRecord(
        xml_id="custom_test.rule_plain",
        filepath="",
        lineno=1,
        name="Company rule",
        model_id="custom.test.plain",
        domain_force="[('company_id', '=', 1)]",
    )

    acl = OdooAccessEntry(
        xml_id="access_custom_test_plain",
        filepath="",
        lineno=1,
        name="access.custom.test.plain",
        model_id="custom.test.plain",
        all_authenticated=True,
        perm_read=True,
    )

    server_action = OdooServerActionRecord(
        xml_id="custom_test.action_server_test",
        filepath="",
        lineno=1,
        name="Test Server Action",
        model_id="custom.test.plain",
        state="code",
        code="pass",
    )

    automation = OdooBaseAutomationRecord(
        xml_id="custom_test.automation_test",
        filepath="",
        lineno=1,
        name="Test Automation",
        model_id="custom.test.plain",
        trigger="on_create",
    )

    mod = ParsedModule(
        manifest=None,
        models=[model_plain, model_workflow],
        rules=[rule_workflow, rule_plain],
        acl_entries=[acl],
        server_actions=[server_action],
        base_automations=[automation],
    )

    modules_dict = {"custom_test": mod}
    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    return builder.build_graph()


# ---------- who_has_access_to: RuleDetail.tags ----------

def test_who_has_access_to_exposes_tags_on_each_active_rule(tagged_graph):
    result = who_has_access_to(tagged_graph, "custom.test.plain", permission="read")
    by_xml_id = {r.rule_xml_id: r for r in result.active_rules}
    assert by_xml_id["custom_test.rule_plain"].tags == [
        BehavioralTag.VISIBILITY_RULE.value,
        TechnicalTag.RECORD_RULE.value,
    ]
    assert by_xml_id["custom_test.rule_workflow"].tags == [
        BehavioralTag.VISIBILITY_RULE.value,
        BehavioralTag.WORKFLOW_RULE.value,
        TechnicalTag.RECORD_RULE.value,
    ]


# ---------- field_change_impact: FieldImpactResult.field_tags ----------

def test_field_change_impact_exposes_calculation_and_computed_field_tags(tagged_graph):
    result = field_change_impact(tagged_graph, "total", "custom.test.plain")
    assert result.field_tags == [
        BehavioralTag.CALCULATION_RULE.value,
        TechnicalTag.COMPUTED_FIELD.value,
    ]


def test_field_change_impact_reports_no_tags_for_plain_field(tagged_graph):
    result = field_change_impact(tagged_graph, "name", "custom.test.plain")
    assert result.field_tags == []


# ---------- button_execution_path: ButtonExecutionPathResult.method_tags ----------

def test_button_execution_path_exposes_blocking_rule_tag(tagged_graph):
    result = button_execution_path(tagged_graph, "action_validate", "custom.test.plain")
    assert BehavioralTag.BLOCKING_RULE.value in result.method_tags


def test_button_execution_path_reports_no_tags_for_method_without_guard(tagged_graph):
    result = button_execution_path(tagged_graph, "action_noop", "custom.test.plain")
    assert result.method_tags == []


def test_button_execution_path_reports_no_tags_when_method_not_found(tagged_graph):
    result = button_execution_path(tagged_graph, "action_does_not_exist", "custom.test.plain")
    assert result.method_tags == []


# ---------- trace_full_inheritance: InheritanceChainResult.model_tags ----------

def test_trace_full_inheritance_exposes_workflow_rule_model_tag(tagged_graph):
    result = trace_full_inheritance(tagged_graph, "custom.test.workflow")
    assert result.status == QueryStatus.EMPTY
    assert result.model_tags == [BehavioralTag.WORKFLOW_RULE.value]


def test_trace_full_inheritance_reports_no_model_tags_for_untagged_model(tagged_graph):
    result = trace_full_inheritance(tagged_graph, "custom.test.plain")
    assert result.model_tags == []


def test_trace_full_inheritance_reports_no_model_tags_when_model_not_found(tagged_graph):
    result = trace_full_inheritance(tagged_graph, "does.not.exist")
    assert result.status == QueryStatus.NOT_FOUND
    assert result.model_tags == []


# ---------- describe_workflow: WorkflowProcessResult.model_tags ----------

def test_describe_workflow_exposes_workflow_rule_model_tag_even_with_no_transitions(tagged_graph):
    # This fixture's model_workflow has a `state` field (-> WORKFLOW_RULE
    # model tag from graph_builder.py) but no TRANSITIONS_VIA edges, so
    # status is EMPTY -- exercises the EMPTY-branch wiring specifically,
    # not just the FOUND branch already covered by the other 3 tools.
    result = describe_workflow(tagged_graph, "custom.test.workflow")
    assert result.status == QueryStatus.EMPTY
    assert result.model_tags == [BehavioralTag.WORKFLOW_RULE.value]


def test_describe_workflow_reports_no_model_tags_when_model_not_found(tagged_graph):
    result = describe_workflow(tagged_graph, "does.not.exist")
    assert result.status == QueryStatus.NOT_FOUND
    assert result.model_tags == []


# ---------- semantic_tag_query.get_tagged_nodes_for_model ----------

def test_get_tagged_nodes_for_model_filters_by_behavioral_tag(tagged_graph):
    results = get_tagged_nodes_for_model(
        tagged_graph, "custom.test.plain", behavioral_tag=BehavioralTag.BLOCKING_RULE.value
    )
    node_ids = [node_id for node_id, _ in results]
    assert node_ids == ["method:custom.test.plain.action_validate"]


def test_get_tagged_nodes_for_model_filters_by_technical_tag(tagged_graph):
    results = get_tagged_nodes_for_model(
        tagged_graph, "custom.test.plain", technical_tag=TechnicalTag.SERVER_ACTION.value
    )
    node_ids = [node_id for node_id, _ in results]
    assert node_ids == ["server_action:custom_test.action_server_test"]


def test_get_tagged_nodes_for_model_unfiltered_excludes_untagged_nodes(tagged_graph):
    results = get_tagged_nodes_for_model(tagged_graph, "custom.test.plain")
    node_ids = {node_id for node_id, _ in results}
    # Tagged nodes related to custom.test.plain: rule_plain, rule_workflow,
    # field 'total', method 'action_validate', method '_check_amount',
    # the ACL, the server action, the automation rule.
    assert node_ids == {
        "rule:custom_test.rule_plain",
        "rule:custom_test.rule_workflow",
        "field:custom.test.plain.total",
        "method:custom.test.plain.action_validate",
        "method:custom.test.plain._check_amount",
        "acl:custom_test.access_custom_test_plain",
        "server_action:custom_test.action_server_test",
        "automation:custom_test.automation_test",
    }
    # The model node itself carries no tags (no `state` field on
    # custom.test.plain), and untagged siblings (field 'name', method
    # 'action_noop') are excluded from the unfiltered case.
    assert "model:custom.test.plain" not in node_ids
    assert "field:custom.test.plain.name" not in node_ids
    assert "method:custom.test.plain.action_noop" not in node_ids


def test_get_tagged_nodes_for_model_returns_empty_for_unindexed_model(tagged_graph):
    assert get_tagged_nodes_for_model(tagged_graph, "does.not.exist") == []
