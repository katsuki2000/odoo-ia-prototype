"""Request-scoped Odoo identity ContextVars.

Shared kernel with no dependency on odoo_connector.py, which reads these vars.
"""

import contextvars

odoo_uid_ctx = contextvars.ContextVar("odoo_uid", default=None)
odoo_api_key_ctx = contextvars.ContextVar("odoo_api_key", default=None)
odoo_company_id_ctx = contextvars.ContextVar("odoo_company_id", default=None)
odoo_company_ids_ctx = contextvars.ContextVar("odoo_company_ids", default=None)
