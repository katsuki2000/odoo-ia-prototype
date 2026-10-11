# -*- coding: utf-8 -*-
"""models/discuss_channel.py
===========================
Extension du modèle discuss.channel pour intercepter les messages et solliciter
l'Assistant IA via miro.ai.bot (architecture 0 JS).
"""
from odoo import api, models, _
from odoo.exceptions import UserError


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def _message_post_after_hook(self, message, msg_vals):
        """Intercepte le message posté et délègue au bot IA si approprié."""
        res = super()._message_post_after_hook(message, msg_vals)
        self.env['miro.ai.bot']._handle_channel_message(self, message, msg_vals)
        return res

    @api.model
    def action_open_ai_chat(self):
        """Ouvre ou crée le canal Discuss direct (1-à-1) avec l'Assistant IA."""
        bot_partner_id = self.env['ir.model.data']._xmlid_to_res_id('miro_ai_discuss.partner_miro_ai_bot')
        if not bot_partner_id:
            raise UserError(_("Le partenaire Assistant IA n'a pas été trouvé."))

        # Récupère ou crée la conversation privée avec le bot et l'épingle
        channel_info = self.channel_get([bot_partner_id], pin=True)
        channel_id = channel_info.get('id') if isinstance(channel_info, dict) else channel_info.id

        return {
            'type': 'ir.actions.client',
            'tag': 'mail.action_discuss',
            'params': {
                'active_id': channel_id,
            },
            'context': {
                'active_id': channel_id,
            },
        }
