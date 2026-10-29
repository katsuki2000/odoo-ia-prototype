# -*- coding: utf-8 -*-
"""Audit log and history of the MIRO AI requests: question, answer, sources, response time, requester."""
import json
import logging
from odoo import models, fields, api
from odoo.osv.expression import OR

_logger = logging.getLogger(__name__)
MAX_SESSION_LIST_LIMIT = 1000


def _parse_json_field(value, field_name, record_id, expected_type, default):
    if not value:
        return default
    try:
        result = json.loads(value)
    except (TypeError, ValueError) as error:
        _logger.warning("miro.ai.log: %s parsing failed (id=%s): %s", field_name, record_id, error)
        return default
    if not isinstance(result, expected_type):
        _logger.warning("miro.ai.log: %s of id %s is not a JSON %s", field_name, record_id, expected_type.__name__)
        return default
    return result


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
        help="Route and confidence of the answer, serialized as JSON."
    )
    state = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error')
    ], string='Status', default='success', readonly=True, index=True)

    @api.depends('sources_text')
    def _compute_sources_count(self):
        for rec in self:
            sources = _parse_json_field(rec.sources_text, 'sources_text', rec.id, list, [])
            rec.sources_count = len(sources)

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
    def get_sessions(self, limit=30):
        """
        List recent conversations visible to the current user. Grouping and counts stay in
        the ORM; record rules apply to both queries.
        """
        if type(limit) is not int or limit < 1:
            raise ValueError('limit must be a positive integer.')
        limit = min(limit, MAX_SESSION_LIST_LIMIT)
        groups = self.read_group(
            [('session_id', '!=', False)],
            ['session_id', 'create_date:max'],
            ['session_id'],
            limit=limit,
            orderby='create_date desc',
        )
        if not groups:
            return []

        latest_domains = [
            [('session_id', '=', group['session_id']), ('create_date', '=', group['create_date'])]
            for group in groups
        ]
        latest_logs = self.search(OR(latest_domains), order='create_date desc, id desc')
        latest_by_session = {}
        for log in latest_logs:
            latest_by_session.setdefault(log.session_id, log)

        return [
            {
                'session_id': group['session_id'],
                'preview': (latest_by_session[group['session_id']].question or '')[:120],
                'last_activity': group['create_date'].isoformat() if group.get('create_date') else None,
                'message_count': group.get('session_id_count', group.get('__count', 0)),
            }
            for group in groups
            if group.get('session_id') in latest_by_session
        ]

    @api.model
    def get_session_history(self, session_id):
        """Rebuild the full history of a session as an ordered list of question/answer turns (not elevated, like get_sessions)."""
        if not session_id:
            return []
        logs = self.search([('session_id', '=', session_id)], order='create_date asc')
        history = []
        for log in logs:
            metadata = _parse_json_field(log.metadata_text, 'metadata_text', log.id, dict, {})
            sources = _parse_json_field(log.sources_text, 'sources_text', log.id, list, [])
            history.append({
                'question': log.question,
                'answer': log.answer,
                'sources': sources,
                'state': log.state,
                'create_date': log.create_date.isoformat() if log.create_date else None,
                'route': metadata.get('route'),
                'confidence': metadata.get('confidence'),
            })
        return history
