import pytest

from config.settings import ODOO_DB
from config.odoo_credentials import service_password
from erp_data.connector.odoo_connector import OdooConnector
from erp_data.connector.odoo_context import request_identity
from erp_data.tools import read_tools


@pytest.fixture
def admin_requester_identity():
    """Run a test as the Odoo admin account, the way a request carrying a signed identity would."""
    password = service_password()
    connector = OdooConnector(db=ODOO_DB, password=password)
    uid = connector.authenticate(connector.username)
    with request_identity(uid, password, db=ODOO_DB):
        yield uid


@pytest.fixture(autouse=True)
def _reset_connector():
    read_tools._connector = None
    read_tools._field_cache.clear()
    yield
    read_tools._connector = None
    read_tools._field_cache.clear()
