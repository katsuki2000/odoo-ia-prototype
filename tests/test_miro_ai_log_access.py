import csv
import re
from pathlib import Path
from xml.etree import ElementTree

SECURITY = Path(__file__).resolve().parents[1] / "odoo_addons/miro_ai/security"
TECHNICAL_ADMIN = "base.group_system"


def _log_rule_groups():
    root = ElementTree.parse(SECURITY / "miro_ai_security.xml").getroot()
    rules = {
        record.get("id"): record.find("field[@name='groups']").get("eval")
        for record in root.iter("record")
        if record.get("model") == "ir.rule"
    }
    return {name: re.findall(r"ref\('([^']+)'\)", eval_text) for name, eval_text in rules.items()}


def test_full_log_visibility_is_reserved_to_the_miro_ai_administrator_group():
    groups = _log_rule_groups()["rule_miro_ai_log_admin"]
    assert groups == ["group_miro_ai_admin"]


def test_technical_administrator_has_no_dedicated_log_access():
    with open(SECURITY / "ir.model.access.csv", encoding="utf-8", newline="") as handle:
        log_groups = [row["group_id:id"] for row in csv.DictReader(handle) if row["model_id:id"] == "model_miro_ai_log"]
    assert TECHNICAL_ADMIN not in log_groups
    assert "group_miro_ai_admin" in log_groups


def test_log_rules_are_updated_with_the_module():
    root = ElementTree.parse(SECURITY / "miro_ai_security.xml").getroot()
    for data in root.findall("data"):
        ids = {record.get("id") for record in data.findall("record")}
        if ids & {"rule_miro_ai_log_user", "rule_miro_ai_log_admin"}:
            assert data.get("noupdate") != "1"
