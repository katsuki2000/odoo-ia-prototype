# -*- coding: utf-8 -*-
"""
miro_ai_settings.py
===================
Modèle de configuration pour l'assistant MIRO AI.
Permet de configurer l'URL de l'API RAG, le jeton d'authentification et d'activer/désactiver
les catégories de compétences (Ventes, Stocks, Comptabilité, Tickets).
"""
import logging
import secrets
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MIN_SIGNING_SECRET_BYTES = 32
LEGACY_DEFAULT_SECRET = 'default_insecure_secret_for_dev'


class MiroAiSettings(models.Model):
    _name = 'miro.ai.settings'
    _description = 'MIRO AI - Paramètres et Configuration'
    _rec_name = 'name'

    name = fields.Char(
        string='Nom de configuration',
        required=True,
        default='Configuration MIRO RAG principale'
    )
    active = fields.Boolean(
        string='Actif',
        default=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        default=lambda self: self.env.company
    )

    # Paramètres de connexion vers FastAPI / RAG
    api_url = fields.Char(
        string='URL de l\'API MIRO RAG',
        required=True,
        default='http://127.0.0.1:8000',
        help='Adresse racine du serveur FastAPI MIRO RAG (ex: http://127.0.0.1:8000 ou http://miro_rag:8000)'
    )
    request_timeout = fields.Integer(
        string='Délai maximal de réponse (s)',
        required=True,
        default=120,
        help='Temps d\'attente maximal de la réponse du backend. En mode multi-workers, '
             'il doit rester inférieur à limit_time_real d\'Odoo (120 s par défaut).'
    )
    api_token = fields.Char(
        string='Jeton Secret API (JWT Secret)',
        default=lambda self: secrets.token_urlsafe(48),
        groups='base.group_system,miro_ai.group_miro_ai_admin',
        copy=False,
        help='Secret partagé avec le backend RAG (variable JWT_SECRET du serveur) : '
             'aléatoire, au moins 32 octets, identique des deux côtés. '
             'Lecture et écriture réservées aux administrateurs.'
    )

    # Catégories de compétences (skills toggles)
    activer_ventes = fields.Boolean(
        string='Compétence : Ventes (sale)',
        default=True,
        help='Activer la recherche ORM et documentaire sur le module Ventes'
    )
    activer_stocks = fields.Boolean(
        string='Compétence : Stocks (stock)',
        default=True,
        help='Activer la recherche ORM et documentaire sur le module Stocks / Inventaire'
    )
    activer_comptabilite = fields.Boolean(
        string='Compétence : Comptabilité (account)',
        default=True,
        help='Activer la recherche ORM et documentaire sur le module Comptabilité'
    )
    activer_tickets = fields.Boolean(
        string='Compétence : Support / Tickets (helpdesk)',
        default=True,
        help='Activer la recherche ORM et documentaire sur le module Support & Tickets'
    )

    _sql_constraints = [
        ('request_timeout_min', 'CHECK(request_timeout >= 10)',
         'Le délai maximal de réponse doit être d\'au moins 10 secondes.'),
    ]

    def get_signing_secret(self):
        self.ensure_one()
        secret = self.api_token or ''
        if secret == LEGACY_DEFAULT_SECRET or len(secret.encode('utf-8')) < MIN_SIGNING_SECRET_BYTES:
            raise UserError(
                "Le secret de signature MIRO AI n'est pas configuré : renseignez dans les paramètres "
                f"MIRO AI un secret aléatoire d'au moins {MIN_SIGNING_SECRET_BYTES} octets, "
                "identique à JWT_SECRET du serveur RAG."
            )
        return secret

    @api.model
    def get_active_settings(self):
        """Récupère la configuration active pour la société courante ou en crée une par défaut."""
        config = self.search([('company_id', '=', self.env.company.id)], limit=1)
        if not config:
            _logger.info("miro.ai.settings: aucune config spécifique à la société %s, recherche globale", self.env.company.id)
            config = self.search([], limit=1)
        if not config:
            _logger.info("miro.ai.settings: aucune config trouvée, création des paramètres par défaut")
            config = self.create({
                'name': 'Configuration MIRO RAG principale',
                'api_url': 'http://127.0.0.1:8000',
                'activer_ventes': True,
                'activer_stocks': True,
                'activer_comptabilite': True,
                'activer_tickets': True,
            })
        return config
