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

        # Génération du JWT (sub et uid, company_id, groups, expiration 1h)
        jwt_payload = {
            "sub": str(uid),
            "uid": uid,
            "company_id": company_id,
            "groups": groups,
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
            "session_id": session_id or f"odoo_session_{uid}_{int(time.time())}",
            "user_uid": uid,
            "company_id": company_id,
            "groups": groups
        }

        try:
            _logger.info("MIRO AI -> Interrogation RAG %s/api/v1/ask pour UID=%s", api_url, uid)
            resp = requests.post(f"{api_url}/api/v1/ask", headers=headers, json=payload, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    'answer': data.get('answer', 'Aucune réponse renvoyée par le RAG.'),
                    'sources': data.get('sources', []),
                    'session_id': data.get('session_id', session_id)
                }
            else:
                _logger.error("Erreur API RAG HTTP %s: %s", resp.status_code, resp.text)
                return {
                    'answer': f"Erreur du serveur RAG (code {resp.status_code}). Veuillez vérifier que le service FastAPI est actif.",
                    'sources': []
                }
        except Exception as e:
            _logger.exception("Impossible de contacter l'API RAG MIRO: %s", e)
            return {
                'answer': f"Impossible de contacter le serveur RAG MIRO ({api_url}). Vérifiez la configuration de l'URL.",
                'sources': []
            }
