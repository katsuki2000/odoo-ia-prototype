"""
code_intelligence/tests/test_bloc_p2_j2_3_graph_tagging.py

Regression lock for Bloc P2 Jour 2-3 (todo/plan.md, todo/contexte.txt
section 170): OdooGraphBuilder annotates Rule/AccessEntry/Model/Field/
Method/ServerAction/AutomationRule nodes with behavioral_tags/
technical_tags from code_intelligence/semantic_tags.py at build time.

This file was written after the tagging code already existed in
graph_builder.py (found already present, referencing a section 170 not
yet logged -- same parallel-session pattern already documented several
times in contexte.txt, e.g. sections 85/107/135/136/158). No production
code is changed here, only test coverage for what was already written.

Builds small synthetic ParsedModule fixtures directly (dataclasses from
python_extractor/xml_extractor/csv_extractor) rather than parsing real
corpus files, so each assertion targets exactly one tagging rule in
isolation. Not executed in this session -- filesystem access only:
    pytest code_intelligence/tests/test_bloc_p2_j2_3_graph_tagging.py -v
"""


import pytest

from code_intelligence.extractor.python import (
    OdooModelDeclaration,
    OdooFieldDeclaration,
    OdooMethodDeclaration,
    OdooMethodDecoration,
)
from code_intelligence.extractor.xml_models import (
    OdooRuleRecord,
    OdooServerActionRecord,
    OdooBaseAutomationRecord,
)
from code_intelligence.extractor.csv import OdooAccessEntry
from code_intelligence.graph.nodes import ParsedModule
from code_intelligence.graph.symbols import build_module_symbol_registry
from code_intelligence.graph.builder import OdooGraphBuilder
from code_intelligence.rules.ontology import BehavioralTag, TechnicalTag

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
    """Build one small graph exercising every Jour 2-3 tagging rule at once."""
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
        model_id="custom.test.workflow",
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


def test_model_without_state_field_has_no_behavioral_tags(tagged_graph):
    assert tagged_graph.nodes["model:custom.test.plain"]["behavioral_tags"] == []


def test_model_with_state_field_gets_workflow_rule_tag(tagged_graph):
    assert tagged_graph.nodes["model:custom.test.workflow"]["behavioral_tags"] == [
        BehavioralTag.WORKFLOW_RULE.value
    ]


def test_computed_field_gets_calculation_rule_and_computed_field_tags(tagged_graph):
    node = tagged_graph.nodes["field:custom.test.plain.total"]
    assert node["behavioral_tags"] == [BehavioralTag.CALCULATION_RULE.value]
    assert node["technical_tags"] == [TechnicalTag.COMPUTED_FIELD.value]


def test_non_computed_field_gets_no_tags(tagged_graph):
    node = tagged_graph.nodes["field:custom.test.plain.name"]
    assert node["behavioral_tags"] == []
    assert node["technical_tags"] == []


def test_method_with_has_group_and_raise_gets_blocking_rule_tag(tagged_graph):
    node = tagged_graph.nodes["method:custom.test.plain.action_validate"]
    assert BehavioralTag.BLOCKING_RULE.value in node["behavioral_tags"]


def test_method_without_has_group_and_raise_gets_no_blocking_rule_tag(tagged_graph):
    node = tagged_graph.nodes["method:custom.test.plain.action_noop"]
    assert BehavioralTag.BLOCKING_RULE.value not in node["behavioral_tags"]


def test_method_with_constrains_decorator_gets_constraint_technical_tag(tagged_graph):
    node = tagged_graph.nodes["method:custom.test.plain._check_amount"]
    assert TechnicalTag.CONSTRAINT.value in node["technical_tags"]


def test_rule_always_gets_visibility_rule_and_record_rule_tags(tagged_graph):
    node = tagged_graph.nodes["rule:custom_test.rule_plain"]
    assert node["behavioral_tags"] == [BehavioralTag.VISIBILITY_RULE.value]
    assert node["technical_tags"] == [TechnicalTag.RECORD_RULE.value]


def test_rule_gating_on_state_also_gets_workflow_rule_tag(tagged_graph):
    node = tagged_graph.nodes["rule:custom_test.rule_workflow"]
    assert node["behavioral_tags"] == [
        BehavioralTag.VISIBILITY_RULE.value,
        BehavioralTag.WORKFLOW_RULE.value,
    ]


def test_access_entry_gets_visibility_rule_and_acl_tags(tagged_graph):
    node = tagged_graph.nodes["acl:custom_test.access_custom_test_plain"]
    assert node["behavioral_tags"] == [BehavioralTag.VISIBILITY_RULE.value]
    assert node["technical_tags"] == [TechnicalTag.ACL.value]


def test_server_action_gets_server_action_technical_tag_and_no_behavioral_tag(tagged_graph):
    node = tagged_graph.nodes["server_action:custom_test.action_server_test"]
    assert node["behavioral_tags"] == []
    assert node["technical_tags"] == [TechnicalTag.SERVER_ACTION.value]


def test_automation_rule_gets_cron_technical_tag_and_no_behavioral_tag(tagged_graph):
    node = tagged_graph.nodes["automation:custom_test.automation_test"]
    assert node["behavioral_tags"] == []
    assert node["technical_tags"] == [TechnicalTag.CRON.value]
