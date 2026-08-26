# -*- coding: utf-8 -*-
"""
controllers/main.py
===================
Contrôleur Odoo pour MIRO AI Assistant.
Gère la communication RAG/FastAPI et la génération JWT.
"""
import base64
import hashlib
import hmac
import json
import logging
import time
import requests
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


def generate_jwt_token(payload_dict, secret_key):
    """Génère un jeton JWT HS256 valide en pur Python standard."""
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
        """Vérification rapide de la santé du module MIRO AI côté Odoo."""
        return {
            'status': 'ok',
            'module': 'miro_ai',
            'user_id': request.env.user.id,
            'company_id': request.env.company.id
        }

    @http.route('/miro_ai/ask', type='json', auth='user', methods=['POST'])
    def ask(self, question=None, session_id=None, **kwargs):
        """
        Reçoit la question du frontend Odoo, signe un jeton JWT d'authentification
        et interroge le backend FastAPI MIRO RAG.
        """
        if not question or not question.strip():
            return {'answer': "Veuillez poser une question.", 'sources': []}

        # Récupération de la configuration
        settings = request.env['miro.ai.settings'].sudo().get_active_settings()
        api_url = settings.api_url.rstrip('/') if settings and settings.api_url else "http://127.0.0.1:8000"
        secret_key = settings.api_token if settings and settings.api_token else "default_insecure_secret_for_dev"

        # Métadonnées utilisateur courant Odoo
        user = request.env.user
        uid = user.id
        company_id = request.env.company.id
        groups = [g.id for g in user.groups_id]
        effective_session = session_id or f"odoo_session_{uid}_{int(time.time())}"

        # Clé API Odoo réelle et éphémère, générée pour CET utilisateur précis
        # (self-service : un utilisateur peut toujours générer ses propres clés,
        # pas besoin de sudo()). C'est cette clé -- pas le mot de passe admin --
        # que le backend FastAPI utilisera pour les appels XML-RPC, afin que les
        # droits réels du demandeur (ir.rule, ACL) s'appliquent réellement côté
        # Odoo au lieu de tourner en pratique avec les droits admin. Révoquée
        # dans le bloc finally ci-dessous, quoi qu'il arrive.
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
        except Exception as key_err:
            _logger.error("MIRO AI: échec de génération de la clé API pour uid=%s: %s", uid, key_err)

        # Génération du JWT (sub et uid, company_id, groups, clé API réelle, expiration 1h)
        jwt_payload = {
            "sub": str(uid),
            "uid": uid,
            "login": user.login,
            "company_id": company_id,
            "groups": groups,
            "api_key": rpc_api_key,
            "exp": int(time.time()) + 3600
        }
        jwt_token = generate_jwt_token(jwt_payload, secret_key)

        # Envoi au serveur RAG
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "question": question.strip(),
            "session_id": effective_session,
            "user_uid": uid,
            "company_id": company_id,
            "groups": groups
        }

        start_time = time.time()
        candidate_urls = [api_url]
        if api_url in ("http://miro_rag:8000", "http://miro_rag:8000/"):
            candidate_urls.append("http://127.0.0.1:8000")
        elif api_url in ("http://127.0.0.1:8000", "http://127.0.0.1:8000/"):
            candidate_urls.append("http://localhost:8000")

        resp = None
        last_error = None
        for candidate_url in candidate_urls:
            try:
                _logger.info("MIRO AI -> Interrogation RAG %s/api/v1/ask pour UID=%s", candidate_url, uid)
                resp = requests.post(f"{candidate_url}/api/v1/ask", headers=headers, json=payload, timeout=60)
                if resp:
                    api_url = candidate_url
                    break
            except Exception as conn_err:
                _logger.warning("MIRO AI: tentative vers %s échouée: %s", candidate_url, conn_err)
                last_error = conn_err

        try:
            if resp is not None and resp.status_code == 200:
                elapsed_ms = int((time.time() - start_time) * 1000)
                data = resp.json()
                answer_str = data.get('answer', 'Aucune réponse renvoyée par le RAG.')
                sources_list = data.get('sources', [])
                # Enregistrement du journal d'audit en succès
                try:
                    request.env['miro.ai.log'].sudo().log_query(
                        question=question.strip(),
                        answer=answer_str,
                        session_id=effective_session,
                        response_time_ms=elapsed_ms,
                        sources=sources_list,
                        state='success'
                    )
                except Exception as log_err:
                    _logger.warning("Erreur lors de l'enregistrement du journal MIRO AI: %s", log_err)

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
                err_msg = f"Erreur du serveur RAG (code {resp.status_code}). Veuillez vérifier que le service FastAPI est actif."
                _logger.error("Erreur API RAG HTTP %s: %s", resp.status_code, resp.text)
                try:
                    request.env['miro.ai.log'].sudo().log_query(
                        question=question.strip(),
                        answer=err_msg,
                        session_id=effective_session,
                        response_time_ms=elapsed_ms,
                        sources=[],
                        state='error'
                    )
                except Exception as log_err:
                    _logger.warning("Erreur lors de l'enregistrement du journal MIRO AI: %s", log_err)

                return {
                    'answer': err_msg,
                    'sources': []
                }
            else:
                raise last_error or Exception("Serveur RAG inaccessible")
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            _logger.exception("Impossible de contacter l'API RAG MIRO: %s", e)
            err_msg = f"Impossible de contacter le serveur RAG MIRO ({api_url}). Vérifiez que le backend FastAPI est lancé (ex: uvicorn api.main:app --port 8000)."
            try:
                request.env['miro.ai.log'].sudo().log_query(
                    question=question.strip(),
                    answer=err_msg,
                    session_id=effective_session,
                    response_time_ms=elapsed_ms,
                    sources=[],
                    state='error'
                )
            except Exception as log_err:
                _logger.warning("Erreur lors de l'enregistrement du journal MIRO AI: %s", log_err)

            return {
                'answer': err_msg,
                'sources': []
            }

            return {
                'answer': err_msg,
                'sources': []
            }
        finally:
            # La clé API est éphémère et n'a plus de raison d'exister une fois
            # l'appel terminé (succès, erreur HTTP ou exception réseau) : la
            # révoquer réduit la fenêtre d'exposition à une seule requête.
            if apikey_record:
                try:
                    apikey_record._remove()
                except Exception as revoke_err:
                    _logger.warning(
                        "MIRO AI: échec de révocation de la clé API pour uid=%s: %s",
                        uid, revoke_err,
                    )
