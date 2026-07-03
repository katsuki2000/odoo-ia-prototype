# -*- coding: utf-8 -*-
"""
chat.py — JSON controllers for the AI ERP chat interface.

Endpoints:
  POST /ai_erp/chat          — send a message, get a response
  POST /ai_erp/conversation  — create a new conversation
  GET  /ai_erp/conversations — list the current user's conversations
  POST /ai_erp/ingest/directory — trigger code directory ingestion
"""
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class AiErpChatController(http.Controller):

    # ── Chat endpoint ──────────────────────────────────────────────────────────

    @http.route(
        '/ai_erp/chat',
        type='json',
        auth='user',
        methods=['POST'],
        csrf=True,
    )
    def chat(self, conversation_id=None, message='', **kwargs):
        """
        Send a user message and return the AI response.

        Request body (JSON):
          conversation_id : int | None  — existing conversation; if None, creates a new one
          message         : str         — the user question

        Response (JSON):
          {
            "conversation_id": int,
            "message_id": int,
            "content": str,
            "pipeline_used": str,
            "citations": [...],
            "duration_ms": int,
            "error": str | null
          }
        """
        env = request.env

        if not message or not message.strip():
            return {'error': 'Message vide.'}

        # Get or create conversation
        if conversation_id:
            conv = env['ai.conversation'].browse(int(conversation_id))
            if not conv.exists() or conv.user_id.id != env.user.id:
                return {'error': 'Conversation introuvable ou accès refusé.'}
        else:
            config = env['ai.config'].get_active_config()
            conv = env['ai.conversation'].create({
                'name': message[:60] + ('…' if len(message) > 60 else ''),
                'config_id': config.id if config else False,
            })

        # Save user message
        env['ai.message'].create({
            'conversation_id': conv.id,
            'role': 'user',
            'content': message,
        })

        # Build conversation history for the router
        history = [
            {'role': m.role, 'content': m.content}
            for m in conv.message_ids
            if m.role in ('user', 'assistant')
        ]

        # Get active config and run router
        config = env['ai.config'].get_active_config()
        if not config:
            return {
                'conversation_id': conv.id,
                'error': (
                    'Aucune configuration IA active. '
                    'Veuillez configurer le module dans IA ERP > Configuration.'
                ),
            }

        try:
            from ..services.router import RouterService
            router = RouterService(env, config)
            result = router.answer(message, history=history[:-1])  # exclude last user msg
        except Exception as exc:
            _logger.exception('Chat routing error')
            return {
                'conversation_id': conv.id,
                'error': f'Erreur du moteur IA : {exc}',
            }

        # Save assistant message with full metadata
        ai_msg = env['ai.message'].create({
            'conversation_id': conv.id,
            'role': 'assistant',
            'content': result.content,
            'pipeline_used': result.pipeline_used,
            'tool_called': result.tool_called or False,
            'citations': json.dumps(result.citations, ensure_ascii=False),
            'tokens_prompt': result.tokens_prompt,
            'tokens_completion': result.tokens_completion,
            'duration_ms': result.duration_ms,
        })

        return {
            'conversation_id': conv.id,
            'message_id': ai_msg.id,
            'content': result.content,
            'pipeline_used': result.pipeline_used,
            'tool_called': result.tool_called or '',
            'citations': result.citations,
            'tokens_prompt': result.tokens_prompt,
            'tokens_completion': result.tokens_completion,
            'duration_ms': result.duration_ms,
            'error': result.error or None,
        }

    # ── Conversation management ────────────────────────────────────────────────

    @http.route(
        '/ai_erp/conversations',
        type='json',
        auth='user',
        methods=['GET', 'POST'],
        csrf=True,
    )
    def list_conversations(self, **kwargs):
        """Return the current user's conversations (newest first)."""
        env = request.env
        convs = env['ai.conversation'].search(
            [('user_id', '=', env.user.id)],
            order='create_date desc',
            limit=50,
        )
        return {
            'conversations': [
                {
                    'id': c.id,
                    'name': c.name,
                    'message_count': c.message_count,
                    'create_date': c.create_date.isoformat() if c.create_date else '',
                }
                for c in convs
            ]
        }

    @http.route(
        '/ai_erp/conversation/<int:conv_id>/messages',
        type='json',
        auth='user',
        methods=['GET', 'POST'],
        csrf=True,
    )
    def get_messages(self, conv_id, **kwargs):
        """Return all messages in a conversation."""
        env = request.env
        conv = env['ai.conversation'].browse(conv_id)
        if not conv.exists() or conv.user_id.id != env.user.id:
            return {'error': 'Conversation introuvable.'}
        return {
            'conversation_id': conv_id,
            'name': conv.name,
            'messages': [
                {
                    'id': m.id,
                    'role': m.role,
                    'content': m.content,
                    'pipeline_used': m.pipeline_used or '',
                    'citations': json.loads(m.citations or '[]'),
                    'duration_ms': m.duration_ms,
                    'create_date': m.create_date.isoformat() if m.create_date else '',
                }
                for m in conv.message_ids
            ],
        }

    # ── Ingestion helpers ──────────────────────────────────────────────────────

    @http.route(
        '/ai_erp/ingest/directory',
        type='json',
        auth='user',
        methods=['POST'],
        csrf=True,
    )
    def ingest_directory(self, directory='', **kwargs):
        """
        Trigger ingestion of all .py and .xml files in *directory*.
        Requires the user to be an Odoo administrator.
        """
        env = request.env
        if not env.user.has_group('base.group_system'):
            return {'error': 'Accès refusé. Réservé aux administrateurs.'}
        if not directory:
            return {'error': 'Paramètre `directory` requis.'}
        try:
            from ..services.ingestion import IngestionService
            svc = IngestionService(env)
            result = svc.ingest_code_directory(directory)
            return result
        except Exception as exc:
            _logger.exception('Directory ingestion error')
            return {'error': str(exc)}
