# -*- coding: utf-8 -*-
"""
controllers/main.py
===================
Contrôleur Odoo pour MIRO AI Assistant.
Sera enrichi lors du Jour 3 pour la communication avec FastAPI et la génération JWT.
"""
from odoo import http
from odoo.http import request


class MiroAiController(http.Controller):

    @http.route('/miro_ai/health', type='json', auth='user', methods=['POST'])
    def health_check(self):
        """Vérification rapide de la santé du module MIRO AI côté Odoo."""
        return {
            'status': 'ok',
            'module': 'miro_ai',
            'user_id': request.env.user.id,
            'company_id': request.env.company.id
        }
