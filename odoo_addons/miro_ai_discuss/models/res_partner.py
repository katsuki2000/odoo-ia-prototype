# -*- coding: utf-8 -*-
"""models/res_partner.py
======================
Extension du modèle res.partner pour attribuer le statut instant messaging 'bot'
au partenaire Assistant IA dans l'interface Discuss d'Odoo 17.
"""
from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _compute_im_status(self):
        super()._compute_im_status()
        bot_id = self.env['ir.model.data']._xmlid_to_res_id('miro_ai_discuss.partner_miro_ai_bot')
        if bot_id:
            bot = self.browse(bot_id)
            if bot in self:
                bot.im_status = 'bot'
