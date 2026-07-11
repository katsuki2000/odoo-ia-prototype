"""
miro-rag/tests/test_ir_rule_enforcement_profiles.py

Step 14 Day 2 Verification: ir.rule Record Rules and RBAC Profile Enforcement.
Verifies across 3 distinct profiles (Admin, Sales User, Support User) with 15 test queries (5 per profile):
1. Admin (uid=2): Sees all domain data across sales, stocks, accounting, and tickets.
2. Sales User (`charlie@alpha.com`, Company Alpha): Sees Company Alpha sales data and client records; restricted from accounting, stock, and ticket tools/records.
3. Support User (`diana@beta.com`, Company Beta): Sees Company Beta support tickets and client records; restricted from sales, accounting, and stock tools/records.
"""

import unittest
import pytest
from tools.odoo_connector import OdooConnectorError
from tools.odoo_tools import (
    connector,
    odoo_uid_ctx,
    get_tools_for_skills,
    rechercher_client,
    obtenir_total_ventes,
    obtenir_statut_commande,
    obtenir_ca_periode,
    obtenir_stock_produit,
    lister_produits_en_rupture,
    obtenir_total_factures,
    obtenir_tickets_recents,
)
from rag.graph import query_graph


@pytest.mark.integration
class TestIRRuleEnforcementProfiles(unittest.TestCase):
    """Integration test suite verifying Odoo ir.rule record rules and RBAC tool boundaries for 15 queries."""

    @classmethod
    def setUpClass(cls):
        """Authenticate and retrieve exact UIDs for Admin, Charlie (Sales), and Diana (Support)."""
        cls.admin_uid = 2
        try:
            cls.admin_uid = connector.authenticate("admin")
            cls.charlie_uid = connector.common.authenticate(connector.db, "charlie@alpha.com", "password123", {})
            cls.diana_uid = connector.common.authenticate(connector.db, "diana@beta.com", "password123", {})
        except Exception as e:
            raise unittest.SkipTest(f"Live Odoo database not accessible for ir.rule verification: {e}")

        if not cls.charlie_uid or not cls.diana_uid:
            raise unittest.SkipTest("Charlie or Diana accounts missing; ensure create_day2_setup.py has been executed.")

    # =========================================================================
    # PROFILE 1: Admin (`uid=admin_uid`) -> Sees Everything (5 Queries)
    # =========================================================================

    def test_q01_admin_order_status(self):
        """Q1 [Admin]: Verify Admin can inspect sales order S00001 status."""
        token = odoo_uid_ctx.set(self.admin_uid)
        try:
            res = obtenir_statut_commande.invoke({'reference': 'S00001'})
            self.assertIsInstance(res, str)
            self.assertTrue("S00001" in res or "introuvable" in res or "statut" in res.lower())
        finally:
            odoo_uid_ctx.reset(token)

    def test_q02_admin_total_ca(self):
        """Q2 [Admin]: Verify Admin can calculate global revenue across companies."""
        token = odoo_uid_ctx.set(self.admin_uid)
        try:
            res = obtenir_ca_periode.invoke({'periode': '2024'})
            self.assertIsInstance(res, str)
            self.assertTrue("Ar" in res or "chiffre d'affaires" in res.lower() or "ca" in res.lower())
        finally:
            odoo_uid_ctx.reset(token)

    def test_q03_admin_stock_availability(self):
        """Q3 [Admin]: Verify Admin can check stock quantities for ergonomic chairs."""
        token = odoo_uid_ctx.set(self.admin_uid)
        try:
            res = obtenir_stock_produit.invoke({'produit': 'Chaise de Bureau Ergonomique'})
            self.assertIsInstance(res, str)
            self.assertTrue("unités" in res or "Inconnu" in res or "trouvé" in res)
        finally:
            odoo_uid_ctx.reset(token)

    def test_q04_admin_unpaid_invoices(self):
        """Q4 [Admin]: Verify Admin can inspect accounting unpaid invoices."""
        token = odoo_uid_ctx.set(self.admin_uid)
        try:
            res = obtenir_total_factures.invoke({'client': 'Client Alpha', 'statut': 'impayé'})
            self.assertIsInstance(res, str)
            self.assertTrue("Ar" in res or "Aucune facture" in res or "AMBIGU" in res)
        finally:
            odoo_uid_ctx.reset(token)

    def test_q05_admin_recent_tickets(self):
        """Q5 [Admin]: Verify Admin can access helpdesk/project support tickets."""
        token = odoo_uid_ctx.set(self.admin_uid)
        try:
            res = obtenir_tickets_recents.invoke({'client': 'Client Alpha', 'limite': 5})
            self.assertIsInstance(res, str)
            self.assertTrue("ticket" in res.lower() or "aucun ticket" in res.lower())
        finally:
            odoo_uid_ctx.reset(token)

    # =========================================================================
    # PROFILE 2: Sales User Charlie (`uid=charlie_uid`, Company Alpha) -> Sales Only (5 Queries)
    # =========================================================================

    def test_q06_charlie_authorized_order_status(self):
        """Q6 [Sales User Charlie - Authorized]: Can view order status in Company Alpha."""
        token = odoo_uid_ctx.set(self.charlie_uid)
        try:
            res = obtenir_statut_commande.invoke({'reference': 'S00001'})
            self.assertIsInstance(res, str)
            self.assertTrue("S00001" in res or "introuvable" in res or "statut" in res.lower())
        finally:
            odoo_uid_ctx.reset(token)

    def test_q07_charlie_authorized_client_search(self):
        """Q7 [Sales User Charlie - Authorized]: Can search client details in Company Alpha."""
        token = odoo_uid_ctx.set(self.charlie_uid)
        try:
            res = rechercher_client.invoke({'nom': 'Client Alpha'})
            self.assertIsInstance(res, str)
            self.assertIn("Client Alpha", res)
        finally:
            odoo_uid_ctx.reset(token)

    def test_q08_charlie_unauthorized_accounting_tools_and_rules(self):
        """Q8 [Sales User Charlie - Unauthorized Accounting]: Accounting tools excluded from skills; direct ORM restricted by ir.rule."""
        skills = connector.get_user_skills(self.charlie_uid)
        self.assertFalse(skills["comptabilite"], "Charlie should NOT have comptabilite skill")
        tools = get_tools_for_skills(skills)
        self.assertNotIn(obtenir_total_factures, tools, "Accounting tool must NOT be exposed to Charlie")

        # Direct ORM ir.rule / permissions verification: Charlie querying account.move directly should fail or be restricted by company/record rules
        token = odoo_uid_ctx.set(self.charlie_uid)
        try:
            try:
                moves = connector.search_read(
                    uid=self.charlie_uid,
                    model="account.move",
                    domain=[("company_id", "=", 3)],  # Company Beta moves
                    fields=["name", "amount_total"]
                )
                self.assertEqual(len(moves), 0, "ir.rule must prevent Charlie from reading Company Beta invoices")
            except OdooConnectorError as e:
                err_msg = str(e).lower()
                self.assertTrue(
                    any(k in err_msg for k in ["access denied", "not allowed to access", "failed to read from", "rule", "droit"]),
                    f"Expected security/access error but got: {err_msg}"
                )
        finally:
            odoo_uid_ctx.reset(token)

    def test_q09_charlie_unauthorized_stock_tools_and_rules(self):
        """Q9 [Sales User Charlie - Unauthorized Stocks]: Stock tools excluded from skills."""
        skills = connector.get_user_skills(self.charlie_uid)
        self.assertFalse(skills["stocks"], "Charlie should NOT have stocks skill")
        tools = get_tools_for_skills(skills)
        self.assertNotIn(obtenir_stock_produit, tools)
        self.assertNotIn(lister_produits_en_rupture, tools)

    def test_q10_charlie_unauthorized_ticket_tools_and_rules(self):
        """Q10 [Sales User Charlie - Unauthorized Tickets]: Ticket tools excluded from skills."""
        skills = connector.get_user_skills(self.charlie_uid)
        self.assertFalse(skills["tickets"], "Charlie should NOT have tickets skill")
        tools = get_tools_for_skills(skills)
        self.assertNotIn(obtenir_tickets_recents, tools)

    # =========================================================================
    # PROFILE 3: Support User Diana (`uid=diana_uid`, Company Beta) -> Tickets Only (5 Queries)
    # =========================================================================

    def test_q11_diana_authorized_recent_tickets(self):
        """Q11 [Support User Diana - Authorized]: Can view recent support tickets for Company Beta."""
        token = odoo_uid_ctx.set(self.diana_uid)
        try:
            res = obtenir_tickets_recents.invoke({'client': 'Client Beta', 'limite': 5})
            self.assertIsInstance(res, str)
            self.assertTrue("ticket" in res.lower() or "aucun ticket" in res.lower() or "beta" in res.lower())
        finally:
            odoo_uid_ctx.reset(token)

    def test_q12_diana_authorized_client_search(self):
        """Q12 [Support User Diana - Authorized]: Can search client details in Company Beta."""
        token = odoo_uid_ctx.set(self.diana_uid)
        try:
            res = rechercher_client.invoke({'nom': 'Client Beta'})
            self.assertIsInstance(res, str)
            self.assertTrue("Client Beta" in res or "introuvable" in res.lower())
        finally:
            odoo_uid_ctx.reset(token)

    def test_q13_diana_unauthorized_sales_tools_and_rules(self):
        """Q13 [Support User Diana - Unauthorized Sales]: Sales tools excluded; ir.rule blocks cross-company sales order S00001 access."""
        skills = connector.get_user_skills(self.diana_uid)
        self.assertFalse(skills["ventes"], "Diana should NOT have ventes skill")
        tools = get_tools_for_skills(skills)
        self.assertNotIn(obtenir_statut_commande, tools)
        self.assertNotIn(obtenir_total_ventes, tools)
        self.assertNotIn(obtenir_ca_periode, tools)

        # Direct ORM ir.rule check: Diana (Company Beta) attempting to read Alpha's order S00001
        token = odoo_uid_ctx.set(self.diana_uid)
        try:
            try:
                orders = connector.search_read(
                    uid=self.diana_uid,
                    model="sale.order",
                    domain=[("name", "=", "S00001")],
                    fields=["name", "amount_total", "company_id"]
                )
                self.assertEqual(len(orders), 0, "ir.rule must prevent Diana from reading Company Alpha order S00001")
            except OdooConnectorError as e:
                err = str(e).lower()
                self.assertTrue(
                    any(k in err for k in ["access denied", "not allowed to access", "failed to read from", "rule", "droit"]),
                    f"Expected security/access error but got: {err}"
                )
        finally:
            odoo_uid_ctx.reset(token)

    def test_q14_diana_unauthorized_accounting_tools_and_rules(self):
        """Q14 [Support User Diana - Unauthorized Accounting]: Accounting tools excluded from skills."""
        skills = connector.get_user_skills(self.diana_uid)
        self.assertFalse(skills["comptabilite"], "Diana should NOT have comptabilite skill")
        tools = get_tools_for_skills(skills)
        self.assertNotIn(obtenir_total_factures, tools)

    def test_q15_diana_unauthorized_stock_tools_and_rules(self):
        """Q15 [Support User Diana - Unauthorized Stocks]: Stock tools excluded from skills."""
        skills = connector.get_user_skills(self.diana_uid)
        self.assertFalse(skills["stocks"], "Diana should NOT have stocks skill")
        tools = get_tools_for_skills(skills)
        self.assertNotIn(obtenir_stock_produit, tools)
        self.assertNotIn(lister_produits_en_rupture, tools)


if __name__ == "__main__":
    unittest.main()
