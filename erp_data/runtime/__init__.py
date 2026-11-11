"""P9 runtime: execution sandbox, security boundary, schema discovery and types."""

from erp_data.runtime.discovery import is_undescribed, mark_described, require_described
from erp_data.runtime.errors import OrmRuntimeError, SchemaNotReadError
from erp_data.runtime.identity import require_execution_uid, resolve_company_scope
from erp_data.runtime.types import OrmObservation, OrmToolResult
from erp_data.runtime.validation import (
    DOMAIN_LEAF_OPS,
    DOMAIN_LOGICAL_OPS,
    assert_domain_within_companies,
    validate_domain,
    validate_field_list,
    validate_groupby,
    validate_model_name,
)

__all__ = [
    "DOMAIN_LEAF_OPS",
    "DOMAIN_LOGICAL_OPS",
    "OrmObservation",
    "OrmRuntimeError",
    "OrmToolResult",
    "SchemaNotReadError",
    "assert_domain_within_companies",
    "is_undescribed",
    "mark_described",
    "require_described",
    "require_execution_uid",
    "resolve_company_scope",
    "validate_domain",
    "validate_field_list",
    "validate_groupby",
    "validate_model_name",
]
