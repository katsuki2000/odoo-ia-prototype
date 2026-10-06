"""Request-scoped Odoo identity ContextVars.

Shared kernel: zero dependency on odoo_connector.py or _odoo_helpers.py,
which both need these vars and would otherwise import each other in a
cycle (odoo_connector needs the per-request api key, _odoo_helpers needs
OdooConnector).
"""

import contextvars

odoo_uid_ctx = contextvars.ContextVar("odoo_uid", default=None)
odoo_api_key_ctx = contextvars.ContextVar("odoo_api_key", default=None)
odoo_company_id_ctx = contextvars.ContextVar("odoo_company_id", default=None)
odoo_company_ids_ctx = contextvars.ContextVar("odoo_company_ids", default=None)
