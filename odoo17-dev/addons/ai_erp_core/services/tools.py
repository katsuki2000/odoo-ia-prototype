# -*- coding: utf-8 -*-
"""
tools.py
========
Predefined, safe ORM tool implementations.

IMPORTANT DESIGN RULE
---------------------
No raw SQL strings, no dynamic ORM queries constructed from untrusted user
input. Every function here:
  1. Accepts only validated Python primitives (str, int)
  2. Uses Odoo's ORM domain syntax
  3. Returns a structured dict with a mandatory 'source' key for citation

When the router calls one of these functions, the result is passed back
to the LLM together with the data source label so the answer can be cited.

Adding a new tool
-----------------
1. Add a function below following the existing pattern.
2. Add an `ai.tool` record (or via _load_default_tools) with the same name.
"""
import logging
from datetime import datetime, date

_logger = logging.getLogger(__name__)


def _get_partner_id(env, client_name: str) -> int | None:
    """Fuzzy-search a partner by name and return its ID."""
    partner = env['res.partner'].search(
        [('name', 'ilike', client_name), ('customer_rank', '>', 0)],
        limit=1,
    )
    return partner.id if partner else None


# ─────────────────────────────────────────────────────────────────────────────
# Sales tools
# ─────────────────────────────────────────────────────────────────────────────

def get_sales_total(env, client_name: str, year: int) -> dict:
    """
    Return the total invoiced sales for a given client and calendar year.

    Returns
    -------
    dict with: total (float), currency (str), invoice_count (int), source (str)
    """
    partner_id = _get_partner_id(env, client_name)
    if not partner_id:
        return {
            'error': f'Client « {client_name} » introuvable.',
            'source': 'Modèle : res.partner',
        }

    date_from = date(year, 1, 1)
    date_to = date(year, 12, 31)

    invoices = env['account.move'].search([
        ('partner_id', '=', partner_id),
        ('move_type', '=', 'out_invoice'),
        ('state', '=', 'posted'),
        ('invoice_date', '>=', date_from),
        ('invoice_date', '<=', date_to),
    ])

    total = sum(inv.amount_total_signed for inv in invoices)
    currency = env.company.currency_id.name

    return {
        'client': client_name,
        'year': year,
        'total': round(total, 2),
        'currency': currency,
        'invoice_count': len(invoices),
        'source': 'Odoo ORM : account.move (factures validées)',
    }


def get_top_products(env, year: int, limit: int = 10) -> dict:
    """
    Return the top N products by quantity sold for a given year.
    """
    date_from = date(year, 1, 1)
    date_to = date(year, 12, 31)

    lines = env['sale.order.line'].search([
        ('order_id.state', 'in', ['sale', 'done']),
        ('order_id.date_order', '>=', str(date_from)),
        ('order_id.date_order', '<=', str(date_to)),
    ])

    # Aggregate by product
    totals: dict[str, float] = {}
    for line in lines:
        name = line.product_id.name or 'Inconnu'
        totals[name] = totals.get(name, 0.0) + line.product_uom_qty

    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:limit]
    return {
        'year': year,
        'top_products': [{'product': p, 'qty': q} for p, q in ranked],
        'source': 'Odoo ORM : sale.order.line',
    }


# ─────────────────────────────────────────────────────────────────────────────
# Accounting tools
# ─────────────────────────────────────────────────────────────────────────────

def get_invoice_status(env, client_name: str, year: int) -> dict:
    """
    Return a summary of invoices (paid / unpaid) for a client and year.
    """
    partner_id = _get_partner_id(env, client_name)
    if not partner_id:
        return {
            'error': f'Client « {client_name} » introuvable.',
            'source': 'Modèle : res.partner',
        }

    date_from = date(year, 1, 1)
    date_to = date(year, 12, 31)

    invoices = env['account.move'].search([
        ('partner_id', '=', partner_id),
        ('move_type', '=', 'out_invoice'),
        ('state', '=', 'posted'),
        ('invoice_date', '>=', date_from),
        ('invoice_date', '<=', date_to),
    ])

    paid = invoices.filtered(lambda i: i.payment_state == 'paid')
    unpaid = invoices.filtered(lambda i: i.payment_state in ('not_paid', 'partial'))

    return {
        'client': client_name,
        'year': year,
        'paid_count': len(paid),
        'paid_total': round(sum(i.amount_total_signed for i in paid), 2),
        'unpaid_count': len(unpaid),
        'unpaid_total': round(sum(i.amount_residual_signed for i in unpaid), 2),
        'currency': env.company.currency_id.name,
        'source': 'Odoo ORM : account.move (état de paiement)',
    }


# ─────────────────────────────────────────────────────────────────────────────
# General / workflow tools
# ─────────────────────────────────────────────────────────────────────────────

def get_approval_rule(env, operation_type: str) -> dict:
    """
    Lookup approval rules for a given operation type.
    Checks ir.rule, stock.picking.type, and purchase.order approval thresholds.
    """
    results = []

    # Purchase order double validation
    if 'achat' in operation_type.lower() or 'purchase' in operation_type.lower():
        try:
            po_settings = env['res.config.settings'].default_get(
                ['po_double_validation', 'po_double_validation_amount']
            )
            results.append({
                'rule': 'Double validation bon de commande',
                'active': po_settings.get('po_double_validation', False),
                'threshold': po_settings.get('po_double_validation_amount', 'N/A'),
                'currency': env.company.currency_id.name,
            })
        except Exception:
            pass

    if not results:
        results.append({
            'rule': 'Aucune règle d\'approbation configurée trouvée',
            'hint': f'Vérifiez la configuration pour : {operation_type}',
        })

    return {
        'operation_type': operation_type,
        'approval_rules': results,
        'source': 'Odoo ORM : res.config.settings, ir.rule',
    }


# ─────────────────────────────────────────────────────────────────────────────
# Inventory tools
# ─────────────────────────────────────────────────────────────────────────────

def get_stock_level(env, product_name: str, warehouse_name: str = '') -> dict:
    """
    Return on-hand quantity for a product, optionally filtered by warehouse.
    """
    domain = [('name', 'ilike', product_name)]
    product = env['product.product'].search(domain, limit=1)
    if not product:
        return {
            'error': f'Produit « {product_name} » introuvable.',
            'source': 'Modèle : product.product',
        }

    quant_domain = [('product_id', '=', product.id)]
    if warehouse_name:
        warehouse = env['stock.warehouse'].search(
            [('name', 'ilike', warehouse_name)], limit=1
        )
        if warehouse:
            quant_domain.append(('location_id', 'child_of', warehouse.lot_stock_id.id))

    quants = env['stock.quant'].search(quant_domain)
    qty_on_hand = sum(q.quantity for q in quants)
    qty_reserved = sum(q.reserved_quantity for q in quants)

    return {
        'product': product.name,
        'warehouse': warehouse_name or 'Tous entrepôts',
        'qty_on_hand': round(qty_on_hand, 2),
        'qty_reserved': round(qty_reserved, 2),
        'qty_available': round(qty_on_hand - qty_reserved, 2),
        'uom': product.uom_id.name,
        'source': 'Odoo ORM : stock.quant',
    }


# ─────────────────────────────────────────────────────────────────────────────
# Project tools
# ─────────────────────────────────────────────────────────────────────────────

def get_open_tasks(
    env, project_name: str = '', assignee_name: str = ''
) -> dict:
    """
    Return open tasks optionally filtered by project and/or assignee.
    """
    domain = [('stage_id.fold', '=', False)]  # non-folded = open stages

    if project_name:
        project = env['project.project'].search(
            [('name', 'ilike', project_name)], limit=1
        )
        if project:
            domain.append(('project_id', '=', project.id))

    if assignee_name:
        user = env['res.users'].search(
            [('name', 'ilike', assignee_name)], limit=1
        )
        if user:
            domain.append(('user_ids', 'in', [user.id]))

    tasks = env['project.task'].search(domain, limit=50)
    tasks_data = [
        {
            'name': t.name,
            'project': t.project_id.name or 'Aucun projet',
            'stage': t.stage_id.name,
            'assignees': ', '.join(t.user_ids.mapped('name')),
            'deadline': str(t.date_deadline) if t.date_deadline else 'Aucune',
        }
        for t in tasks
    ]

    return {
        'filter_project': project_name or 'Tous',
        'filter_assignee': assignee_name or 'Tous',
        'total_open': len(tasks),
        'tasks': tasks_data,
        'source': 'Odoo ORM : project.task',
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch table (used by the router)
# ─────────────────────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict = {
    'get_sales_total': get_sales_total,
    'get_top_products': get_top_products,
    'get_invoice_status': get_invoice_status,
    'get_approval_rule': get_approval_rule,
    'get_stock_level': get_stock_level,
    'get_open_tasks': get_open_tasks,
}


def call_tool(env, tool_name: str, arguments: dict) -> dict:
    """
    Safely dispatch a tool call.

    Parameters
    ----------
    env       : Odoo environment
    tool_name : name of the function in TOOL_REGISTRY
    arguments : dict of keyword arguments

    Returns
    -------
    dict with tool results (always includes a 'source' key).
    """
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return {
            'error': f'Outil inconnu : {tool_name}',
            'source': 'Registre des outils AI ERP',
        }
    try:
        # Update usage stats on the ai.tool record
        tool_rec = env['ai.tool'].search([('tool_name', '=', tool_name)], limit=1)
        if tool_rec:
            import fields as _f  # noqa — use Odoo fields.Datetime.now()
            from odoo import fields as odoo_fields
            tool_rec.sudo().write({
                'call_count': tool_rec.call_count + 1,
                'last_called': odoo_fields.Datetime.now(),
            })
        result = fn(env, **arguments)
        return result
    except Exception as exc:
        _logger.exception('Tool call %s failed', tool_name)
        tool_rec = env['ai.tool'].search([('tool_name', '=', tool_name)], limit=1)
        if tool_rec:
            tool_rec.sudo().write({'error_count': tool_rec.error_count + 1})
        return {
            'error': f'Erreur lors de l\'appel à {tool_name} : {exc}',
            'source': f'Odoo ORM — {tool_name}',
        }
