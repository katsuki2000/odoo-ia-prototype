import csv
import re
from pathlib import Path
from xml.etree import ElementTree

SECURITY = Path(__file__).resolve().parents[2] / "odoo_addons/miro_ai/security"
TECHNICAL_ADMIN = "base.group_system"
LOG_RULES = {"rule_miro_ai_log_user"}


def _log_rule_groups():
    root = ElementTree.parse(SECURITY / "miro_ai_security.xml").getroot()
    rules = {
        record.get("id"): record.find("field[@name='groups']").get("eval")
        for record in root.iter("record")
        if record.get("model") == "ir.rule" and "model_miro_ai_log" in record.find("field[@name='model_id']").get("ref")
    }
    return {name: re.findall(r"ref\('([^']+)'\)", eval_text) for name, eval_text in rules.items()}


def _log_access_rows():
    with open(SECURITY / "ir.model.access.csv", encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row["model_id:id"] == "model_miro_ai_log"]


def test_the_only_log_rule_restricts_every_user_to_their_own_requests():
    rules = _log_rule_groups()
    assert set(rules) == LOG_RULES
    assert rules["rule_miro_ai_log_user"] == ["base.group_user"]


def test_no_group_can_read_the_requests_of_other_users():
    root = ElementTree.parse(SECURITY / "miro_ai_security.xml").getroot()
    domains = [
        record.find("field[@name='domain_force']").text
        for record in root.iter("record")
        if record.get("id") == "rule_miro_ai_log_user"
    ]
    assert len(domains) == 1 and "user_id" in domains[0] and "user.id" in domains[0]


def test_log_access_is_read_only_for_users_and_absent_for_administrators():
    rows = _log_access_rows()
    assert [row["group_id:id"] for row in rows] == ["base.group_user"]
    row = rows[0]
    assert (row["perm_read"], row["perm_write"], row["perm_create"], row["perm_unlink"]) == ("1", "0", "0", "0")
    assert TECHNICAL_ADMIN not in {row["group_id:id"] for row in rows}


def test_log_rules_are_updated_with_the_module():
    root = ElementTree.parse(SECURITY / "miro_ai_security.xml").getroot()
    for data in root.findall("data"):
        ids = {record.get("id") for record in data.findall("record")}
        if ids & LOG_RULES:
            assert data.get("noupdate") != "1"
