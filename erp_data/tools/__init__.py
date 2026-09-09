"""
erp_data/tools

Domain-specific LangChain @tool wrappers and raw query functions for Odoo ERP data:
- sales: sales orders, counts, averages, itemized details
- inventory: product stock, order status, out-of-stock items
- accounting: invoices, period revenue
- crm: commercial partner lookup, project tickets
"""

from erp_data.tools.sales import (
    get_total_sales_raw,
    get_total_sales,
    get_order_count_raw,
    get_order_count,
    get_average_sales_raw,
    get_average_sales,
    get_sale_details_raw,
    get_sale_details,
)

from erp_data.tools.inventory import (
    get_product_stock_raw,
    get_product_stock,
    get_order_status_raw,
    get_order_status,
    list_out_of_stock_products_raw,
    list_out_of_stock_products,
)

from erp_data.tools.accounting import (
    get_total_invoices_raw,
    get_total_invoices,
    get_period_revenue_raw,
    get_period_revenue,
)

from erp_data.tools.crm import (
    search_partner_raw,
    search_partner,
    get_recent_tickets_raw,
    get_recent_tickets,
)

__all__ = [
    # Sales
    "get_total_sales_raw",
    "get_total_sales",
    "get_order_count_raw",
    "get_order_count",
    "get_average_sales_raw",
    "get_average_sales",
    "get_sale_details_raw",
    "get_sale_details",
    # Inventory
    "get_product_stock_raw",
    "get_product_stock",
    "get_order_status_raw",
    "get_order_status",
    "list_out_of_stock_products_raw",
    "list_out_of_stock_products",
    # Accounting
    "get_total_invoices_raw",
    "get_total_invoices",
    "get_period_revenue_raw",
    "get_period_revenue",
    # CRM
    "search_partner_raw",
    "search_partner",
    "get_recent_tickets_raw",
    "get_recent_tickets",
]
