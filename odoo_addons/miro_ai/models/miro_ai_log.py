# -*- coding: utf-8 -*-
"""Audit log and history of the MIRO AI requests: question, answer, sources, response time, requester."""
import json
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MiroAiLog(models.Model):
    _name = 'miro.ai.log'
    _description = 'MIRO AI - RAG Request Audit Log'
    _order = 'create_date desc, id desc'
    _rec_name = 'question'

    question = fields.Text(
        string='Question asked',
        required=True,
        readonly=True,
        help='Raw text of the question the user sent to the RAG.'
    )
    answer = fields.Text(
        string='Generated answer',
        readonly=True,
        help='Markdown answer returned by the assistant.'
    )
    user_id = fields.Many2one(
        'res.users',
        string='User',
        default=lambda self: self.env.user,
        required=True,
        readonly=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        readonly=True
    )
    session_id = fields.Char(
        string='Session ID',
        readonly=True,
        index=True,
        help='Unique identifier of the RAG discussion session.'
    )
    response_time_ms = fields.Integer(
        string='Response time (ms)',
        readonly=True,
        help='Time taken to query the FastAPI RAG backend, in milliseconds.'
    )
    sources_text = fields.Text(
        string='Sources (raw JSON)',
        readonly=True,
        help='Raw list of the cited documents or ORM excerpts.'
    )
    sources_count = fields.Integer(
        string='Sources count',
        compute='_compute_sources_count',
        store=True,
        help='Number of documentary/code sources cited by the answer.'
    )
    metadata_text = fields.Text(
        string='Metadata (raw JSON)',
        readonly=True,
        help="Route, confidence, evidence status, investigation plan and omitted items, serialized as JSON."
    )
    state = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error')
    ], string='Status', default='success', readonly=True, index=True)

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
                        _logger.warning("miro.ai.log: sources_text of id %s is not a JSON list", rec.id)
                        count = 0
                except Exception as e:
                    _logger.warning("miro.ai.log: JSON decoding of sources_text failed for id %s: %s", rec.id, e)
                    count = 0
            else:
                count = 0
            rec.sources_count = count

    @api.model
    def log_query(self, question, answer, session_id, response_time_ms, sources, state='success', metadata=None):
        """Record one request. Elevated so the audit trail is kept even without write access to the log."""
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
        List the most recent conversations visible to the current user. Not elevated: the
        rule_miro_ai_log_user record rule already filters on the user. Message counts come
        from a single read_group to avoid N+1 queries.
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
                _logger.warning("miro.ai.log: grouped session count failed: %s", e)
                counts = {}
            for s in sessions:
                s['message_count'] = counts.get(s['session_id'], 0)

        return sessions

    @api.model
    def get_session_history(self, session_id):
        """Rebuild the full history of a session as an ordered list of question/answer turns (not elevated, like get_sessions)."""
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
                    _logger.warning("miro.ai.log: metadata_text parsing failed (id=%s): %s", log.id, e)
                    metadata = {}
            else:
                metadata = {}

            sources = []
            if log.sources_text:
                try:
                    sources = json.loads(log.sources_text)
                except Exception as e:
                    _logger.warning("miro.ai.log: sources_text parsing failed (id=%s): %s", log.id, e)
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
