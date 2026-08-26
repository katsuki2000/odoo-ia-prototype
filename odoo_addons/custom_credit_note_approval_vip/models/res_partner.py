from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    avoir_vip_exempt = fields.Boolean(string="Client VIP - avoirs sans seuil")
