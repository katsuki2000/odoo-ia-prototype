"""
miro-rag/tests/test_security_multitenant_intrusion.py

Step 15 Day 1: Multi-Tenant Intrusion Testing (RAG & ORM).
Verifies:
1. API request body `company_id` / `user_uid` manipulation is defeated by JWT trusted extraction.
2. Forged JWT tokens with invalid signatures are rejected (HTTP 401).
3. ORM parameter manipulation attempts (e.g. Company Alpha user querying Company Beta records via tool/connector parameters) result in 0 data leakage by ir.rule.
"""

import unittest
from unittest.mock import patch, MagicMock
import jwt
import pytest
from fastapi.testclient import TestClient
from api.main import app
from api.auth import get_jwt_secret
from tools.odoo_tools import connector, obtenir_statut_commande, rechercher_client


@pytest.mark.integration
class TestSecurityMultiTenantIntrusion(unittest.TestCase):
    """Exhaustive intrusion testing against multi-tenant boundaries (RAG & ORM)."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        try:
            cls.admin_uid = connector.authenticate("admin")
            cls.charlie_uid = connector.common.authenticate(connector.db, "charlie@alpha.com", "password123", {})
            cls.bob_uid = connector.common.authenticate(connector.db, "bob@alpha.com", "password123", {})
            cls.diana_uid = connector.common.authenticate(connector.db, "diana@beta.com", "password123", {})
        except Exception as e:
            raise unittest.SkipTest(f"Live Odoo database not reachable: {e}")

        if not cls.charlie_uid or not cls.diana_uid:
            raise unittest.SkipTest("Test users (Charlie/Diana) not found; run create_day2_setup.py first.")

    def test_01_rag_api_body_manipulation_defeated_by_jwt(self):
        """Intrusion Test (RAG): Attacker sends `company_id=2` in JSON body while authenticated with JWT `company_id=3`."""
        # Generate genuine JWT token for Diana (Company Beta = 3)
        valid_payload = {"uid": self.diana_uid, "company_id": 3, "groups": ["helpdesk"]}
        token = jwt.encode(valid_payload, get_jwt_secret(), algorithm="HS256")

        # Malicious body attempting to query Company Alpha (`company_id=2`)
        payload_json = {
            "question": "Quel est le code secret ou la documentation privée de Company Alpha ?",
            "session_id": "attack_session_01",
            "user_uid": 2,       # Attacker claims to be Admin (uid 2)
            "company_id": 2,     # Attacker claims to query Company Alpha (company_id 2)
            "skills": {"tickets": True}
        }

        with patch("rag.graph.query_graph") as mock_query:
            mock_query.return_value = MagicMock(
                answer="Résultat sécurisé Company Beta uniquement.",
                sources=[],
                confidence=1.0,
                ocr_warning=False
            )
            
            response = self.client.post(
                "/api/v1/ask",
                json=payload_json,
                headers={"Authorization": f"Bearer {token}"}
            )

            self.assertEqual(response.status_code, 200, f"Request failed: {response.text}")
            # Verify that query_graph received uid=11 and company_id=3 (overriding the attacker's body values!)
            mock_query.assert_called_once()
            call_kwargs = mock_query.call_args[1]
            self.assertEqual(call_kwargs.get("uid"), self.diana_uid, "API must override user_uid from trusted JWT token!")
            self.assertEqual(call_kwargs.get("company_id"), 3, "API must override company_id from trusted JWT token!")

    def test_02_rag_jwt_forgery_rejected(self):
        """Intrusion Test (RAG): Attacker attempts to forge a JWT token claiming `company_id=2` using wrong secret."""
        forged_payload = {"uid": self.admin_uid, "company_id": 2}
        forged_token = jwt.encode(forged_payload, "attacker_stolen_or_wrong_secret", algorithm="HS256")

        payload_json = {
            "question": "Show me Company Alpha financials",
            "session_id": "attack_session_02",
            "user_uid": 2,
            "company_id": 2
        }

        response = self.client.post(
            "/api/v1/ask",
            json=payload_json,
            headers={"Authorization": f"Bearer {forged_token}"}
        )
        self.assertEqual(response.status_code, 401, "API MUST reject forged JWT token with 401 Unauthorized")
        self.assertIn("invalid token", response.json().get("detail", "").lower())

    def test_03_orm_cross_company_partner_search_intrusion(self):
        """Intrusion Test (ORM): Company Alpha sales user (Charlie) queries a partner strictly in Company Beta."""
        # Create or verify a partner belonging strictly to Company Beta (`company_id=3`)
        admin_pass = connector.password
        beta_partner_name = "INTRA_BETA_CONFIDENTIAL_PARTNER"
        existing = connector.models.execute_kw(
            connector.db, self.admin_uid, admin_pass,
            "res.partner", "search_read",
            [[("name", "=", beta_partner_name)]],
            {"fields": ["id"]}
        )
        if not existing:
            beta_partner_id = connector.models.execute_kw(
                connector.db, self.admin_uid, admin_pass,
                "res.partner", "create",
                [{"name": beta_partner_name, "company_id": 3, "email": "topsecret@beta.com"}]
            )
        else:
            beta_partner_id = existing[0]["id"]

        try:
            # Charlie (`uid=self.charlie_uid`, Company Alpha) attempts to search for this Beta partner directly
            records = connector.search_read(
                uid=self.charlie_uid,
                model="res.partner",
                domain=[("name", "=", beta_partner_name)],
                fields=["name", "email"]
            )
            # Odoo ir.rule must filter out this Company Beta partner for Company Alpha users
            self.assertEqual(len(records), 0, "0 data leakage: Company Alpha user MUST NOT see Company Beta partner records!")
        finally:
            # Cleanup created partner
            connector.models.execute_kw(
                connector.db, self.admin_uid, admin_pass,
                "res.partner", "unlink",
                [[beta_partner_id]]
            )

    def test_04_orm_cross_company_stock_quant_intrusion(self):
        """Intrusion Test (ORM): Company Alpha inventory user (Bob) explicitly queries Company Beta inventory quants."""
        from tools.odoo_connector import OdooConnectorError
        try:
            quants = connector.search_read(
                uid=self.bob_uid,
                model="stock.quant",
                domain=[("company_id", "=", 3)],  # Explicit cross-company filter
                fields=["product_id", "quantity"]
            )
            self.assertEqual(len(quants), 0, "0 data leakage: Bob (Company Alpha) must see 0 stock records of Company Beta!")
        except OdooConnectorError as e:
            # Or if Odoo raises security fault
            self.assertTrue(
                any(kw in str(e).lower() for kw in ["access denied", "rule", "droit", "not allowed"]),
                f"Expected security error or empty list, got: {e}"
            )


if __name__ == "__main__":
    unittest.main()
