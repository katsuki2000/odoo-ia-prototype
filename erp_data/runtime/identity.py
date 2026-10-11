from typing import Optional

from erp_data.odoo_context import (
    odoo_company_id_ctx,
    odoo_company_ids_ctx,
    odoo_uid_ctx,
)
from erp_data.runtime.errors import OrmRuntimeError


def require_execution_uid() -> int:
    uid = odoo_uid_ctx.get()
    if uid is not None:
        return int(uid)
    raise OrmRuntimeError("read refused: no requester uid in context")


def resolve_company_scope() -> tuple[Optional[int], Optional[list[int]]]:
    """Return (active company_id, allowed company_ids) from the session.

    Never derived from the LLM. Missing scope is allowed (legacy scripts);
    when present, company_ids defaults to [company_id] for mono-company.
    """
    raw_id = odoo_company_id_ctx.get()
    raw_ids = odoo_company_ids_ctx.get()
    company_ids: Optional[list[int]] = None
    if raw_ids is not None:
        company_ids = [int(x) for x in raw_ids]
        if not company_ids:
            raise OrmRuntimeError("read refused: empty company_ids in context")
    elif raw_id is not None:
        company_ids = [int(raw_id)]
    company_id = int(raw_id) if raw_id is not None else None
    if company_id is None and company_ids:
        company_id = company_ids[0]
    if (
        company_id is not None
        and company_ids is not None
        and company_id not in company_ids
    ):
        raise OrmRuntimeError(
            f"read refused: company_id {company_id} not in company_ids {company_ids}"
        )
    return company_id, company_ids
