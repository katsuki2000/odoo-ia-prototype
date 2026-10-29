# -*- coding: utf-8 -*-
"""Odoo controller for the MIRO AI assistant: starts questions on the backend and relays their answers."""
import logging
import time
import uuid

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request

from .ask_flow import backend_headers, is_job_id, issue_requester_key, requester_scope, revoke_requester_keys
from .backend_client import BackendError, get_from_backend, post_to_backend

_logger = logging.getLogger(__name__)

BACKEND_REPLY_TIMEOUT_SECONDS = 10
METADATA_FIELDS = ('route', 'confidence')


def _settings_and_secret():
    settings = request.env['miro.ai.settings'].sudo().get_active_settings()
    return settings, settings.get_signing_secret()


def _unreachable_message(api_url):
    return _("Cannot reach the server (%s). Check that the FastAPI backend is running.", api_url)


def _server_error_message(status_code):
    return _("RAG server error (code %s). Please check that the FastAPI service is running.", status_code)


def _log_exchange(question, answer, session_id, elapsed_ms, sources=(), state='success', metadata=None):
    try:
        request.env['miro.ai.log'].log_query(
            question=question,
            answer=answer,
            session_id=session_id,
            response_time_ms=elapsed_ms,
            sources=list(sources),
            state=state,
            metadata=metadata,
        )
    except Exception as log_err:
        _logger.warning("MIRO AI: audit log write failed: %s", log_err)


def _answer_payload(data, session_id):
    return {
        'answer': data.get('answer', _("The backend returned no answer.")),
        'sources': data.get('sources', []),
        'session_id': data.get('session_id', session_id),
        'route': data.get('route'),
        'confidence': data.get('confidence', 1.0),
        'ocr_warning': data.get('ocr_warning', False),
    }


class MiroAiController(http.Controller):

    @http.route('/miro_ai/health', type='json', auth='user', methods=['POST'])
    def health_check(self):
        """Quick health check of the module on the Odoo side."""
        return {
            'status': 'ok',
            'module': 'miro_ai',
            'user_id': request.env.user.id,
            'company_id': request.env.company.id
        }

    @http.route('/miro_ai/ask', type='json', auth='user', methods=['POST'])
    def ask(self, question=None, session_id=None, source_mode=None, **kwargs):
        """Start the question on the backend and return its job id; /miro_ai/ask_result returns the answer."""
        if not question or not question.strip():
            return {'answer': _("Please ask a question."), 'sources': []}
        question = question.strip()
        try:
            settings, secret_key = _settings_and_secret()
        except UserError as err:
            return {'answer': err.args[0], 'sources': []}

        user = request.env.user
        company_id, groups = requester_scope(request.env)
        effective_session = session_id or f"odoo_session_{user.id}_{int(time.time())}"
        job_id = uuid.uuid4().hex
        revoke_requester_keys(request.env)
        headers = backend_headers(secret_key, user, company_id, groups, issue_requester_key(request.env, job_id))
        payload = {
            "job_id": job_id,
            "question": question,
            "session_id": effective_session,
            "user_uid": user.id,
            "company_id": company_id,
            "groups": groups,
        }
        interface_language = request.env.context.get('lang') or user.lang
        if interface_language:
            payload["language"] = interface_language
        # Explicit source chosen in the UI; anything else means automatic routing.
        if source_mode in ("documentation", "system"):
            payload["source_mode"] = source_mode

        api_url = settings.api_url.rstrip('/')
        start_time = time.time()
        try:
            resp = post_to_backend(
                api_url, "/api/v1/ask/jobs", headers, payload, BACKEND_REPLY_TIMEOUT_SECONDS)
            if resp.status_code == 202:
                return {'job_id': job_id, 'session_id': effective_session}
            _logger.error("Backend HTTP error %s: %s", resp.status_code, resp.text)
            if resp.status_code == 429:
                message = _("The assistant is busy answering other questions. Please try again in a moment.")
            else:
                message = _server_error_message(resp.status_code)
        except BackendError as error:
            _logger.exception("Backend unreachable: %s", error)
            message = _unreachable_message(api_url)
        revoke_requester_keys(request.env, job_id)
        _log_exchange(question, message, effective_session, int((time.time() - start_time) * 1000), state='error')
        return {'answer': message, 'sources': []}

    @http.route('/miro_ai/ask_result', type='json', auth='user', methods=['POST'])
    def ask_result(self, job_id=None, session_id=None, **kwargs):
        """Return {'status': 'pending'} while the backend is working, then the answer."""
        if not is_job_id(job_id):
            return {'answer': _("Unknown question."), 'sources': []}
        result = self._fetch_answer(job_id, session_id)
        if result.get('status') != 'pending':
            revoke_requester_keys(request.env, job_id)
        return result

    def _fetch_answer(self, job_id, session_id):
        try:
            settings, secret_key = _settings_and_secret()
        except UserError as err:
            return {'answer': err.args[0], 'sources': []}
        company_id, groups = requester_scope(request.env)
        headers = backend_headers(secret_key, request.env.user, company_id, groups)
        api_url = settings.api_url.rstrip('/')
        try:
            resp = get_from_backend(
                api_url, f"/api/v1/ask/jobs/{job_id}", headers, BACKEND_REPLY_TIMEOUT_SECONDS)
        except BackendError as error:
            _logger.exception("Backend unreachable: %s", error)
            return {'answer': _unreachable_message(api_url), 'sources': []}
        if resp.status_code == 404:
            return {'answer': _("This answer is no longer available. Please ask the question again."), 'sources': []}
        if resp.status_code != 200:
            _logger.error("Backend HTTP error %s: %s", resp.status_code, resp.text)
            return {'answer': _server_error_message(resp.status_code), 'sources': []}

        job = resp.json()
        question, elapsed_ms = job['question'], job['elapsed_ms']
        if job['status'] == 'done':
            payload = _answer_payload(job['result'], session_id)
            _log_exchange(
                question, payload['answer'], payload['session_id'], elapsed_ms, payload['sources'],
                metadata={name: payload[name] for name in METADATA_FIELDS},
            )
            return payload
        if job['status'] == 'pending':
            timeout = settings.request_timeout
            if elapsed_ms <= timeout * 1000:
                return {'status': 'pending'}
            message = _(
                "The server (%(url)s) did not answer within %(timeout)s s: the answer is too slow. "
                "Try again, or increase the timeout in the MIRO AI settings.",
                url=api_url, timeout=timeout,
            )
        else:
            _logger.error("Backend job failed with HTTP %s: %s", job['error_status'], job['error_detail'])
            message = _server_error_message(job['error_status'])
        _log_exchange(question, message, session_id, elapsed_ms, state='error')
        return {'answer': message, 'sources': []}

    @http.route('/miro_ai/sessions', type='json', auth='user', methods=['POST'])
    def sessions(self, limit=30, **kwargs):
        """List the recent conversations visible to the current user."""
        return request.env['miro.ai.log'].get_sessions(limit=limit)

    @http.route('/miro_ai/history', type='json', auth='user', methods=['POST'])
    def history(self, session_id=None, **kwargs):
        """Return the full history of one conversation."""
        if not session_id:
            return []
        return request.env['miro.ai.log'].get_session_history(session_id)
