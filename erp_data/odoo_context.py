"""Request-scoped Odoo identity ContextVars.

Shared kernel with no dependency on odoo_connector.py, which reads these vars.
"""

import contextvars
from contextlib import contextmanager

odoo_uid_ctx = contextvars.ContextVar("odoo_uid", default=None)
odoo_api_key_ctx = contextvars.ContextVar("odoo_api_key", default=None)
odoo_company_id_ctx = contextvars.ContextVar("odoo_company_id", default=None)
odoo_company_ids_ctx = contextvars.ContextVar("odoo_company_ids", default=None)
odoo_db_ctx = contextvars.ContextVar("odoo_db", default=None)


@contextmanager
def request_identity(uid, api_key, company_id=None, company_ids=None, db=None):
    """Bind the requester identity; absent values are bound too so a nested request cannot inherit them."""
    if company_ids is None and company_id is not None:
        company_ids = [company_id]
    values = (
        (odoo_uid_ctx, uid),
        (odoo_api_key_ctx, api_key),
        (odoo_company_id_ctx, None if company_id is None else int(company_id)),
        (odoo_company_ids_ctx, None if company_ids is None else [int(x) for x in company_ids]),
        (odoo_db_ctx, db),
    )
    tokens = [(var, var.set(value)) for var, value in values]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
