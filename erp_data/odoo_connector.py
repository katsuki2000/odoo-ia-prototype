"""
Odoo XML-RPC connection manager for the AI.
Provides read-only ORM access under the requester's identity.
"""

import logging
import re
import time
import xmlrpc.client

from config import settings
from config.odoo_credentials import service_login, service_password
from erp_data.odoo_context import odoo_api_key_ctx, odoo_company_id_ctx, odoo_company_ids_ctx, odoo_db_ctx

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

TECHNICAL_ONLY_MODELS = frozenset({
    "ir.model.data",
    "ir.module.category",
    "res.groups",
})


class OdooConnectorError(Exception):
    """Custom exception for Odoo connection or enforcement errors."""
    pass


class OdooConnector:
    """Manages secure XML-RPC connections to Odoo."""

    def __init__(self, url: str = None, db: str = None, password: str = None, technical: bool = False):
        """
        Initialize the connector. Credentials can be passed directly or come from config/settings.py.
        Note: We do not store uid here because each query must pass the requesting user's uid.
        The password used here is the application token or user password for the XML-RPC connection.
        Without an explicit password the service account password is read from the environment
        when it is first needed; there is no default (see config/odoo_credentials.py).

        A technical connector reads instance metadata (installed modules, languages,
        registry labels) with the configured service account and ignores the per-request
        API key, so the uid and the password always belong to the same identity.
        """
        self.url = url or settings.ODOO_URL
        self._db = db
        self.username = service_login()
        self._password = password
        self.technical = technical
        if technical:
            logger.info("OdooConnector opened in technical mode as '%s' (instance metadata only).", self.username)

        self.common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    @property
    def db(self) -> str:
        """Explicit database, else the one signed into the request JWT; never a configured fallback."""
        db = self._db or odoo_db_ctx.get()
        if not db:
            raise OdooConnectorError("No Odoo database: the request JWT carries none and none was given to the connector.")
        return db

    @property
    def password(self) -> str:
        return self._password or service_password()

    @password.setter
    def password(self, value: str) -> None:
        self._password = value

    def _resolve_password(self) -> str:
        """
        Return the credential matching the identity of this call.

        A technical connector uses its service password. Any other connector
        uses the per-request API key set by query_graph() from the key signed
        into the JWT by the Odoo controller (res.users.apikeys), so Odoo's own
        ir.rule / ACL enforcement applies to the requesting user. Without that
        key the call is refused: falling back to the admin password would run
        it as admin whoever the token claims to be.
        """
        if self.technical:
            return self.password
        ctx_key = odoo_api_key_ctx.get()
        if ctx_key is not None:
            return ctx_key
        raise OdooConnectorError(
            "No per-request Odoo API key in context: refusing to run this call with the service credential."
        )

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
        """Apply optional deployment restrictions before Odoo's own access checks."""
        if not _MODEL_NAME_RE.fullmatch(model):
            raise OdooConnectorError(f"Model {model} is not a valid Odoo model name.")
        if self.technical and model in TECHNICAL_ONLY_MODELS:
            return
        if settings.ODOO_ALLOWED_MODELS and model not in settings.ODOO_ALLOWED_MODELS:
            raise OdooConnectorError(f"Model {model} is not allowed by ODOO_ALLOWED_MODELS.")

    def _session_orm_context(self) -> dict:
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
            {"attributes": ["string", "type", "help", "relation", "selection", "required", "readonly", "store"]},
        )
