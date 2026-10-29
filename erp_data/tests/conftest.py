import os

import pytest

from config.settings import ODOO_DB
from erp_data.odoo_connector import OdooConnector
from erp_data.odoo_context import request_identity


@pytest.fixture
def admin_requester_identity():
    """Run a test as the Odoo admin account, the way a request carrying a signed identity would."""
    password = os.getenv("ODOO_ADMIN_PASSWORD", "admin")
    connector = OdooConnector(
        url=os.getenv("ODOO_URL", "http://localhost:8069"),
        db=ODOO_DB,
        password=password,
    )
    uid = connector.authenticate(connector.username)
    with request_identity(uid, password, db=ODOO_DB):
        yield uid
