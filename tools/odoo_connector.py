"""Backward-compatibility facade re-exporting OdooConnector."""

from erp_data.odoo_connector import OdooConnector, OdooConnectorError

__all__ = ["OdooConnector", "OdooConnectorError"]
