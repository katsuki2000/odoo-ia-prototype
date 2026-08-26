# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    miro_ai_api_url = fields.Char(
        string='URL API MIRO RAG',
        config_parameter='miro_ai.api_url',
        default='http://127.0.0.1:8000'
    )
    miro_ai_api_token = fields.Char(
        string='Jeton API MIRO RAG',
        config_parameter='miro_ai.api_token',
        default='default_insecure_secret_for_dev'
    )
