"""
Small XML-RPC client used by J5 live security validation tests.

The methods intentionally mirror the Odoo security operations under test:
authenticate a real user, check ACLs through check_access_rights, then query
records as that same user so ir.rule filtering is evaluated by Odoo itself.
"""

from __future__ import annotations

import os
import xmlrpc.client
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


VALID_OPERATIONS = {"read", "write", "create", "unlink"}


class OdooRpcError(RuntimeError):
    """Raised for local client misuse before an XML-RPC call is made."""


@dataclass
class OdooRpcClient:
    url: str = field(default_factory=lambda: os.getenv("ODOO_URL", "http://localhost:8069"))
    db: str = field(default_factory=lambda: os.getenv("ODOO_DB", "odoo-dev"))
    admin_login: str = field(default_factory=lambda: os.getenv("ODOO_ADMIN_LOGIN", "admin"))
    admin_password: str = field(default_factory=lambda: os.getenv("ODOO_ADMIN_PASSWORD", "admin"))

    def __post_init__(self) -> None:
        self.common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)
        self._password_by_uid: Dict[int, str] = {}

    def authenticate_user(self, login: str, password: str) -> int:
        uid = self.common.authenticate(self.db, login, password, {})
        if not uid:
            raise OdooRpcError(f"Authentication failed for Odoo user '{login}'.")
        self._password_by_uid[int(uid)] = password
        return int(uid)

    def authenticate_admin(self) -> int:
        return self.authenticate_user(self.admin_login, self.admin_password)

    def execute_kw(
        self,
        uid: int,
        model_name: str,
        method: str,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> Any:
        password = self._password_by_uid.get(uid)
        if password is None:
            raise OdooRpcError(
                f"No password cached for uid {uid}; call authenticate_user() for that user first."
            )
        return self.models.execute_kw(
            self.db,
            uid,
            password,
            model_name,
            method,
            args or [],
            kwargs or {},
        )

    def check_access_rights(self, uid: int, model_name: str, operation: str = "read") -> bool:
        self._validate_operation(operation)
        return bool(
            self.execute_kw(
                uid,
                model_name,
                "check_access_rights",
                [operation],
                {"raise_exception": True},
            )
        )

    def search_as_user(
        self,
        uid: int,
        model_name: str,
        domain: List[Any],
        operation: str = "read",
        limit: Optional[int] = None,
    ) -> List[int]:
        self._validate_operation(operation)
        self.check_access_rights(uid, model_name, operation)
        kwargs: Dict[str, Any] = {}
        if limit is not None:
            kwargs["limit"] = limit
        record_ids = list(self.execute_kw(uid, model_name, "search", [domain], kwargs))
        if operation != "read" and record_ids:
            self.check_access_rule(uid, model_name, record_ids, operation)
        return record_ids

    def check_access_rule(
        self,
        uid: int,
        model_name: str,
        record_ids: List[int],
        operation: str = "read",
    ) -> bool:
        self._validate_operation(operation)
        if not record_ids:
            return True
        try:
            result = self.execute_kw(
                uid,
                model_name,
                "check_access_rule",
                [record_ids, operation],
            )
        except xmlrpc.client.Fault as exc:
            # Odoo's check_access_rule returns None on success. The XML-RPC
            # endpoint is configured with allow_none=False and therefore raises
            # this marshalling fault after the server-side security check has
            # already passed. Real AccessError faults do not contain this text.
            if "cannot marshal None" in exc.faultString:
                return True
            raise
        return bool(result) if result is not None else True

    def set_user_password(self, admin_uid: int, login: str, password: str) -> int:
        user_ids = self.execute_kw(admin_uid, "res.users", "search", [[("login", "=", login)]], {"limit": 1})
        if not user_ids:
            raise OdooRpcError(f"Required Odoo test user '{login}' does not exist.")
        self.execute_kw(admin_uid, "res.users", "write", [user_ids, {"password": password}])
        return int(user_ids[0])

    @staticmethod
    def _validate_operation(operation: str) -> None:
        if operation not in VALID_OPERATIONS:
            raise ValueError(
                f"Unsupported Odoo access operation '{operation}'. "
                f"Expected one of {sorted(VALID_OPERATIONS)}."
            )
