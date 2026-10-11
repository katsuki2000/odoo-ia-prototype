# -*- coding: utf-8 -*-
"""
miro_ai_log.py
==============
Modèle de journal d'audit et d'historique des requêtes MIRO AI .
Enregistre chaque question posée, la réponse générée par le RAG, les sources citées,
le temps de réponse et l'utilisateur à l'origine de la requête pour traçabilité et débogage.
"""
import json
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


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
    answer = fields.Text(
        string='Réponse générée',
        readonly=True,
        help='Réponse en Markdown renvoyée par le RAG (convertie en HTML côté frontend par formatMarkdown).'
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
    metadata_text = fields.Text(
        string='Métadonnées (JSON brut)',
        readonly=True,
        help="Route, confiance, statut de preuve, plan d'investigation et élements masqués, sérialisés en JSON."
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
                    else:
                        _logger.warning("miro.ai.log: sources_text pour l'ID %s n'est pas une liste JSON", rec.id)
                        count = 0
                except Exception as e:
                    _logger.warning("miro.ai.log: échec du décodage JSON de sources_text pour l'ID %s: %s", rec.id, e)
                    count = 0
            else:
                count = 0
            rec.sources_count = count

    @api.model
    def log_query(self, question, answer, session_id, response_time_ms, sources, state='success', metadata=None):
        """
        Méthode utilitaire appelée par le contrôleur main.py pour enregistrer une requête.
        Exécutée avec sudo() pour garantir la traçabilité même si l'utilisateur n'a pas les droits d'écriture sur les logs.
        """
        sources_str = json.dumps(sources, ensure_ascii=False) if isinstance(sources, (list, dict)) else str(sources or '')
        metadata_str = json.dumps(metadata, ensure_ascii=False) if isinstance(metadata, dict) else ''
        return self.sudo().create({
            'question': question,
            'answer': answer,
            'user_id': self.env.user.id,
            'company_id': self.env.company.id,
            'session_id': session_id,
            'response_time_ms': response_time_ms,
            'sources_text': sources_str,
            'metadata_text': metadata_str,
            'state': state
        })

    @api.model
    def get_sessions(self, limit=30, scan_limit=1000):
        """
        Liste les sessions de conversation les plus récentes visibles par
        l'utilisateur courant. Non-sudo : le ir.rule existant
        (rule_miro_ai_log_user) filtre déjà sur l'utilisateur, la sécurité
        est donc héritée par construction plutôt que revalidée ici.
        Évite le piège N+1 en calculant les comptages de messages via read_group.
        """
        logs = self.search([], order='create_date desc', limit=scan_limit)
        sessions = []
        seen = set()
        for log in logs:
            session_id = log.session_id
            if not session_id or session_id in seen:
                continue
            seen.add(session_id)
            sessions.append({
                'session_id': session_id,
                'preview': (log.question or '')[:120],
                'last_activity': log.create_date.isoformat() if log.create_date else None,
                'message_count': 0,
            })
            if len(sessions) >= limit:
                break

        target_session_ids = [s['session_id'] for s in sessions]
        if target_session_ids:
            try:
                grouped_counts = self.read_group(
                    [('session_id', 'in', target_session_ids)],
                    ['session_id'],
                    ['session_id']
                )
                counts = {
                    g.get('session_id'): g.get('session_id_count', g.get('__count', 0))
                    for g in grouped_counts
                    if g.get('session_id')
                }
            except Exception as e:
                _logger.warning("miro.ai.log: échec du calcul groupé des sessions: %s", e)
                counts = {}
            for s in sessions:
                s['message_count'] = counts.get(s['session_id'], 0)

        return sessions

    @api.model
    def get_session_history(self, session_id):
        """
        Reconstitue l'historique complet d'une session sous forme de liste
        ordonnée de tours question/réponse. Non-sudo, même raisonnement de
        sécurité héritée que get_sessions().
        """
        if not session_id:
            return []
        logs = self.search([('session_id', '=', session_id)], order='create_date asc')
        history = []
        for log in logs:
            metadata = {}
            if log.metadata_text:
                try:
                    metadata = json.loads(log.metadata_text)
                except Exception as e:
                    _logger.warning("miro.ai.log: échec parsing metadata_text (id=%s): %s", log.id, e)
                    metadata = {}
            else:
                metadata = {}

            sources = []
            if log.sources_text:
                try:
                    sources = json.loads(log.sources_text)
                except Exception as e:
                    _logger.warning("miro.ai.log: échec parsing sources_text (id=%s): %s", log.id, e)
                    sources = []
            else:
                sources = []

            history.append({
                'question': log.question,
                'answer': log.answer,
                'sources': sources,
                'state': log.state,
                'create_date': log.create_date.isoformat() if log.create_date else None,
                'route': metadata.get('route'),
                'confidence': metadata.get('confidence'),
                'evidence_status': metadata.get('evidence_status'),
                'investigation_plan': metadata.get('investigation_plan'),
                'omitted_for_authorization': metadata.get('omitted_for_authorization'),
            })
        return history
