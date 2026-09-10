"""
code_intelligence/tests/test_s2_3_server_actions.py

Unit tests for Stories S2.3 & S2.4:
  - S2.3: Extract ir.actions.server and base.automation from XML data files.
  - S2.4: Detect sudo(), has_group(), and hardcoded lists in server action code fields.
  Validates adversarial test Q5.1 (bypass fournisseurs 42/108/231 via sudo()).
"""

import pytest
import textwrap
from pathlib import Path
from code_intelligence.knowledge_rules.extractor.xml_extractor import (
    parse_server_actions_from_xml,
    parse_base_automations_from_xml,
    OdooServerActionRecord,
    OdooBaseAutomationRecord,
)
from code_intelligence.knowledge_rules.server_actions import (
    analyze_server_action_code,
    ServerActionCodeAnalysis,
)


AUTOMATION_XML = textwrap.dedent("""\
    <odoo>
        <record id="ir_action_server_avoir_fournisseur_privilegie" model="ir.actions.server">
            <field name="name">Auto-validation avoirs fournisseurs privilegies (logique cachee)</field>
            <field name="model_id" ref="account.model_account_move"/>
            <field name="state">code</field>
            <field name="code">
    # Regle non documentee ailleurs
    FOURNISSEURS_PRIVILEGIES = [42, 108, 231]
    for rec in records:
        if rec.move_type == 'in_refund' and rec.partner_id.id in FOURNISSEURS_PRIVILEGIES:
            rec.sudo().action_post()
            </field>
        </record>

        <record id="base_automation_avoir_fournisseur_privilegie" model="base.automation">
            <field name="name">Validation auto avoirs fournisseurs privilegies</field>
            <field name="model_id" ref="account.model_account_move"/>
            <field name="trigger">on_create_or_write</field>
            <field name="action_server_ids" eval="[(4, ref('ir_action_server_avoir_fournisseur_privilegie'))]"/>
        </record>
    </odoo>
""")


@pytest.fixture
def xml_file(tmp_path):
    p = tmp_path / "automation_rule.xml"
    p.write_text(AUTOMATION_XML, encoding="utf-8")
    return p


# ── S2.3 Tests: XML Extraction ──────────────────────────────────────────────


class TestParseServerActions:
    def test_extracts_server_action_record(self, xml_file):
        actions = parse_server_actions_from_xml(xml_file)
        assert len(actions) == 1
        sa = actions[0]
        assert isinstance(sa, OdooServerActionRecord)
        assert sa.xml_id == "ir_action_server_avoir_fournisseur_privilegie"
        assert sa.name == "Auto-validation avoirs fournisseurs privilegies (logique cachee)"
        assert sa.model_id == "account.model_account_move"
        assert sa.state == "code"
        assert "FOURNISSEURS_PRIVILEGIES" in sa.code
        assert "sudo()" in sa.code

    def test_extracts_base_automation_record(self, xml_file):
        automations = parse_base_automations_from_xml(xml_file)
        assert len(automations) == 1
        ba = automations[0]
        assert isinstance(ba, OdooBaseAutomationRecord)
        assert ba.xml_id == "base_automation_avoir_fournisseur_privilegie"
        assert ba.name == "Validation auto avoirs fournisseurs privilegies"
        assert ba.model_id == "account.model_account_move"
        assert ba.trigger == "on_create_or_write"
        assert "ir_action_server_avoir_fournisseur_privilegie" in ba.action_server_ids

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.xml"
        p.write_text("<odoo></odoo>", encoding="utf-8")
        assert parse_server_actions_from_xml(p) == []
        assert parse_base_automations_from_xml(p) == []


# ── S2.4 Tests: Server Action Code Analysis ─────────────────────────────────


class TestServerActionCodeAnalysis:
    def test_detects_sudo_call(self):
        code = "rec.sudo().action_post()"
        analysis = analyze_server_action_code(code, "test_action")
        assert analysis.has_sudo is True
        assert any("sudo()" in w for w in analysis.security_warnings)

    def test_detects_hardcoded_id_list(self):
        code = "FOURNISSEURS_PRIVILEGIES = [42, 108, 231]\nfor rec in records:\n    if rec.partner_id.id in FOURNISSEURS_PRIVILEGIES:\n        pass"
        analysis = analyze_server_action_code(code, "test_action")
        assert analysis.has_hardcoded_ids is True
        assert [42, 108, 231] in analysis.hardcoded_id_lists

    def test_detects_has_group(self):
        code = "if env.user.has_group('base.group_system'):\n    rec.sudo().write({'state': 'done'})"
        analysis = analyze_server_action_code(code, "test_action")
        assert analysis.has_sudo is True
        assert analysis.has_group_checks == ["base.group_system"]

    def test_confidence_tag_is_low(self):
        code = "rec.sudo().action_post()"
        analysis = analyze_server_action_code(code, "test_action")
        assert analysis.confidence == "low"

    def test_clean_code_no_warnings(self):
        code = "for rec in records:\n    rec.write({'name': 'test'})"
        analysis = analyze_server_action_code(code, "test_action")
        assert analysis.has_sudo is False
        assert analysis.has_hardcoded_ids is False
        assert analysis.has_group_checks == []
        assert analysis.security_warnings == []

    def test_full_adversarial_code_q5_1(self):
        """Full integration test matching Q5.1 adversarial trap."""
        code = textwrap.dedent("""\
            # Regle non documentee ailleurs
            FOURNISSEURS_PRIVILEGIES = [42, 108, 231]
            for rec in records:
                if rec.move_type == 'in_refund' and rec.partner_id.id in FOURNISSEURS_PRIVILEGIES:
                    rec.sudo().action_post()
        """)
        analysis = analyze_server_action_code(code, "ir_action_server_avoir_fournisseur_privilegie")
        assert analysis.has_sudo is True
        assert analysis.has_hardcoded_ids is True
        assert [42, 108, 231] in analysis.hardcoded_id_lists
        assert analysis.confidence == "low"
        assert len(analysis.security_warnings) >= 2  # sudo + hardcoded IDs
        # Summary should mention both risks
        assert "sudo" in analysis.summary_text.lower()
        assert "42" in analysis.summary_text
        # fix: the enclosing if-guard must be captured so that
        # Q5.1 can answer "NON, pas tous les avoirs" -- the bypass only
        # fires for in_refund moves from the 3 privileged partners.
        assert len(analysis.trigger_conditions) >= 1
        assert any("in_refund" in c for c in analysis.trigger_conditions), (
            f"Expected 'in_refund' guard in trigger_conditions, got: {analysis.trigger_conditions}"
        )
        # The condition should also appear in the summary text
        assert "in_refund" in analysis.summary_text, (
            f"Expected 'in_refund' in summary_text, got: {analysis.summary_text}"
        )
        # And in the security warnings themselves
        assert any("in_refund" in w for w in analysis.security_warnings), (
            f"Expected 'in_refund' in at least one security_warning"
        )
