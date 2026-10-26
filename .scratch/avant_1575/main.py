# -*- coding: utf-8 -*-
"""Odoo controller for the MIRO AI assistant: signs the requester's JWT and calls the backend."""
import base64
import hashlib
import hmac
import json
import logging
import time
from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request

from .backend_client import BackendError, BackendTimeout, candidate_urls_for, post_with_failover

_logger = logging.getLogger(__name__)


def generate_jwt_token(payload_dict, secret_key):
    """Build an HS256 JWT with the standard library only."""
    header = {"alg": "HS256", "typ": "JWT"}

    def b64url_encode(data_bytes):
        return base64.urlsafe_b64encode(data_bytes).rstrip(b'=').decode('ascii')

    encoded_header = b64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))
    encoded_payload = b64url_encode(json.dumps(payload_dict, separators=(',', ':')).encode('utf-8'))

    signing_input = f"{encoded_header}.{encoded_payload}".encode('ascii')
    signature = hmac.new(secret_key.encode('utf-8'), signing_input, hashlib.sha256).digest()
    encoded_signature = b64url_encode(signature)

    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


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
        """Receive the question from the Odoo frontend, sign the requester's JWT and query the backend."""
        if not question or not question.strip():
            return {'answer': _("Please ask a question."), 'sources': []}

        settings = request.env['miro.ai.settings'].sudo().get_active_settings()
        api_url = settings.api_url.rstrip('/')
        try:
            secret_key = settings.get_signing_secret()
        except UserError as err:
            return {'answer': err.args[0], 'sources': []}

        user = request.env.user
        uid = user.id
        company_id = request.env.company.id
        groups = [g.id for g in user.groups_id]
        effective_session = session_id or f"odoo_session_{uid}_{int(time.time())}"

        # Ephemeral Odoo API key for THIS user (self-service, no elevation needed). The backend
        # uses it for its XML-RPC calls so the requester's own ACL and record rules apply
        # instead of admin rights. It is revoked in the finally block below.
        apikeys_model = request.env['res.users.apikeys']
        key_name = f"MIRO AI - {effective_session}"
        rpc_api_key = None
        apikey_record = None
        try:
            rpc_api_key = apikeys_model._generate(None, key_name)
            apikey_record = apikeys_model.search(
                [('user_id', '=', uid), ('name', '=', key_name)],
                order='create_date desc', limit=1,
            )
            # Commit now: the backend calls Odoo back over XML-RPC with its own cursor, and under
            # READ COMMITTED it cannot see an uncommitted key (authentication would fail).
            request.env.cr.commit()
        except Exception as key_err:
            rpc_api_key = None
            apikey_record = None
            _logger.error("MIRO AI: API key generation failed for uid=%s: %s", uid, key_err)

        # JWT valid for 5 minutes
        jwt_payload = {
            "sub": str(uid),
            "uid": uid,
            "login": user.login,
            "company_id": company_id,
            "groups": groups,
            "api_key": rpc_api_key,
            "is_admin": user.has_group('base.group_system'),
            "exp": int(time.time()) + 300
        }
        jwt_token = generate_jwt_token(jwt_payload, secret_key)

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "question": question.strip(),
            "session_id": effective_session,
            "user_uid": uid,
            "company_id": company_id,
            "groups": groups,
        }
        interface_language = request.env.context.get('lang') or user.lang
        if interface_language:
            payload["language"] = interface_language
        # Explicit source chosen in the UI; anything else means automatic routing.
        if source_mode in ("documentation", "systeme"):
            payload["source_mode"] = source_mode

        start_time = time.time()
        timeout = settings.request_timeout
        resp = None
        backend_error = None
        try:
            resp, api_url = post_with_failover(candidate_urls_for(api_url), "/api/v1/ask", headers, payload, timeout)
        except BackendError as error:
            backend_error = error

        try:
            if resp is not None and resp.status_code == 200:
                elapsed_ms = int((time.time() - start_time) * 1000)
                data = resp.json()
                answer_str = data.get('answer', _("The backend returned no answer."))
                sources_list = data.get('sources', [])
                # Investigation metadata needed to rebuild the history (miro.ai.log.get_session_history)
                metadata_dict = {
                    'route': data.get('route'),
                    'confidence': data.get('confidence', 1.0),
                    'evidence_status': data.get('evidence_status'),
                    'resolved_concept': data.get('resolved_concept'),
                    'omitted_for_authorization': data.get('omitted_for_authorization', []),
                    'investigation_plan': data.get('investigation_plan'),
                }
                try:
                    request.env['miro.ai.log'].log_query(
                        question=question.strip(),
                        answer=answer_str,
                        session_id=effective_session,
                        response_time_ms=elapsed_ms,
                        sources=sources_list,
                        state='success',
                        metadata=metadata_dict
                    )
                except Exception as log_err:
                    _logger.warning("MIRO AI: audit log write failed: %s", log_err)

                return {
                    'answer': answer_str,
                    'sources': sources_list,
                    'session_id': data.get('session_id', effective_session),
                    'route': data.get('route'),
                    'confidence': data.get('confidence', 1.0),
                    'ocr_warning': data.get('ocr_warning', False),
                    'evidence_status': data.get('evidence_status'),
                    'resolved_concept': data.get('resolved_concept'),
                    'omitted_for_authorization': data.get('omitted_for_authorization', []),
                    'investigation_plan': data.get('investigation_plan'),
                }
            elif resp is not None:
                elapsed_ms = int((time.time() - start_time) * 1000)
                err_msg = _(
                    "RAG server error (code %s). Please check that the FastAPI service is running.",
                    resp.status_code,
                )
                _logger.error("Backend HTTP error %s: %s", resp.status_code, resp.text)
                try:
                    request.env['miro.ai.log'].log_query(
                        question=question.strip(),
                        answer=err_msg,
                        session_id=effective_session,
                        response_time_ms=elapsed_ms,
                        sources=[],
                        state='error'
                    )
                except Exception as log_err:
                    _logger.warning("MIRO AI: audit log write failed: %s", log_err)

                return {
                    'answer': err_msg,
                    'sources': []
                }
            else:
                raise backend_error
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            _logger.exception("Backend unreachable: %s", e)
            if isinstance(e, BackendTimeout):
                err_msg = _(
                    "The server (%(url)s) did not answer within %(timeout)s s: the answer is too slow. "
                    "Try again, or increase the timeout in the MIRO AI settings.",
                    url=api_url, timeout=timeout,
                )
            else:
                err_msg = _(
                    "Cannot reach the server (%s). Check that the FastAPI backend is running.", api_url,
                )
            try:
                request.env['miro.ai.log'].log_query(
                    question=question.strip(),
                    answer=err_msg,
                    session_id=effective_session,
                    response_time_ms=elapsed_ms,
                    sources=[],
                    state='error'
                )
            except Exception as log_err:
                _logger.warning("MIRO AI: audit log write failed: %s", log_err)

            return {
                'answer': err_msg,
                'sources': []
            }
        finally:
            # The key is only needed for this request: revoke it whatever the outcome.
            if apikey_record:
                try:
                    apikey_record._remove()
                    # Commit now so the revocation does not wait for the end of the request.
                    request.env.cr.commit()
                except Exception as revoke_err:
                    _logger.warning(
                        "MIRO AI: API key revocation failed for uid=%s: %s",
                        uid, revoke_err,
                    )
                    try:
                        request.env.cr.rollback()
                    except Exception as rollback_err:
                        _logger.warning("MIRO AI: rollback after revocation failed for uid=%s: %s", uid, rollback_err)

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
