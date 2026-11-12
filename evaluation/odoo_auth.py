"""Authentication of the Odoo account used by the evaluation scripts."""

from config import settings
from erp_data.connector.odoo_connector import OdooConnector
from evaluation.preflight import BackendUnavailable


def authenticate_odoo(login, password):
    connector = OdooConnector(db=settings.ODOO_DB, password=password)
    uid = connector.common.authenticate(connector.db, login, password, {})
    if not uid:
        raise BackendUnavailable(f"Odoo authentication failed for {login}.")
    return uid
