# -*- coding: utf-8 -*-
"""
ai_config.py
============
Stores the Ollama / LLM provider configuration that the module uses.
Each Odoo company can have its own AI configuration record.
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class AiConfig(models.Model):
    _name = 'ai.config'
    _description = 'AI ERP — Configuration du provider LLM'
    _rec_name = 'name'
    _order = 'sequence, id'

    # ── Identification ─────────────────────────────────────────────────────────
    name = fields.Char(
        string='Nom de la configuration',
        required=True,
        default='Configuration Ollama principale',
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Société',
        default=lambda self: self.env.company,
    )

    # ── Ollama connection ───────────────────────────────────────────────────────
    ollama_base_url = fields.Char(
        string='URL de base Ollama',
        required=True,
        default='http://10.0.0.219:11434',
        help='URL du serveur Ollama. Depuis Docker, utilisez l\'IP de l\'hôte.',
    )

    # Models selection (user picks from available pulled models)
    model_chat = fields.Char(
        string='Modèle Chat / Tool-use',
        required=True,
        default='llama3.1',
        help=(
            'Modèle Ollama utilisé pour le routage et la réponse finale.\n'
            'Exemples : hermes3:8b, mistral:7b, phi3.5'
        ),
    )
    model_embed = fields.Char(
        string='Modèle Embedding',
        required=True,
        default='nomic-embed-text',
        help=(
            'Modèle Ollama utilisé pour générer les embeddings vectoriels.\n'
            'Exemple : nomic-embed-text'
        ),
    )

    # ── ChromaDB vector store ───────────────────────────────────────────────────
    chromadb_host = fields.Char(
        string='Hôte ChromaDB',
        required=True,
        default='chromadb',
    )
    chromadb_port = fields.Integer(
        string='Port ChromaDB',
        required=True,
        default=8000,
    )
    chromadb_collection_docs = fields.Char(
        string='Collection — Documents',
        default='erp_documents',
    )
    chromadb_collection_code = fields.Char(
        string='Collection — Code source',
        default='erp_code',
    )

    # ── Ingestion paths ─────────────────────────────────────────────────────────
    code_ingestion_paths = fields.Text(
        string='Chemins d\'ingestion code (un par ligne)',
        default='/mnt/extra-addons',
        help=(
            'Répertoires à analyser pour l\'ingestion du code source Python/XML.\n'
            'Un chemin absolu par ligne.'
        ),
    )

    # ── RAG parameters ──────────────────────────────────────────────────────────
    rag_top_k = fields.Integer(
        string='Top-K résultats RAG',
        default=5,
        help='Nombre de fragments retournés par la recherche sémantique.',
    )
    chunk_size = fields.Integer(
        string='Taille des chunks (tokens)',
        default=512,
    )
    chunk_overlap = fields.Integer(
        string='Chevauchement des chunks (tokens)',
        default=64,
    )

    # ── Generation parameters ───────────────────────────────────────────────────
    temperature = fields.Float(
        string='Température',
        default=0.2,
        help='0 = déterministe, 1 = créatif.',
    )
    max_tokens = fields.Integer(
        string='Tokens max en réponse',
        default=1024,
    )
    timeout_seconds = fields.Integer(
        string='Timeout Ollama (s)',
        default=120,
    )

    # ── System prompt ───────────────────────────────────────────────────────────
    system_prompt = fields.Text(
        string='Prompt système',
        default=(
            'Tu es l\'assistant IA interne de l\'ERP MIRO KE. '
            'Réponds en français, de manière concise et professionnelle. '
            'Chaque réponse DOIT indiquer la source exacte de l\'information '
            '(nom du fichier, page, article ou champ ORM). '
            'Si tu ne trouves pas la réponse dans les sources disponibles, '
            'dis-le clairement plutôt que d\'inventer.'
        ),
    )

    # ── Status / test ───────────────────────────────────────────────────────────
    last_test_date = fields.Datetime(string='Dernier test de connexion', readonly=True)
    last_test_result = fields.Selection(
        [('ok', 'Succès'), ('error', 'Erreur'), ('pending', 'En attente')],
        string='Résultat du test',
        default='pending',
        readonly=True,
    )
    last_test_message = fields.Text(string='Message du test', readonly=True)

    # ── Constraints ─────────────────────────────────────────────────────────────
    @api.constrains('temperature')
    def _check_temperature(self):
        for rec in self:
            if not (0.0 <= rec.temperature <= 2.0):
                raise ValidationError('La température doit être entre 0.0 et 2.0.')

    @api.constrains('rag_top_k')
    def _check_rag_top_k(self):
        for rec in self:
            if rec.rag_top_k < 1 or rec.rag_top_k > 20:
                raise ValidationError('Top-K doit être entre 1 et 20.')

    # ── Actions ─────────────────────────────────────────────────────────────────
    def action_test_connection(self):
        """Test the Ollama connection and update status fields."""
        self.ensure_one()
        from ..services.ollama_client import OllamaClient
        client = OllamaClient(self)
        ok, message = client.test_connection()
        self.write({
            'last_test_date': fields.Datetime.now(),
            'last_test_result': 'ok' if ok else 'error',
            'last_test_message': message,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Test de connexion Ollama',
                'message': message,
                'type': 'success' if ok else 'danger',
                'sticky': False,
            },
        }

    def action_list_models(self):
        """Fetch and display the list of models available on Ollama."""
        self.ensure_one()
        from ..services.ollama_client import OllamaClient
        client = OllamaClient(self)
        models_list = client.list_models()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Modèles Ollama disponibles',
                'message': ', '.join(models_list) if models_list else 'Aucun modèle trouvé.',
                'type': 'info',
                'sticky': True,
            },
        }

    @api.model
    def get_active_config(self):
        """Return the first active configuration for the current company."""
        config = self.search(
            [('company_id', '=', self.env.company.id), ('active', '=', True)],
            limit=1,
        )
        if not config:
            config = self.search([('active', '=', True)], limit=1)
        return config
