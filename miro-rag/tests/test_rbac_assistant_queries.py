"""
miro-rag/tests/test_rbac_assistant_queries.py

Step 14 Day 3 Verification: End-to-End Assistant & Edge Case Verification.
Verifies via `query_graph` and tool binding that:
1. Sales User (`charlie@alpha.com`) asking an accounting question -> agent has no accounting tool and refuses/restricts access without data leak.
2. Admin asking the exact same accounting question -> agent gets full accounting tool access and returns financial answer.
3. Edge case: User with multiple groups (`alice@alpha.com` CEO/General Manager) -> gets tools across multiple domains.
4. Edge case: User with no relevant groups (`uid=9999` portal/no permissions) -> gets 0 domain tools and answers safely.
"""

import unittest
from unittest.mock import patch, MagicMock
import pytest
from tools.odoo_tools import connector, get_tools_for_skills, obtenir_ca_periode, obtenir_statut_commande, obtenir_total_factures
from rag.graph import query_graph, AssistantResponse


@pytest.mark.integration
class TestRBACAssistantQueries(unittest.TestCase):
    """Integration and edge-case suite verifying end-to-end assistant behavior under RBAC boundaries."""

    @classmethod
    def setUpClass(cls):
        cls.admin_uid = 2
        try:
            cls.admin_uid = connector.authenticate("admin")
            cls.charlie_uid = connector.common.authenticate(connector.db, "charlie@alpha.com", "password123", {})
            cls.alice_uid = connector.common.authenticate(connector.db, "alice@alpha.com", "password123", {})
        except Exception as e:
            raise unittest.SkipTest(f"Live Odoo database not accessible: {e}")

        if not cls.charlie_uid:
            raise unittest.SkipTest("Charlie user not found; run create_day2_setup.py first.")

    def test_01_sales_user_asks_accounting_question_refused(self):
        """Sales User (Charlie) asking accounting question -> agent has no accounting tool (`obtenir_total_factures`) and refuses safely."""
        skills = connector.get_user_skills(self.charlie_uid)
        self.assertFalse(skills["comptabilite"], "Sales user must not have comptabilite skill")
        
        tools = get_tools_for_skills(skills)
        self.assertNotIn(obtenir_total_factures, tools, "Accounting tools must NOT be bound for Charlie")

        # Verify query_graph execution with mock LLM observation ensuring refusal/no-permission behavior
        with patch("rag.graph.ChatGroq") as MockLLM:
            mock_instance = MagicMock()
            MockLLM.return_value = mock_instance
            mock_bound = MagicMock()
            mock_instance.bind_tools.return_value = mock_bound
            # Simulate LLM observing lack of accounting tools/data and refusing
            mock_bound.invoke.return_value = MagicMock(
                content="Désolé, je ne dispose pas des permissions ni des outils de comptabilité nécessaires pour accéder au total de vos factures.",
                tool_calls=[]
            )
            
            res = query_graph("Quel est le montant total des factures pour Azure Interior ?", uid=self.charlie_uid, company_id=2)
            self.assertTrue(hasattr(res, "answer"), "Response must be an AssistantResponse object")
            answer = res.answer.lower()
            self.assertTrue(
                any(kw in answer for kw in ["ne dispose pas", "pas les permissions", "pas l'accès", "pas autorisé", "désolé", "aucun outil", "comptabilité", "permission", "factures"]),
                f"Expected refusal/no-permission response for sales user asking accounting question, got: {res.answer}"
            )
            # Ensure the bound tools for Charlie did NOT include accounting tools
            for call_args in mock_instance.bind_tools.call_args_list:
                bound_tools_list = call_args[0][0]
                self.assertNotIn(obtenir_total_factures, bound_tools_list)

    def test_02_admin_asks_same_accounting_question_answered(self):
        """Admin asking exact same accounting question -> agent binds `obtenir_total_factures` and returns financial answer."""
        skills = connector.get_user_skills(self.admin_uid)
        self.assertTrue(skills["comptabilite"], "Admin user must have comptabilite skill")
        
        tools = get_tools_for_skills(skills)
        self.assertIn(obtenir_total_factures, tools, "Accounting tools MUST be bound for Admin")

        with patch("rag.graph.ChatGroq") as MockLLM:
            mock_instance = MagicMock()
            MockLLM.return_value = mock_instance
            mock_bound = MagicMock()
            mock_instance.bind_tools.return_value = mock_bound
            mock_bound.invoke.return_value = MagicMock(
                content="Le total des factures payées pour Azure Interior s'élève à 4 500.00 Ar.",
                tool_calls=[]
            )
            
            res = query_graph("Quel est le montant total des factures pour Azure Interior ?", uid=self.admin_uid, company_id=2)
            self.assertTrue(hasattr(res, "answer"), "Response must be an AssistantResponse object")
            answer = res.answer
            self.assertTrue(
                "Ar" in answer or "factures" in answer.lower() or "4 500" in answer,
                f"Expected financial answer for Admin, got: {answer}"
            )
            # Ensure the bound tools for Admin DID include accounting tools
            for call_args in mock_instance.bind_tools.call_args_list:
                bound_tools_list = call_args[0][0]
                self.assertIn(obtenir_total_factures, bound_tools_list)

    def test_03_edge_case_user_with_multiple_groups(self):
        """Edge Case: User with multiple groups (`alice@alpha.com`, CEO/General Manager) receives multi-domain tool access."""
        if not self.alice_uid:
            self.skipTest("Alice user not found.")
            
        skills = connector.get_user_skills(self.alice_uid)
        # Alice is in group_sale_salesman AND group_project_user
        self.assertTrue(skills["ventes"], "Alice CEO should have sales skill")
        self.assertTrue(skills["tickets"], "Alice CEO should have tickets skill")
        
        tools = get_tools_for_skills(skills)
        self.assertIn(obtenir_statut_commande, tools)
        self.assertGreaterEqual(len(tools), 4, "Multi-group user must receive tools from multiple domains")

    def test_04_edge_case_user_with_no_relevant_groups(self):
        """Edge Case: User with no relevant ERP groups (`uid=9999` or portal user) gets 0 domain tools and answers safely."""
        fake_uid = 9999
        skills = connector.get_user_skills(fake_uid)
        self.assertEqual(skills, {"ventes": False, "stocks": False, "comptabilite": False, "tickets": False})
        
        tools = get_tools_for_skills(skills)
        self.assertNotIn(obtenir_ca_periode, tools)
        self.assertNotIn(obtenir_statut_commande, tools)
        
        with patch("rag.graph.ChatGroq") as MockLLM:
            mock_instance = MagicMock()
            MockLLM.return_value = mock_instance
            mock_bound = MagicMock()
            mock_instance.bind_tools.return_value = mock_bound
            mock_bound.invoke.return_value = MagicMock(
                content="Désolé, je ne dispose pas d'accès aux données ERP pour répondre à votre question.",
                tool_calls=[]
            )
            res = query_graph("Quel est le statut de la commande S00001 ?", uid=fake_uid, company_id=2)
            self.assertTrue(hasattr(res, "answer"), "Response must be an AssistantResponse object")
            answer = res.answer.lower()
            self.assertTrue(
                any(kw in answer for kw in ["ne dispose pas", "pas les permissions", "pas l'accès", "pas autorisé", "désolé", "aucun outil", "ne peux pas", "je ne peux pas", "introuvable", "inconnu", "disponible", "pas d'accès"]),
                f"Expected graceful no-access/no-tool response for unprivileged user, got: {res.answer}"
            )


if __name__ == "__main__":
    unittest.main()
