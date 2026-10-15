import os

import pytest

from erp_data.odoo_connector import OdooConnector
from erp_data.odoo_context import odoo_api_key_ctx, odoo_uid_ctx


@pytest.fixture
def admin_requester_identity():
    """Run a test as the Odoo admin account, the way a request carrying a signed identity would."""
    password = os.getenv("ODOO_PASSWORD", "admin")
    connector = OdooConnector(
        url=os.getenv("ODOO_URL", "http://localhost:8069"),
        db=os.getenv("ODOO_DB", "odoo-dev"),
        password=password,
    )
    uid = connector.authenticate(connector.username)
    key_token = odoo_api_key_ctx.set(password)
    uid_token = odoo_uid_ctx.set(uid)
    try:
        yield uid
    finally:
        odoo_uid_ctx.reset(uid_token)
        odoo_api_key_ctx.reset(key_token)
