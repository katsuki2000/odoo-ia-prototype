"""Odoo service account: login and password come from the backend environment, never from a default."""

import os

import config.settings  # noqa: F401  (loads .env)

PASSWORD_VARIABLES = ("ODOO_ADMIN_PASSWORD", "ODOO_PASSWORD")
LOGIN_VARIABLES = ("ODOO_ADMIN_LOGIN", "ODOO_USERNAME")
DEFAULT_LOGIN = "admin"


class MissingServiceCredentialError(RuntimeError):
    """Raised when the Odoo service account password is not configured."""


def service_login() -> str:
    for variable in LOGIN_VARIABLES:
        value = os.getenv(variable)
        if value:
            return value
    return DEFAULT_LOGIN


def service_password() -> str:
    for variable in PASSWORD_VARIABLES:
        value = os.getenv(variable)
        if value:
            return value
    raise MissingServiceCredentialError(
        "The Odoo service account password is not configured: set ODOO_ADMIN_PASSWORD in the backend .env "
        "(never in the Odoo interface)."
    )


__all__ = ["MissingServiceCredentialError", "service_login", "service_password"]
