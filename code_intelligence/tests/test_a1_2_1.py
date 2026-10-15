from code_intelligence.tests._corpus_paths import CUSTOM_ADDONS_PATH
"""
code_intelligence/tests/test_a1_2_1.py

Unit tests for Task A1.2.1: Parser ir.rule.
Tests:
  1. ir.rule with perm_read=1, perm_write=0 distinct flags
  2. domain_force raw text string storage
  3. groups_id extraction from ref and eval
  4. Real XML test on odoo17-dev/addons/miro_ai/security/miro_ai_security.xml
"""

import tempfile
from pathlib import Path

from code_intelligence.extractor.xml import parse_ir_rules_from_xml


def test_ir_rule_parsing_distinct_permissions():
    """Test ir.rule parsing with distinct perm_read=1, perm_write=0 permissions."""
    xml_content = """<odoo>
    <data>
        <record id="rule_test_read_only" model="ir.rule">
            <field name="name">Test Read Only Rule</field>
            <field name="model_id" ref="model_sale_order"/>
            <field name="groups" eval="[(4, ref('base.group_user'))]"/>
            <field name="domain_force">[('state', '=', 'sale')]</field>
            <field name="perm_read" eval="1"/>
            <field name="perm_write" eval="0"/>
            <field name="perm_create" eval="0"/>
            <field name="perm_unlink" eval="0"/>
        </record>
    </data>
</odoo>
"""
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
        f.write(xml_content)
        f_path = Path(f.name)

    try:
        rules = parse_ir_rules_from_xml(f_path)
        assert len(rules) == 1
        rule = rules[0]

        assert rule.xml_id == "rule_test_read_only"
        assert rule.name == "Test Read Only Rule"
        assert rule.model_id == "model_sale_order"
        assert rule.domain_force == "[('state', '=', 'sale')]"
        assert rule.groups_id == ["base.group_user"]
        
        # Verify distinct permission flags
        assert rule.perm_read is True
        assert rule.perm_write is False
        assert rule.perm_create is False
        assert rule.perm_unlink is False
    finally:
        f_path.unlink()


def test_real_xml_miro_ai_rules():
    """Test parsing ir.rule records from real miro_ai_security.xml file."""
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    xml_file = CUSTOM_ADDONS_PATH / "miro_ai" / "security" / "miro_ai_security.xml"

    if xml_file.exists():
        rules = parse_ir_rules_from_xml(xml_file)
        assert len(rules) == 3

        rules_map = {r.xml_id: r for r in rules}
        assert "rule_miro_ai_log_user" in rules_map

        log_user_rule = rules_map["rule_miro_ai_log_user"]
        assert log_user_rule.name == "MIRO AI Log : Voir ses requêtes"
        assert log_user_rule.model_id == "model_miro_ai_log"
        assert log_user_rule.groups_id == ["base.group_user"]
        assert "user_id" in log_user_rule.domain_force
        assert log_user_rule.perm_read is True
        assert log_user_rule.perm_write is True
