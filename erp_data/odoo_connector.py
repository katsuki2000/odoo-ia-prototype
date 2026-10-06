"""
Odoo XML-RPC connection manager for the AI.
Enforces model whitelisting and read-only operations for secure data retrieval.
"""

import logging
import os
import re
import time
import xmlrpc.client

logger = logging.getLogger(__name__)

_MODEL_NAME_RE = re.compile(r"^[a-z][a-z0-9_.]*$")

_METHOD_FAILURE_PREFIX = {
    "search_read": "Failed to read from",
    "search": "Failed to search",
    "read": "Failed to read from",
    "search_count": "Failed to count",
    "name_search": "Failed to name_search",
    "read_group": "Failed to aggregate on",
    "fields_get": "Failed to fetch fields for",
}

DEFAULT_ALLOWED_MODELS = {
    "sale.order",
    "sale.order.line",
    "account.move",
    "stock.quant",
    "project.task",
    "res.partner",
    "product.product",
    "ir.module.module",
    "ir.model",
    "ir.model.fields",
    "res.lang",
    "res.company",  # todo/contexte.txt section 536: read-only, whitelisted with
    # explicit maitre de stage sign-off, solely to let search_partner_raw
    # exclude self-company res.partner records (e.g. "Company Alpha") from
    # client search results -- never exposed as a directly queryable tool.
}

ALLOWED_MODELS = DEFAULT_ALLOWED_MODELS


def resolve_allowed_models():
    """Return (allowed_set, wildcard). wildcard=True skips the static set."""
    raw = os.getenv("ODOO_ALLOWED_MODELS")
    if raw is None or not str(raw).strip():
        return frozenset(DEFAULT_ALLOWED_MODELS), False
    text = str(raw).strip()
    if text == "*":
        return frozenset(), True
    return frozenset(part.strip() for part in text.split(",") if part.strip()), False


class OdooConnectorError(Exception):
    """Custom exception for Odoo connection or enforcement errors."""
    pass


class OdooConnector:
    """Manages secure XML-RPC connections to Odoo."""

    def __init__(self, url: str = None, db: str = None, password: str = None, technical: bool = False):
        """
        Initialize the connector. Credentials can be passed directly or read from env.
        Note: We do not store uid here because each query must pass the requesting user's uid.
        The password used here is the application token or user password for the XML-RPC connection.
        In this prototype, we use the default admin password if not provided.

        A technical connector reads instance metadata (installed modules, languages,
        registry labels) with the configured service account and ignores the per-request
        API key, so the uid and the password always belong to the same identity.
        """
        self.url = url or os.getenv("ODOO_URL", "http://localhost:8069")
        self.db = db or os.getenv("ODOO_DB", "odoo-dev")
        self.username = os.getenv("ODOO_USERNAME", "admin")
        self.password = password or os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_ADMIN_PASSWORD", "admin")
        self.technical = technical
        if technical:
            logger.info("OdooConnector opened in technical mode as '%s' (instance metadata only).", self.username)

        self.common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        self._allowed_models, self._wildcard_models = resolve_allowed_models()

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
        if self.technical:
            return self.password
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
        if self._wildcard_models:
            if not _MODEL_NAME_RE.match(model):
                logger.warning("Attempted access with invalid model name: %s", model)
                raise OdooConnectorError(f"Model {model} is not a valid Odoo model name.")
            return
        if model not in self._allowed_models:
            logger.warning("Attempted access to non-whitelisted model: %s", model)
            raise OdooConnectorError(f"Model {model} is not whitelisted for AI queries.")

    def _session_orm_context(self) -> dict:
        from erp_data.odoo_context import odoo_company_id_ctx, odoo_company_ids_ctx

        company_id = odoo_company_id_ctx.get()
        company_ids = odoo_company_ids_ctx.get()
        ctx: dict = {}
        if company_ids:
            ctx["allowed_company_ids"] = [int(x) for x in company_ids]
        if company_id is not None:
            ctx["force_company"] = int(company_id)
            ctx.setdefault("allowed_company_ids", [int(company_id)])
        return ctx

    def _execute_kw(self, uid: int, model: str, method: str, args: list, kwargs: dict | None = None):
        self._check_whitelist(model)
        kwargs = dict(kwargs or {})
        session_ctx = self._session_orm_context()
        if session_ctx:
            merged = dict(kwargs.get("context") or {})
            merged.update(session_ctx)
            kwargs["context"] = merged
        try:
            t0 = time.perf_counter()
            result = self.models.execute_kw(
                self.db, uid, self._resolve_password(),
                model, method, args, kwargs,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info("XML-RPC %.1fms: %s.%s", elapsed_ms, model, method)
            return result
        except OdooConnectorError:
            raise
        except Exception as e:
            logger.error("XML-RPC %s error on %s: %s", method, model, str(e))
            prefix = _METHOD_FAILURE_PREFIX.get(method, f"Failed {method} on")
            raise OdooConnectorError(f"{prefix} {model}: {str(e)}")

    def search_read(self, uid: int, model: str, domain: list = None, fields: list = None, limit: int = 0, order: str = None, **extra_kwargs) -> list[dict]:
        """
        Execute a search_read query safely.
        Must use the requesting user's uid.
        """
        domain = domain if domain is not None else []
        fields = fields if fields is not None else []

        kwargs = {"fields": fields}
        if limit > 0:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        kwargs.update(extra_kwargs)
        return self._execute_kw(uid, model, "search_read", [domain], kwargs)

    def search(
        self,
        uid: int,
        model: str,
        domain: list | None = None,
        limit: int = 0,
        order: str | None = None,
        offset: int = 0,
    ) -> list[int]:
        domain = domain if domain is not None else []
        kwargs: dict = {}
        if limit > 0:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        if offset > 0:
            kwargs["offset"] = offset
        return self._execute_kw(uid, model, "search", [domain], kwargs)

    def read(self, uid: int, model: str, ids: list[int], fields: list | None = None) -> list[dict]:
        fields = fields if fields is not None else []
        return self._execute_kw(uid, model, "read", [ids], {"fields": fields})

    def search_count(self, uid: int, model: str, domain: list | None = None) -> int:
        domain = domain if domain is not None else []
        return int(self._execute_kw(uid, model, "search_count", [domain], {}))

    def name_search(
        self,
        uid: int,
        model: str,
        name: str = "",
        domain: list | None = None,
        operator: str = "ilike",
        limit: int = 0,
    ) -> list:
        domain = domain if domain is not None else []
        kwargs: dict = {"args": domain, "operator": operator}
        if limit > 0:
            kwargs["limit"] = limit
        return self._execute_kw(uid, model, "name_search", [name or ""], kwargs)

    def read_group(self, uid: int, model: str, domain: list, fields: list, groupby: list, **extra_kwargs) -> list[dict]:
        """
        Execute a read_group query for aggregations. Pass lazy=False to group
        by every field of `groupby` at once instead of the first one only.
        """
        return self._execute_kw(
            uid, model, "read_group", [domain, fields, groupby], extra_kwargs or {}
        )

    def fields_get(self, uid: int, model: str) -> dict:
        """
        Retrieve schema information for a model.
        """
        return self._execute_kw(
            uid,
            model,
            "fields_get",
            [],
            {"attributes": ["string", "type", "help"]},
        )
