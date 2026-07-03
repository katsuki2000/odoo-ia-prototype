# -*- coding: utf-8 -*-
"""
ai_tool.py
==========
Registry of predefined ORM tools exposed to the LLM.
Each tool defines a safe, named function the router may call on live Odoo data.
No free-form SQL is ever executed — only these registered, code-reviewed functions.
"""
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class AiTool(models.Model):
    _name = 'ai.tool'
    _description = 'AI ERP — Outil ORM enregistré'
    _rec_name = 'tool_name'
    _order = 'category, tool_name'

    # ── Definition ──────────────────────────────────────────────────────────────
    tool_name = fields.Char(
        string='Nom de l\'outil (fonction)',
        required=True,
        index=True,
        help='Nom Python exact de la fonction dans services/tools.py',
    )
    display_name = fields.Char(
        string='Nom affiché',
        required=True,
    )
    description = fields.Text(
        string='Description (vue par le LLM)',
        required=True,
        help=(
            'Cette description est envoyée au LLM pour qu\'il comprenne '
            'quand utiliser cet outil et ce qu\'il retourne.'
        ),
    )
    category = fields.Selection(
        [
            ('sales', 'Ventes'),
            ('purchase', 'Achats'),
            ('accounting', 'Comptabilité'),
            ('inventory', 'Stock'),
            ('hr', 'Ressources humaines'),
            ('project', 'Projets'),
            ('crm', 'CRM'),
            ('general', 'Général'),
        ],
        string='Catégorie',
        default='general',
        required=True,
    )
    active = fields.Boolean(default=True)

    # ── Parameters schema (JSON) ────────────────────────────────────────────────
    parameters_schema = fields.Text(
        string='Schéma des paramètres (JSON)',
        help=(
            'Schéma JSON décrivant les paramètres attendus.\n'
            'Exemple : {"client_name": "string", "year": "int"}'
        ),
    )

    # ── Usage stats ──────────────────────────────────────────────────────────────
    call_count = fields.Integer(
        string='Nombre d\'appels',
        readonly=True,
        default=0,
    )
    last_called = fields.Datetime(
        string='Dernier appel',
        readonly=True,
    )
    error_count = fields.Integer(
        string='Erreurs',
        readonly=True,
        default=0,
    )

    def action_reset_stats(self):
        """Reset usage statistics for selected tools."""
        self.write({'call_count': 0, 'error_count': 0, 'last_called': False})

    @api.model
    def get_tools_schema_for_llm(self):
        """
        Return the list of active tools formatted as an Ollama/OpenAI
        tool-calling schema so the router LLM can pick the right one.
        """
        import json
        tools = self.search([('active', '=', True)])
        schema = []
        for t in tools:
            try:
                params = json.loads(t.parameters_schema or '{}')
            except Exception:
                params = {}
            schema.append({
                'type': 'function',
                'function': {
                    'name': t.tool_name,
                    'description': t.description,
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            k: {'type': v} for k, v in params.items()
                        },
                        'required': list(params.keys()),
                    },
                },
            })
        return schema

    @api.model
    def _load_default_tools(self):
        """
        Populate the registry with the built-in ORM tools on first install.
        Called from post_init_hook.
        """
        defaults = [
            {
                'tool_name': 'get_sales_total',
                'display_name': 'Total des ventes client',
                'description': (
                    'Retourne le chiffre d\'affaires total (en devise société) '
                    'pour un client donné sur une période. '
                    'Paramètres : client_name (str), year (int).'
                ),
                'category': 'sales',
                'parameters_schema': '{"client_name": "string", "year": "integer"}',
            },
            {
                'tool_name': 'get_top_products',
                'display_name': 'Produits les plus vendus',
                'description': (
                    'Retourne les N produits les plus vendus en quantité '
                    'sur une période donnée. '
                    'Paramètres : year (int), limit (int, défaut 10).'
                ),
                'category': 'sales',
                'parameters_schema': '{"year": "integer", "limit": "integer"}',
            },
            {
                'tool_name': 'get_invoice_status',
                'display_name': 'Statut des factures client',
                'description': (
                    'Retourne la liste des factures (payées/impayées) '
                    'pour un client et une année. '
                    'Paramètres : client_name (str), year (int).'
                ),
                'category': 'accounting',
                'parameters_schema': '{"client_name": "string", "year": "integer"}',
            },
            {
                'tool_name': 'get_approval_rule',
                'display_name': 'Règle d\'approbation',
                'description': (
                    'Retourne qui doit approuver un type d\'opération donné '
                    '(ex : allocation de ressource, bon de commande > seuil). '
                    'Paramètre : operation_type (str).'
                ),
                'category': 'general',
                'parameters_schema': '{"operation_type": "string"}',
            },
            {
                'tool_name': 'get_stock_level',
                'display_name': 'Niveau de stock produit',
                'description': (
                    'Retourne la quantité en stock d\'un produit dans un entrepôt. '
                    'Paramètres : product_name (str), warehouse_name (str, optionnel).'
                ),
                'category': 'inventory',
                'parameters_schema': '{"product_name": "string", "warehouse_name": "string"}',
            },
            {
                'tool_name': 'get_open_tasks',
                'display_name': 'Tâches ouvertes projet',
                'description': (
                    'Retourne les tâches ouvertes d\'un projet ou d\'un utilisateur. '
                    'Paramètres : project_name (str, optionnel), assignee_name (str, optionnel).'
                ),
                'category': 'project',
                'parameters_schema': '{"project_name": "string", "assignee_name": "string"}',
            },
        ]
        for tool_data in defaults:
            existing = self.search([('tool_name', '=', tool_data['tool_name'])], limit=1)
            if not existing:
                self.create(tool_data)
