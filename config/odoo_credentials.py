"""Odoo service account: login and password come from the backend environment, never from a default."""

from config import settings


class MissingServiceCredentialError(RuntimeError):
    """Raised when the Odoo service account password is not configured."""


def service_login() -> str:
    return settings.ODOO_ADMIN_LOGIN


def service_password() -> str:
    if settings.ODOO_ADMIN_PASSWORD:
        return settings.ODOO_ADMIN_PASSWORD
    raise MissingServiceCredentialError(
        "The Odoo service account password is not configured: set ODOO_ADMIN_PASSWORD in the backend .env "
        "(never in the Odoo interface)."
    )


__all__ = ["MissingServiceCredentialError", "service_login", "service_password"]
