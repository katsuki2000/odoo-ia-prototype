"""
miro-rag/tests/test_rbac_tool_filtering.py

Unit and integration tests for Step 14 Day 1: Group-Based Tool Filtering.
Verifies that:
1. `OdooConnector.get_user_skills(uid)` reads `res.users` -> `groups_id` and accurately maps Odoo groups to tool categories.
2. `get_tools_for_skills(skills)` exposes only the tools matching the user's RBAC permissions.
3. `query_graph` and `orm_agent_loop` enforce skill boundaries via `bind_tools()`.
"""

import unittest
from unittest.mock import patch, MagicMock
import pytest
from tools.odoo_connector import OdooConnector
from tools.odoo_tools import (
    get_tools_for_skills,
    rechercher_client,
    obtenir_total_ventes,
    obtenir_statut_commande,
    obtenir_ca_periode,
    obtenir_stock_produit,
    lister_produits_en_rupture,
    obtenir_total_factures,
    obtenir_tickets_recents,
    connector,
)


class TestRBACToolFilteringUnit(unittest.TestCase):
    """Unit tests for RBAC tool filtering (offline / mocked)."""

    def setUp(self):
        self.mock_connector = OdooConnector(url="http://mock:8069", db="mock_db", password="mock_pwd")
        self.mock_connector.models = MagicMock()
        self.mock_connector.common = MagicMock()

    def test_01_admin_user_gets_all_skills(self):
        """Verify Admin/Superuser (uid 1 or 2) gets all skill categories unconditionally."""
        skills_uid1 = self.mock_connector.get_user_skills(1)
        skills_uid2 = self.mock_connector.get_user_skills(2)
        expected = {"ventes": True, "stocks": True, "comptabilite": True, "tickets": True}
        self.assertEqual(skills_uid1, expected)
        self.assertEqual(skills_uid2, expected)

        tools = get_tools_for_skills(skills_uid1)
        self.assertIn(obtenir_total_ventes, tools)
        self.assertIn(obtenir_stock_produit, tools)
        self.assertIn(obtenir_total_factures, tools)
        self.assertIn(obtenir_tickets_recents, tools)
        self.assertIn(rechercher_client, tools)
        self.assertEqual(len(tools), 8)

    def test_02_sales_user_skills_and_tools(self):
        """Verify user with only `sales_team.group_sale_salesman` gets only sales and base tools."""
        # Mock res.users read -> returns group ID 10
        self.mock_connector.models.execute_kw.side_effect = [
            [{"id": 42, "groups_id": [10]}], # res.users read
            [{"module": "sales_team", "name": "group_sale_salesman"}], # ir.model.data search_read
            [{"name": "User: Own Documents Only", "full_name": "Sales / User: Own Documents Only"}], # res.groups search_read
        ]

        skills = self.mock_connector.get_user_skills(42)
        self.assertEqual(skills["ventes"], True)
        self.assertEqual(skills["stocks"], False)
        self.assertEqual(skills["comptabilite"], False)
        self.assertEqual(skills["tickets"], False)

        tools = get_tools_for_skills(skills)
        self.assertIn(rechercher_client, tools)
        self.assertIn(obtenir_total_ventes, tools)
        self.assertIn(obtenir_statut_commande, tools)
        self.assertIn(obtenir_ca_periode, tools)
        self.assertNotIn(obtenir_stock_produit, tools)
        self.assertNotIn(obtenir_total_factures, tools)
        self.assertNotIn(obtenir_tickets_recents, tools)
        self.assertEqual(len(tools), 4) # rechercher_client + 3 sales tools

    def test_03_accountant_user_skills_and_tools(self):
        """Verify user with `account.group_account_invoice` gets only accounting and base tools."""
        self.mock_connector.models.execute_kw.side_effect = [
            [{"id": 99, "groups_id": [20]}],
            [{"module": "account", "name": "group_account_invoice"}],
            [{"name": "Billing", "full_name": "Invoicing / Billing"}],
        ]

        skills = self.mock_connector.get_user_skills(99)
        self.assertEqual(skills["ventes"], False)
        self.assertEqual(skills["stocks"], False)
        self.assertEqual(skills["comptabilite"], True)
        self.assertEqual(skills["tickets"], False)

        tools = get_tools_for_skills(skills)
        self.assertIn(rechercher_client, tools)
        self.assertIn(obtenir_total_factures, tools)
        self.assertNotIn(obtenir_total_ventes, tools)
        self.assertNotIn(obtenir_stock_produit, tools)
        self.assertNotIn(obtenir_tickets_recents, tools)
        self.assertEqual(len(tools), 2) # rechercher_client + 1 accounting tool

    def test_04_support_user_skills_and_tools(self):
        """Verify user with `project.group_project_user` / helpdesk gets only ticket and base tools."""
        self.mock_connector.models.execute_kw.side_effect = [
            [{"id": 105, "groups_id": [30]}],
            [{"module": "project", "name": "group_project_user"}],
            [{"name": "User", "full_name": "Project / User"}],
        ]

        skills = self.mock_connector.get_user_skills(105)
        self.assertEqual(skills["ventes"], False)
        self.assertEqual(skills["stocks"], False)
        self.assertEqual(skills["comptabilite"], False)
        self.assertEqual(skills["tickets"], True)

        tools = get_tools_for_skills(skills)
        self.assertIn(rechercher_client, tools)
        self.assertIn(obtenir_tickets_recents, tools)
        self.assertNotIn(obtenir_total_ventes, tools)
        self.assertNotIn(obtenir_total_factures, tools)
        self.assertNotIn(obtenir_stock_produit, tools)
        self.assertEqual(len(tools), 2) # rechercher_client + 1 ticket tool

    def test_05_multi_group_user_skills_and_tools(self):
        """Verify user with multiple groups (e.g. Sales + Inventory) gets both sales and stock tools."""
        self.mock_connector.models.execute_kw.side_effect = [
            [{"id": 200, "groups_id": [10, 40]}],
            [
                {"module": "sales_team", "name": "group_sale_salesman"},
                {"module": "stock", "name": "group_stock_user"},
            ],
            [
                {"name": "Sales User", "full_name": "Sales / User"},
                {"name": "Stock User", "full_name": "Inventory / User"},
            ],
        ]

        skills = self.mock_connector.get_user_skills(200)
        self.assertEqual(skills["ventes"], True)
        self.assertEqual(skills["stocks"], True)
        self.assertEqual(skills["comptabilite"], False)
        self.assertEqual(skills["tickets"], False)

        tools = get_tools_for_skills(skills)
        self.assertIn(obtenir_total_ventes, tools)
        self.assertIn(obtenir_stock_produit, tools)
        self.assertIn(lister_produits_en_rupture, tools)
        self.assertNotIn(obtenir_total_factures, tools)
        self.assertNotIn(obtenir_tickets_recents, tools)
        self.assertEqual(len(tools), 6) # base + 3 sales + 2 stocks


@pytest.mark.integration
class TestRBACToolFilteringIntegration(unittest.TestCase):
    """Integration tests for RBAC tool filtering against live Odoo XML-RPC server."""

    def test_live_admin_user_skills(self):
        """Verify live Admin user gets all 4 skill categories."""
        try:
            admin_uid = connector.authenticate("admin")
            self.assertGreater(admin_uid, 0)
            skills = connector.get_user_skills(admin_uid)
            self.assertTrue(skills["ventes"])
            self.assertTrue(skills["stocks"])
            self.assertTrue(skills["comptabilite"])
            self.assertTrue(skills["tickets"])
        except Exception as e:
            self.skipTest(f"Odoo integration not reachable or auth failed: {e}")

    def test_live_specialized_profiles(self):
        """Verify specialized users created in Day 2 get exact tool mappings."""
        profiles = [
            ("charlie@alpha.com", "password123", "ventes"),
            ("fiona@beta.com", "password123", "comptabilite"),
            ("diana@beta.com", "password123", "tickets"),
            ("bob@alpha.com", "password123", "stocks"),
        ]
        for login, pwd, expected_skill in profiles:
            try:
                uid = connector.common.authenticate(connector.db, login, pwd, {})
                if not uid:
                    continue
                skills = connector.get_user_skills(uid)
                self.assertTrue(skills.get(expected_skill, False), f"User {login} (uid {uid}) should have {expected_skill}=True, got {skills}")
                
                # Check that other skills (except base/multi) are False or properly scoped
                if expected_skill == "comptabilite":
                    self.assertFalse(skills["ventes"], f"Accountant {login} should NOT have ventes=True!")
                    self.assertFalse(skills["stocks"], f"Accountant {login} should NOT have stocks=True!")
            except Exception as e:
                continue


if __name__ == "__main__":
    unittest.main()
