"""Technical, value-free query plans for the independent ERP bank."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


TODAY = {"$today": True}
ACTIVE_COMPANY = {"$active_company": True}


def count(model: str, domain: list[list[Any]]) -> dict[str, Any]:
    return {"kind": "count", "model": model, "domain": domain}


def aggregate(
    model: str,
    domain: list[list[Any]],
    field: str,
    currency_field: str | None = None,
) -> dict[str, Any]:
    plan = {"kind": "aggregate", "model": model, "domain": domain, "field": field}
    if currency_field:
        plan["currency_field"] = currency_field
    return plan


def rows(model: str, domain: list[list[Any]], fields: list[str]) -> dict[str, Any]:
    return {"kind": "rows", "model": model, "domain": domain, "fields": fields}


def value(model: str, domain: list[list[Any]], field: str) -> dict[str, Any]:
    return {"kind": "value", "model": model, "domain": domain, "field": field}


def relation(
    model: str,
    domain: list[list[Any]],
    fields: list[str],
    paths: list[dict[str, Any]],
) -> dict[str, Any]:
    chains = [paths] if paths and isinstance(paths[0], dict) else paths
    return {
        "kind": "relation",
        "model": model,
        "domain": domain,
        "fields": fields,
        "paths": chains,
    }


def _path(field: str, model: str, fields: list[str]) -> dict[str, Any]:
    return {"field": field, "model": model, "fields": fields}


def build_plans() -> dict[str, dict[str, Any]]:
    posted_entry = [["state", "=", "posted"]]
    posted_invoice = [["move_type", "=", "out_invoice"], ["state", "=", "posted"]]
    posted_bill = [["move_type", "=", "in_invoice"], ["state", "=", "posted"]]
    confirmed_sale = [["state", "=", "sale"]]
    confirmed_purchase = [["state", "=", "purchase"]]
    plans = {
        "ERP-C-001": count("account.move", posted_entry),
        "ERP-C-002": count("account.move", posted_invoice),
        "ERP-C-003": aggregate("account.move", posted_invoice, "amount_total", "currency_id"),
        "ERP-C-004": aggregate("account.move", posted_bill, "amount_residual", "currency_id"),
        "ERP-C-005": count("account.payment", [["payment_type", "=", "outbound"]]),
        "ERP-C-006": aggregate("account.payment", [["payment_type", "=", "inbound"]], "amount", "currency_id"),
        "ERP-C-007": count("sale.order", confirmed_sale),
        "ERP-C-008": aggregate("sale.order", confirmed_sale, "amount_total", "currency_id"),
        "ERP-C-009": aggregate("sale.order", confirmed_sale, "amount_to_invoice", "currency_id"),
        "ERP-C-010": count("purchase.order", confirmed_purchase),
        "ERP-C-011": aggregate("purchase.order", confirmed_purchase, "amount_total", "currency_id"),
        "ERP-C-012": count("product.product", [["active", "=", True], ["sale_ok", "=", True]]),
        "ERP-C-013": aggregate("product.product", [], "qty_available"),
        "ERP-C-014": count("stock.picking", [["state", "=", "done"]]),
        "ERP-C-015": count("stock.picking", [["has_deadline_issue", "=", True]]),
        "ERP-C-016": count("account.move.line", [["reconciled", "=", True]]),
        "ERP-C-017": aggregate("account.move.line", [["move_id.state", "=", "posted"]], "debit"),
        "ERP-C-018": aggregate("account.analytic.line", [["category", "=", "invoice"]], "amount", "currency_id"),
        "ERP-C-019": count("crm.lead", [["type", "=", "lead"]]),
        "ERP-C-020": aggregate("crm.lead", [["type", "=", "opportunity"]], "expected_revenue", "company_currency"),
        "ERP-C-021": count("project.task", [["state", "=", "1_done"]]),
        "ERP-C-022": aggregate("project.task", [["state", "=", "1_done"]], "effective_hours"),
        "ERP-C-023": count("hr.leave", [["state", "=", "validate"]]),
        "ERP-C-024": aggregate("hr.leave", [["state", "=", "validate"]], "number_of_days"),
        "ERP-C-025": count("mrp.production", [["state", "=", "done"]]),
        "ERP-L-001": rows("account.move", posted_invoice, ["name", "invoice_date", "amount_total"]),
        "ERP-L-002": rows(
            "account.move",
            [["move_type", "=", "out_invoice"], ["payment_state", "in", ["not_paid", "partial"]]],
            ["name", "partner_id", "amount_residual"],
        ),
        "ERP-L-003": rows(
            "account.move",
            [["move_type", "in", ["out_invoice", "in_invoice"]], ["state", "=", "posted"], ["invoice_date_due", "<", TODAY], ["payment_state", "!=", "paid"]],
            ["name", "invoice_date_due", "payment_state", "amount_residual"],
        ),
        "ERP-L-004": rows("account.move", posted_bill, ["name", "partner_id", "invoice_date_due", "amount_residual"]),
        "ERP-L-005": rows("account.account", [["deprecated", "=", False]], ["code", "name"]),
        "ERP-L-006": rows("account.journal", [["active", "=", True], ["type", "in", ["bank", "cash"]]], ["code", "name"]),
        "ERP-L-007": rows("account.payment", [["payment_type", "=", "inbound"]], ["date", "partner_id", "amount"]),
        "ERP-L-008": rows("sale.order", [["state", "in", ["draft", "sent"]]], ["name", "amount_total"]),
        "ERP-L-009": rows("sale.order", confirmed_sale, ["name", "partner_id", "date_order", "amount_total"]),
        "ERP-L-010": rows("sale.order", [["invoice_status", "=", "to invoice"]], ["name", "amount_to_invoice"]),
        "ERP-L-011": rows("purchase.order", [["state", "=", "to approve"]], ["name", "partner_id", "date_order", "amount_total"]),
        "ERP-L-012": rows("purchase.order.line", [["qty_to_invoice", ">", 0]], ["order_id", "product_id", "qty_to_invoice"]),
        "ERP-L-013": rows("product.product", [["active", "=", True], ["sale_ok", "=", True]], ["display_name", "default_code", "list_price"]),
        "ERP-L-014": rows("product.product", [["qty_available", "<=", 0]], ["display_name", "default_code", "qty_available"]),
        "ERP-L-015": rows("product.product", [["incoming_qty", ">", 0], ["outgoing_qty", ">", 0]], ["display_name", "default_code", "incoming_qty", "outgoing_qty"]),
        "ERP-L-016": rows("stock.picking", [["state", "=", "assigned"]], ["name", "partner_id"]),
        "ERP-L-017": rows("stock.picking", [["state", "=", "cancel"]], ["name", "scheduled_date", "partner_id"]),
        "ERP-L-018": rows("stock.move", [["priority", "=", "1"]], ["name", "product_id", "picking_id", "state"]),
        "ERP-L-019": rows("crm.lead", [["type", "=", "opportunity"], ["priority", "in", ["2", "3"]]], ["name", "expected_revenue"]),
        "ERP-L-020": rows("crm.lead", [["type", "=", "lead"], ["user_id", "=", False]], ["name"]),
        "ERP-L-021": rows("project.task", [["state", "not in", ["1_done", "1_canceled"]]], ["name", "project_id", "date_deadline"]),
        "ERP-L-022": rows("project.task", [["user_ids", "!=", False]], ["name", "user_ids"]),
        "ERP-L-023": rows("hr.leave", [["state", "=", "validate"]], ["employee_id", "holiday_status_id", "date_from", "date_to"]),
        "ERP-L-024": rows("hr.employee", [["hr_presence_state", "=", "absent"]], ["name", "hr_presence_state"]),
        "ERP-L-025": rows("hr.expense", [["state", "=", "submitted"]], ["employee_id", "date", "total_amount"]),
        "ERP-R-001": relation("account.move", posted_invoice, ["name", "partner_id"], [_path("partner_id", "res.partner", ["name"])]),
        "ERP-R-002": relation("account.move", [["state", "=", "posted"]], ["name", "journal_id"], [_path("journal_id", "account.journal", ["name"])]),
        "ERP-R-003": relation("account.move", [["move_type", "=", "out_invoice"]], ["name", "payment_ids"], [_path("payment_ids", "account.payment", ["name", "date", "amount"])]),
        "ERP-R-004": relation("sale.order", confirmed_sale, ["name", "order_line"], [_path("order_line", "sale.order.line", ["product_id"]), _path("product_id", "product.product", ["name"])]),
        "ERP-R-005": relation("sale.order", [], ["name", "picking_ids"], [_path("picking_ids", "stock.picking", ["name"])]),
        "ERP-R-006": relation("purchase.order", [], ["name", "invoice_ids"], [_path("invoice_ids", "account.move", ["name"])]),
        "ERP-R-007": relation("stock.picking", [["sale_id", "!=", False]], ["name", "sale_id"], [_path("sale_id", "sale.order", ["partner_id"]), _path("partner_id", "res.partner", ["name"])]),
        "ERP-R-008": relation("stock.move", [], ["name", "product_id"], [_path("product_id", "product.product", ["categ_id"]), _path("categ_id", "product.category", ["name"])]),
        "ERP-R-009": relation("product.product", [], ["display_name", "stock_quant_ids"], [_path("stock_quant_ids", "stock.quant", ["location_id", "quantity"]), _path("location_id", "stock.location", ["name"])]),
        "ERP-R-010": relation("project.task", [], ["name", "project_id"], [_path("project_id", "project.project", ["partner_id"]), _path("partner_id", "res.partner", ["name"])]),
        "ERP-R-011": relation("project.task", [], ["name", "timesheet_ids"], [_path("timesheet_ids", "account.analytic.line", ["employee_id"]), _path("employee_id", "hr.employee", ["name"])]),
        "ERP-R-012": relation("hr.employee", [], ["name", "attendance_ids"], [_path("attendance_ids", "hr.attendance", ["check_in", "check_out"])]),
        "ERP-R-013": relation("hr.leave", [], ["name", "employee_id", "department_id"], [[_path("employee_id", "hr.employee", ["name"])], [_path("department_id", "hr.department", ["name"])] ]),
        "ERP-R-014": relation("mrp.production", [], ["name", "move_raw_ids"], [_path("move_raw_ids", "stock.move", ["product_id"]), _path("product_id", "product.product", ["name"])]),
        "ERP-R-015": relation("pos.order", [], ["name", "lines"], [_path("lines", "pos.order.line", ["product_id"]), _path("product_id", "product.product", ["name"])]),
        "ERP-V-001": value("res.company", [["id", "=", ACTIVE_COMPANY]], "name"),
        "ERP-V-002": value("res.company", [["id", "=", ACTIVE_COMPANY]], "currency_id"),
        "ERP-V-003": value("res.company", [["id", "=", ACTIVE_COMPANY]], "fiscalyear_last_day"),
        "ERP-V-004": value("res.company", [["id", "=", ACTIVE_COMPANY]], "fiscalyear_last_month"),
        "ERP-V-005": value("res.company", [["id", "=", ACTIVE_COMPANY]], "account_opening_date"),
        "ERP-V-006": value("res.company", [["id", "=", ACTIVE_COMPANY]], "period_lock_date"),
        "ERP-V-007": value("res.company", [["id", "=", ACTIVE_COMPANY]], "fiscalyear_lock_date"),
        "ERP-V-008": value("res.company", [["id", "=", ACTIVE_COMPANY]], "manufacturing_lead"),
        "ERP-V-009": value("res.company", [["id", "=", ACTIVE_COMPANY]], "days_to_purchase"),
        "ERP-V-010": value("res.company", [["id", "=", ACTIVE_COMPANY]], "sale_validity_auto_cancel_days"),
        "ERP-N-001": count("account.move", [["state", "=", "draft"], ["state", "=", "posted"]]),
        "ERP-N-002": count("account.move", [["move_type", "=", "out_invoice"], ["move_type", "=", "in_invoice"]]),
        "ERP-N-003": count("account.payment", [["payment_type", "=", "inbound"], ["payment_type", "=", "outbound"]]),
        "ERP-N-004": count("sale.order", [["state", "=", "draft"], ["state", "=", "sale"]]),
        "ERP-N-005": count("purchase.order", [["state", "=", "purchase"], ["state", "=", "cancel"]]),
        "ERP-N-006": count("stock.picking", [["state", "=", "done"], ["state", "=", "cancel"]]),
        "ERP-N-007": count("project.task", [["state", "=", "1_done"], ["state", "=", "1_canceled"]]),
        "ERP-N-008": count("hr.leave", [["state", "=", "validate"], ["state", "=", "refuse"]]),
        "ERP-N-009": count("hr.expense.sheet", [["state", "=", "approve"], ["state", "=", "cancel"]]),
        "ERP-N-010": count("mrp.production", [["state", "=", "done"], ["state", "=", "cancel"]]),
        "ERP-P-001": count("res.partner", []),
        "ERP-P-002": rows("res.company", [], ["name"]),
        "ERP-P-003": count("account.move", posted_entry),
        "ERP-P-004": rows("account.move", posted_invoice, ["name", "amount_residual"]),
        "ERP-P-005": rows("sale.order", [], ["name"]),
        "ERP-P-006": rows("purchase.order", [], ["name"]),
        "ERP-P-007": rows("stock.picking", [], ["name"]),
        "ERP-P-008": rows("product.product", [], ["display_name", "list_price"]),
        "ERP-P-009": rows("hr.employee", [], ["name"]),
        "ERP-P-010": rows("hr.attendance", [], ["employee_id", "check_in", "check_out"]),
        "ERP-P-011": rows("hr.leave", [], ["name", "state"]),
        "ERP-P-012": rows("hr.expense", [], ["name", "total_amount"]),
        "ERP-P-013": rows("project.task", [], ["name", "project_id"]),
        "ERP-P-014": rows("mrp.production", [], ["name"]),
        "ERP-P-015": rows("pos.order", [], ["name"]),
    }
    return deepcopy(plans)


PLANS = build_plans()
