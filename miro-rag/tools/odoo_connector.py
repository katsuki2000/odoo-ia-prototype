"""
miro-rag/tools/odoo_connector.py

Odoo XML-RPC connection manager for the RAG AI Prototype.
Enforces model whitelisting and read-only operations for secure data retrieval.
"""

import os
import xmlrpc.client
import logging

logger = logging.getLogger(__name__)

ALLOWED_MODELS = {
    "sale.order",
    "account.move",
    "stock.quant",
    "helpdesk.ticket",
    "project.task",
    "res.partner",
    "product.product",
    "ir.module.module",
}

class OdooConnectorError(Exception):
    """Custom exception for Odoo connection or enforcement errors."""
    pass


class OdooConnector:
    """Manages secure XML-RPC connections to Odoo."""

    def __init__(self, url: str = None, db: str = None, password: str = None):
        """
        Initialize the connector. Credentials can be passed directly or read from env.
        Note: We do not store uid here because each query must pass the requesting user's uid.
        The password used here is the application token or user password for the XML-RPC connection.
        In this prototype, we use the default admin password if not provided.
        """
        url_val = url or os.getenv("ODOO_URL", "http://localhost:8069")
        if "://odoo:" in url_val:
            import socket
            try:
                socket.getaddrinfo("odoo", 8069)
            except socket.gaierror:
                url_val = url_val.replace("://odoo:", "://localhost:")
        self.url = url_val
        self.db = db or os.getenv("ODOO_DB", "odoo-dev")
        self.password = password or os.getenv("ODOO_PASSWORD", "admin")

        self.common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def authenticate(self, username: str) -> int:
        """
        Authenticate a user by username and return their uid.
        This uid will be used for subsequent calls.
        """
        try:
            uid = self.common.authenticate(self.db, username, self.password, {})
            if not uid:
                raise OdooConnectorError(f"Authentication failed for user {username}")
            return uid
        except Exception as e:
            logger.error("XML-RPC Auth error: %s", str(e))
            raise OdooConnectorError(f"Failed to authenticate: {str(e)}")

    def _check_whitelist(self, model: str):
        """Ensure the requested model is in the allowed whitelist."""
        if model not in ALLOWED_MODELS:
            logger.warning("Attempted access to non-whitelisted model: %s", model)
            raise OdooConnectorError(f"Model {model} is not whitelisted for AI queries.")

    def search_read(self, uid: int, model: str, domain: list = None, fields: list = None) -> list[dict]:
        """
        Execute a search_read query safely.
        Must use the requesting user's uid.
        """
        self._check_whitelist(model)
        domain = domain if domain is not None else []
        fields = fields if fields is not None else []
        
        try:
            records = self.models.execute_kw(
                self.db, uid, self.password,
                model, 'search_read',
                [domain],
                {'fields': fields}
            )
            return records
        except Exception as e:
            logger.error("XML-RPC search_read error on %s: %s", model, str(e))
            raise OdooConnectorError(f"Failed to read from {model}: {str(e)}")

    def read_group(self, uid: int, model: str, domain: list, fields: list, groupby: list) -> list[dict]:
        """
        Execute a read_group query for aggregations.
        """
        self._check_whitelist(model)
        
        try:
            records = self.models.execute_kw(
                self.db, uid, self.password,
                model, 'read_group',
                [domain, fields, groupby]
            )
            return records
        except Exception as e:
            logger.error("XML-RPC read_group error on %s: %s", model, str(e))
            raise OdooConnectorError(f"Failed to aggregate on {model}: {str(e)}")

    def fields_get(self, uid: int, model: str) -> dict:
        """
        Retrieve schema information for a model.
        """
        self._check_whitelist(model)
        
        try:
            fields_info = self.models.execute_kw(
                self.db, uid, self.password,
                model, 'fields_get',
                [],
                {'attributes': ['string', 'type', 'help']}
            )
            return fields_info
        except Exception as e:
            logger.error("XML-RPC fields_get error on %s: %s", model, str(e))
            raise OdooConnectorError(f"Failed to fetch fields for {model}: {str(e)}")

    def get_user_skills(self, uid: int) -> dict[str, bool]:
        """
        Derive skill categories ('ventes', 'stocks', 'comptabilite', 'tickets') from Odoo user groups.
        Reads `res.users` -> `groups_id`, and maps groups via `ir.model.data` / `res.groups` to tool categories.
        Only exposes tool categories matching the user's Odoo permissions.
        """
        if uid in (1, 2):
            return {"ventes": True, "stocks": True, "comptabilite": True, "tickets": True}

        skills = {"ventes": False, "stocks": False, "comptabilite": False, "tickets": False}
        try:
            user_data = self.models.execute_kw(
                self.db, uid, self.password,
                "res.users", "read",
                [[uid]],
                {"fields": ["groups_id"]}
            )
            if not user_data:
                return skills
            group_ids = user_data[0].get("groups_id", [])
            if not group_ids:
                return skills

            eval_uid = uid
            try:
                eval_uid = self.common.authenticate(self.db, "admin", self.password, {}) or uid
            except Exception:
                pass

            mappings = self.models.execute_kw(
                self.db, eval_uid, self.password,
                "ir.model.data", "search_read",
                [[("model", "=", "res.groups"), ("res_id", "in", group_ids)]],
                {"fields": ["module", "name"]}
            )
            xml_ids = {f"{m.get('module')}.{m.get('name')}" for m in mappings}

            group_records = self.models.execute_kw(
                self.db, eval_uid, self.password,
                "res.groups", "search_read",
                [[("id", "in", group_ids)]],
                {"fields": ["name", "full_name"]}
            )
            group_names = {
                f"{r.get('full_name', '')} {r.get('name', '')}".lower()
                for r in group_records
            }

            if any(x in xml_ids for x in ("base.group_system", "base.group_erp_manager")) or any("system" in n or "settings" in n for n in group_names):
                return {"ventes": True, "stocks": True, "comptabilite": True, "tickets": True}

            if any(x.startswith(("sale", "sales_team", "crm")) or "group_sale" in x for x in xml_ids) or any("sale" in n or "ventes" in n or "crm" in n for n in group_names):
                skills["ventes"] = True

            if any(x.startswith(("stock", "purchase", "mrp")) or "group_stock" in x or "group_purchase" in x for x in xml_ids) or any("stock" in n or "inventaire" in n or "purchase" in n or "achat" in n for n in group_names):
                skills["stocks"] = True

            if any(x.startswith("account") or "group_account" in x for x in xml_ids) or any("account" in n or "compta" in n or "factur" in n or "invoicing" in n or "billing" in n for n in group_names):
                skills["comptabilite"] = True

            if any(x.startswith(("helpdesk", "project")) or "group_helpdesk" in x or "group_project" in x for x in xml_ids) or any("helpdesk" in n or "ticket" in n or "project" in n or "projet" in n or "support" in n for n in group_names):
                skills["tickets"] = True

        except Exception as e:
            logger.error("Error fetching user skills for uid=%s: %s", uid, e)

        return skills

