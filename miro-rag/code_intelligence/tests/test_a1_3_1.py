"""
code_intelligence/tests/test_a1_3_1.py

Unit tests for Story A1.3 (Tasks A1.3.1 & A1.3.2): CSV ACL parsing & empty group_id handling.
Tests:
  1. Standard CSV ACL row parsing
  2. Empty group_id handling -> all_authenticated=True, group_id=None
  3. Header variation support (model_id:id vs model_id/id)
  4. Real CSV test on addons/account/ir.model.access.csv
"""

import tempfile
from pathlib import Path

from code_intelligence.csv_extractor import parse_access_control_csv


def test_empty_group_id_all_authenticated():
    """Test Task A1.3.2: Empty group_id row creates AccessEntry with all_authenticated=True."""
    csv_content = """id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_public_read,public.read,model_public_model,,1,0,0,0
access_restricted_write,restricted.write,model_restricted_model,base.group_user,1,1,0,0
"""
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(csv_content)
        f_path = Path(f.name)

    try:
        entries = parse_access_control_csv(f_path)
        assert len(entries) == 2
        entries_map = {e.xml_id: e for e in entries}

        # 1. Empty group_id entry
        assert "access_public_read" in entries_map
        pub_entry = entries_map["access_public_read"]
        assert pub_entry.model_id == "model_public_model"
        assert pub_entry.group_id is None
        assert pub_entry.all_authenticated is True
        assert pub_entry.perm_read is True
        assert pub_entry.perm_write is False

        # 2. Specified group_id entry
        assert "access_restricted_write" in entries_map
        res_entry = entries_map["access_restricted_write"]
        assert res_entry.group_id == "base.group_user"
        assert res_entry.all_authenticated is False
        assert res_entry.perm_read is True
        assert res_entry.perm_write is True

    finally:
        f_path.unlink()


def test_header_variations():
    """Test support for model_id/id and group_id/id header variations."""
    csv_content = """id,name,model_id/id,group_id/id,perm_read,perm_write,perm_create,perm_unlink
access_test,test.access,model_test_model,base.group_system,1,1,1,1
"""
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(csv_content)
        f_path = Path(f.name)

    try:
        entries = parse_access_control_csv(f_path)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.xml_id == "access_test"
        assert entry.model_id == "model_test_model"
        assert entry.group_id == "base.group_system"
        assert entry.perm_unlink is True
    finally:
        f_path.unlink()


def test_real_csv_account_access():
    """Test parsing real account/security/ir.model.access.csv file."""
    corpus_root = Path("/home/user/odoo-17.0/addons")
    csv_file = corpus_root / "account" / "security" / "ir.model.access.csv"

    if csv_file.exists():
        entries = parse_access_control_csv(csv_file)
        assert len(entries) == 7

        move_entry = next((e for e in entries if e.xml_id == "access_account_move"), None)
        assert move_entry is not None
        assert move_entry.name == "account.move"
        assert move_entry.model_id == "model_account_move"
        assert move_entry.group_id == "account.group_account_user"
        assert move_entry.perm_read is True
        assert move_entry.perm_write is True
        assert move_entry.perm_create is True
        assert move_entry.perm_unlink is False
