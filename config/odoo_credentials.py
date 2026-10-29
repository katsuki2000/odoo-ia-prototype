"""Odoo service account: login and password come from the backend environment, never from a default."""

import os

import config.settings  # noqa: F401  (loads .env)

PASSWORD_VARIABLE = "ODOO_ADMIN_PASSWORD"
LOGIN_VARIABLE = "ODOO_ADMIN_LOGIN"
DEFAULT_LOGIN = "admin"


class MissingServiceCredentialError(RuntimeError):
    """Raised when the Odoo service account password is not configured."""


def service_login() -> str:
    return os.getenv(LOGIN_VARIABLE) or DEFAULT_LOGIN


def service_password() -> str:
    value = os.getenv(PASSWORD_VARIABLE)
    if value:
        return value
    raise MissingServiceCredentialError(
        "The Odoo service account password is not configured: set ODOO_ADMIN_PASSWORD in the backend .env "
        "(never in the Odoo interface)."
    )


__all__ = ["MissingServiceCredentialError", "service_login", "service_password"]
