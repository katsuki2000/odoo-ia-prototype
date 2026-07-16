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
        self.url = url or os.getenv("ODOO_URL", "http://localhost:8069")
        self.db = db or os.getenv("ODOO_DB", "odoo-dev")
        self.password = password or os.getenv("ODOO_PASSWORD", "admin")

        self.common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def _resolve_password(self) -> str:
        """Return the per-request API key/password if set via ContextVar, else fall back to instance default."""
        from tools.odoo_tools import odoo_api_key_ctx
        ctx_key = odoo_api_key_ctx.get()
        if ctx_key is not None:
            return ctx_key
        return self.password

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
                self.db, uid, self._resolve_password(),
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
                self.db, uid, self._resolve_password(),
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
                self.db, uid, self._resolve_password(),
                model, 'fields_get',
                [],
                {'attributes': ['string', 'type', 'help']}
            )
            return fields_info
        except Exception as e:
            logger.error("XML-RPC fields_get error on %s: %s", model, str(e))
            raise OdooConnectorError(f"Failed to fetch fields for {model}: {str(e)}")
