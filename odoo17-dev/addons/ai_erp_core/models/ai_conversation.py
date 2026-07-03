# -*- coding: utf-8 -*-
"""
ai_conversation.py
==================
Persists every chat session and its individual messages.
Each message records the pipeline that answered it (doc RAG, code RAG, ORM tool)
and the full list of source citations returned.
"""
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class AiConversation(models.Model):
    _name = 'ai.conversation'
    _description = 'AI ERP — Session de conversation'
    _rec_name = 'name'
    _order = 'create_date desc'

    name = fields.Char(
        string='Titre de la session',
        required=True,
        default='Nouvelle conversation',
    )
    user_id = fields.Many2one(
        'res.users',
        string='Utilisateur',
        default=lambda self: self.env.user,
        readonly=True,
        index=True,
    )
    message_ids = fields.One2many(
        'ai.message',
        'conversation_id',
        string='Messages',
    )
    message_count = fields.Integer(
        string='Nombre de messages',
        compute='_compute_message_count',
    )
    active = fields.Boolean(default=True)
    config_id = fields.Many2one(
        'ai.config',
        string='Configuration IA utilisée',
        readonly=True,
    )

    @api.depends('message_ids')
    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.message_ids)

    def action_clear(self):
        """Delete all messages in this conversation."""
        self.ensure_one()
        self.message_ids.unlink()

    def action_open_chat(self):
        """Open the chat interface for this conversation."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'ai.conversation',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }


class AiMessage(models.Model):
    _name = 'ai.message'
    _description = 'AI ERP — Message de conversation'
    _order = 'sequence, create_date'

    conversation_id = fields.Many2one(
        'ai.conversation',
        string='Conversation',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)

    role = fields.Selection(
        [('user', 'Utilisateur'), ('assistant', 'Assistant'), ('system', 'Système')],
        string='Rôle',
        required=True,
        default='user',
    )
    content = fields.Text(
        string='Contenu',
        required=True,
    )

    # ── Routing metadata (filled only on assistant messages) ────────────────────
    pipeline_used = fields.Selection(
        [
            ('doc_rag', 'RAG — Documents'),
            ('code_rag', 'RAG — Code source'),
            ('orm_tool', 'Outil ORM — Données structurées'),
            ('combined', 'Combiné'),
            ('fallback', 'Réponse directe (pas de source)'),
        ],
        string='Pipeline utilisé',
        readonly=True,
    )
    tool_called = fields.Char(
        string='Outil ORM appelé',
        readonly=True,
        help='Nom de la fonction ORM appelée si pipeline=orm_tool.',
    )

    # ── Citations ───────────────────────────────────────────────────────────────
    citations = fields.Text(
        string='Citations (JSON)',
        readonly=True,
        help=(
            'Liste JSON des sources citées.\n'
            'Format : [{"source": "...", "page": 3, "score": 0.87}, ...]'
        ),
    )
    citations_display = fields.Html(
        string='Sources',
        compute='_compute_citations_display',
    )

    # ── Performance ─────────────────────────────────────────────────────────────
    tokens_prompt = fields.Integer(string='Tokens (prompt)', readonly=True)
    tokens_completion = fields.Integer(string='Tokens (réponse)', readonly=True)
    duration_ms = fields.Integer(string='Durée (ms)', readonly=True)

    @api.depends('citations')
    def _compute_citations_display(self):
        import json
        for rec in self:
            if not rec.citations:
                rec.citations_display = '<em>Aucune source</em>'
                continue
            try:
                data = json.loads(rec.citations)
                html_parts = ['<ul class="ai-citations">']
                for c in data:
                    source = c.get('source', 'Inconnu')
                    detail = ''
                    if 'page' in c:
                        detail += f', page {c["page"]}'
                    if 'line_start' in c:
                        detail += f', ligne {c["line_start"]}'
                    if 'score' in c:
                        score_pct = round(c['score'] * 100, 1)
                        detail += f' <span class="badge">{score_pct}%</span>'
                    html_parts.append(
                        f'<li><strong>{source}</strong>{detail}</li>'
                    )
                html_parts.append('</ul>')
                rec.citations_display = ''.join(html_parts)
            except Exception:
                rec.citations_display = f'<code>{rec.citations}</code>'
