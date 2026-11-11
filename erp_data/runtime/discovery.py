"""Schema discovery guard: the fields of a model must be read in full before it is queried."""

from erp_data.connector.odoo_context import odoo_described_models_ctx
from erp_data.runtime.errors import SchemaNotReadError


def mark_described(model: str) -> None:
    described = odoo_described_models_ctx.get()
    if described is not None:
        described.add(model)


def require_described(model: str) -> None:
    """Refuse a query on a model whose fields were not read in this request; no request scope, no check."""
    described = odoo_described_models_ctx.get()
    if described is not None and model not in described:
        raise SchemaNotReadError(model)


def is_undescribed(model: str) -> bool:
    """True when this request is guarded and the model's full field list was not read yet."""
    described = odoo_described_models_ctx.get()
    return described is not None and model not in described
