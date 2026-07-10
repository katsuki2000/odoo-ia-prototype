# -*- coding: utf-8 -*-
"""
miro_ai_log.py
==============
Modèle de journal d'audit et d'historique des requêtes MIRO AI (Step 11 Day 4).
Enregistre chaque question posée, la réponse générée par le RAG, les sources citées,
le temps de réponse et l'utilisateur à l'origine de la requête pour traçabilité et débogage.
"""
from odoo import models, fields, api
import json


class MiroAiLog(models.Model):
    _name = 'miro.ai.log'
    _description = 'MIRO AI - Journal d\'audit des requêtes RAG'
    _order = 'create_date desc, id desc'
    _rec_name = 'question'

    question = fields.Text(
        string='Question posée',
        required=True,
        readonly=True,
        help='Texte brut de la question envoyée par l\'utilisateur au RAG.'
    )
    answer = fields.Html(
        string='Réponse générée',
        readonly=True,
        help='Réponse mise en forme (Markdown transformé en HTML ou texte brut) renvoyée par le RAG.'
    )
    user_id = fields.Many2one(
        'res.users',
        string='Utilisateur',
        default=lambda self: self.env.user,
        required=True,
        readonly=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        default=lambda self: self.env.company,
        required=True,
        readonly=True
    )
    session_id = fields.Char(
        string='ID de Session',
        readonly=True,
        index=True,
        help='Identifiant unique de la session de discussion RAG.'
    )
    response_time_ms = fields.Integer(
        string='Temps de réponse (ms)',
        readonly=True,
        help='Durée d\'interrogation du backend FastAPI RAG en millisecondes.'
    )
    sources_text = fields.Text(
        string='Sources (JSON brut)',
        readonly=True,
        help='Liste brute des documents ou extraits ORM cités.'
    )
    sources_count = fields.Integer(
        string='Nb Sources',
        compute='_compute_sources_count',
        store=True,
        help='Nombre de sources documentaires/code citées par la réponse.'
    )
    state = fields.Selection([
        ('success', 'Succès'),
        ('error', 'Erreur')
    ], string='Statut', default='success', readonly=True, index=True)

    @api.depends('sources_text')
    def _compute_sources_count(self):
        for rec in self:
            count = 0
            if rec.sources_text:
                try:
                    data = json.loads(rec.sources_text)
                    if isinstance(data, list):
                        count = len(data)
                except Exception:
                    count = 0
            rec.sources_count = count

    @api.model
    def log_query(self, question, answer, session_id, response_time_ms, sources, state='success'):
        """
        Méthode utilitaire appelée par le contrôleur main.py pour enregistrer une requête.
        Exécutée avec sudo() pour garantir la traçabilité même si l'utilisateur n'a pas les droits d'écriture sur les logs.
        """
        sources_str = json.dumps(sources, ensure_ascii=False) if isinstance(sources, (list, dict)) else str(sources or '')
        return self.sudo().create({
            'question': question,
            'answer': answer,
            'user_id': self.env.user.id,
            'company_id': self.env.company.id,
            'session_id': session_id,
            'response_time_ms': response_time_ms,
            'sources_text': sources_str,
            'state': state
        })
