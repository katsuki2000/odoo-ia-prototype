# miro-rag/code_intelligence/domain_relational.py
"""
odoo-relational-domain-declaration.
Tests fields.Many2one and fields.Many2many declarations containing domain= attributes.
"""

from odoo import fields, models


class TestRelationalDomainModel(models.Model):
    _name = "test.relational.domain"
    _description = "Test Relational Domain Model"

    # ruleid: odoo-relational-domain-declaration
    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        domain=[("is_company", "=", True), ("customer_rank", ">", 0)],
    )

    # ruleid: odoo-relational-domain-declaration
    nested_domain_partner_id = fields.Many2one(
        "res.partner",
        string="Nested Partner",
        domain=["|", ("is_company", "=", True), ("parent_id", "=", False)],
    )

    # ruleid: odoo-relational-domain-declaration
    category_ids = fields.Many2many(
        "res.partner.category",
        string="Categories",
        domain=[("active", "=", True)],
    )

    # ruleid: odoo-relational-domain-declaration
    string_domain_partner_id = fields.Many2one(
        "res.partner",
        string="Dynamic String Partner",
        domain="[('company_id', '=', company_id)]",
    )

    # ok: odoo-relational-domain-declaration
    simple_partner_id = fields.Many2one(
        "res.partner",
        string="Simple Partner",
    )

    # ok: odoo-relational-domain-declaration
    simple_category_ids = fields.Many2many(
        "res.partner.category",
        string="Simple Categories",
    )

    # ok: odoo-relational-domain-declaration
    line_ids = fields.One2many(
        "test.relational.domain.line",
        "parent_id",
        string="Lines",
        domain=[("active", "=", True)],
    )

    # ok: odoo-relational-domain-declaration
    lambda_partner_id = fields.Many2one(
        "res.partner",
        string="Lambda Partner",
        domain=lambda self: [("company_id", "in", self.env.companies.ids)],
    )
