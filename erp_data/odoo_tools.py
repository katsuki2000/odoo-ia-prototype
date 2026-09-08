"""
erp_data/odoo_tools.py

Facade re-exporting ORM tools and helpers across domain sub-modules:
- _odoo_helpers: connector, contexts, identity, domain resolution
- tools_sales: sales orders, counts, averages, itemized details
- tools_inventory: product stock, order status, out-of-stock items
- tools_accounting: invoices, period revenue
- tools_crm: commercial partner lookup, project tickets

Maintains full backward compatibility with all existing callers and tests.
"""

from erp_data._odoo_helpers import (
    connector,
    odoo_uid_ctx,
    odoo_api_key_ctx,
    get_current_uid,
    get_current_uid as _get_current_uid,
    orm_evidence_scope,
    orm_evidence_scope as _orm_evidence_scope,
    normalize_client_name,
    normalize_client_name as _normalize_client_name,
    resolve_statut,
    resolve_statut as _resolve_statut,
    STATUT_SCOPE_LABELS,
    parse_period,
)

from erp_data.tools_sales import (
    get_total_sales_raw,
    get_total_sales,
    get_order_count_raw,
    get_order_count,
    get_average_sales_raw,
    get_average_sales,
    get_sale_details_raw,
    get_sale_details,
)

from erp_data.tools_inventory import (
    get_product_stock_raw,
    get_product_stock,
    get_order_status_raw,
    get_order_status,
    list_out_of_stock_products_raw,
    list_out_of_stock_products,
)

from erp_data.tools_accounting import (
    get_total_invoices_raw,
    get_total_invoices,
    get_period_revenue_raw,
    get_period_revenue,
)

from erp_data.tools_crm import (
    search_partner_raw,
    search_partner,
    get_recent_tickets_raw,
    get_recent_tickets,
)

# Legacy aliases for scripts
obtenir_total_ventes = get_total_sales
obtenir_ca_periode = get_period_revenue

__all__ = [
    "connector",
    "odoo_uid_ctx",
    "odoo_api_key_ctx",
    "get_current_uid",
    "_get_current_uid",
    "orm_evidence_scope",
    "_orm_evidence_scope",
    "normalize_client_name",
    "_normalize_client_name",
    "resolve_statut",
    "_resolve_statut",
    "STATUT_SCOPE_LABELS",
    "parse_period",
    "get_total_sales_raw",
    "get_total_sales",
    "get_order_count_raw",
    "get_order_count",
    "get_average_sales_raw",
    "get_average_sales",
    "get_sale_details_raw",
    "get_sale_details",
    "get_product_stock_raw",
    "get_product_stock",
    "get_order_status_raw",
    "get_order_status",
    "list_out_of_stock_products_raw",
    "list_out_of_stock_products",
    "get_total_invoices_raw",
    "get_total_invoices",
    "get_period_revenue_raw",
    "get_period_revenue",
    "search_partner_raw",
    "search_partner",
    "get_recent_tickets_raw",
    "get_recent_tickets",
    "obtenir_total_ventes",
    "obtenir_ca_periode",
]
