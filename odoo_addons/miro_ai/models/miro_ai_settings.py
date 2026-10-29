# -*- coding: utf-8 -*-
"""Configuration model of the MIRO AI assistant: backend URL, signing secret, skill toggles."""
import secrets
from odoo import _, models, fields, api
from odoo.exceptions import UserError

MIN_SIGNING_SECRET_BYTES = 32
LEGACY_DEFAULT_SECRET = 'default_insecure_secret_for_dev'
DEFAULT_API_URL = 'http://127.0.0.1:8000'


class MiroAiSettings(models.Model):
    _name = 'miro.ai.settings'
    _description = 'MIRO AI - Settings and Configuration'
    _rec_name = 'name'

    name = fields.Char(
        string='Configuration name',
        required=True,
        default='Main MIRO AI configuration'
    )

    # Backend connection
    api_url = fields.Char(
        string='MIRO RAG API URL',
        required=True,
        default=DEFAULT_API_URL,
        help='Root address of the MIRO RAG FastAPI server (e.g. http://127.0.0.1:8000 or http://miro_rag:8000)'
    )
    request_timeout = fields.Integer(
        string='Maximum response time (s)',
        required=True,
        default=120,
        help='Maximum time to wait for the answer to a question. '
             'Beyond it, the question is reported as too slow.'
    )
    api_token = fields.Char(
        string='API secret token (JWT secret)',
        default=lambda self: secrets.token_urlsafe(48),
        groups='base.group_system,miro_ai.group_miro_ai_admin',
        copy=False,
        help='Secret shared with the RAG backend (the server\'s JWT_SECRET variable): '
             'random, at least 32 bytes, identical on both sides. '
             'Read and write restricted to administrators.'
    )

    _sql_constraints = [
        ('request_timeout_min', 'CHECK(request_timeout >= 10)',
         'The maximum response time must be at least 10 seconds.'),
    ]

    def get_signing_secret(self):
        self.ensure_one()
        secret = self.api_token or ''
        if secret == LEGACY_DEFAULT_SECRET or len(secret.encode('utf-8')) < MIN_SIGNING_SECRET_BYTES:
            raise UserError(_(
                "The MIRO AI signing secret is not configured: set a random secret of at least "
                "%s bytes in the MIRO AI settings, identical to the RAG server's JWT_SECRET.",
                MIN_SIGNING_SECRET_BYTES,
            ))
        return secret

    @api.model_create_multi
    def create(self, vals_list):
        if len(vals_list) > 1 or self.sudo().search_count([]):
            raise UserError(_("MIRO AI has a single configuration: edit the existing one."))
        return super().create(vals_list)

    @api.model
    def get_active_settings(self):
        """Return the instance configuration, creating the default one when none exists."""
        return self.search([], limit=1) or self.create({})
