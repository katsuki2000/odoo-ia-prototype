"""
Odoo XML-RPC connection manager for the AI.
Enforces model whitelisting and read-only operations for secure data retrieval.
"""

import os
import time
import xmlrpc.client
import logging

logger = logging.getLogger(__name__)

ALLOWED_MODELS = {
    "sale.order",
    "sale.order.line",
    "account.move",
    "stock.quant",
    "project.task",
    "res.partner",
    "product.product",
    "ir.module.module",
    "res.company",  # todo/contexte.txt section 536: read-only, whitelisted with
    # explicit maitre de stage sign-off, solely to let search_partner_raw
    # exclude self-company res.partner records (e.g. "Company Alpha") from
    # client search results -- never exposed as a directly queryable tool.
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
        self.password = password or os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_ADMIN_PASSWORD", "admin")

        self.common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def _resolve_password(self) -> str:
        """
        Return the per-request API key/password if set via ContextVar, else
        fall back to the instance default (admin) password.

        The ContextVar is set by query_graph() from the `api_key` it receives
        -- on a real API request that is the real per-user Odoo API key
        signed into the JWT by the Odoo controller (request.env['res.users.
        apikeys']._generate(), see miro_ai/controllers/main.py), so calls
        genuinely execute as that specific user and Odoo's own ir.rule / ACL
        enforcement applies to them. Falling through to the admin password
        means every call runs as admin regardless of who asked -- exactly the
        auth mock this was meant to remove -- so it's logged loudly instead
        of happening silently.
        """
        from erp_data._odoo_helpers import odoo_api_key_ctx
        ctx_key = odoo_api_key_ctx.get()
        if ctx_key is not None:
            return ctx_key
        logger.warning(
            "OdooConnector._resolve_password(): no per-request API key in "
            "context -- falling back to the admin password. Expected in "
            "tests/scripts; on a real API request it means the JWT api_key "
            "was missing or not propagated."
        )
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

    def search_read(self, uid: int, model: str, domain: list = None, fields: list = None, limit: int = 0, order: str = None, **extra_kwargs) -> list[dict]:
        """
        Execute a search_read query safely.
        Must use the requesting user's uid.
        """
        self._check_whitelist(model)
        domain = domain if domain is not None else []
        fields = fields if fields is not None else []
        
        kwargs = {'fields': fields}
        if limit > 0:
            kwargs['limit'] = limit
        if order:
            kwargs['order'] = order
        kwargs.update(extra_kwargs)
            
        try:
            t0 = time.perf_counter()
            records = self.models.execute_kw(
                self.db, uid, self._resolve_password(),
                model, 'search_read',
                [domain],
                kwargs
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info("XML-RPC %.1fms: %s.%s", elapsed_ms, model, 'search_read')
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
            t0 = time.perf_counter()
            records = self.models.execute_kw(
                self.db, uid, self._resolve_password(),
                model, 'read_group',
                [domain, fields, groupby]
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info("XML-RPC %.1fms: %s.%s", elapsed_ms, model, 'read_group')
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
            t0 = time.perf_counter()
            fields_info = self.models.execute_kw(
                self.db, uid, self._resolve_password(),
                model, 'fields_get',
                [],
                {'attributes': ['string', 'type', 'help']}
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info("XML-RPC %.1fms: %s.%s", elapsed_ms, model, 'fields_get')
            return fields_info
        except Exception as e:
            logger.error("XML-RPC fields_get error on %s: %s", model, str(e))
            raise OdooConnectorError(f"Failed to fetch fields for {model}: {str(e)}")
