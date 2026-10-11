# -*- coding: utf-8 -*-
"""
controllers/main.py
===================
Contrôleur Odoo pour MIRO AI Assistant.
Gère la communication FastAPI et la génération JWT.
"""
import base64
import hashlib
import hmac
import json
import logging
import time
from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from .backend_client import BackendError, BackendTimeout, post_with_failover

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
    def ask(self, question=None, session_id=None, source_mode=None, **kwargs):
        """
        Reçoit la question du frontend Odoo, signe un jeton JWT d'authentification
        et interroge le backend FastAPI.
        """
        if not question or not question.strip():
            return {'answer': "Veuillez poser une question.", 'sources': []}

        # Récupération de la configuration
        settings = request.env['miro.ai.settings'].sudo().get_active_settings()
        api_url = settings.api_url.rstrip('/') if settings and settings.api_url else "http://127.0.0.1:8000"
        try:
            secret_key = settings.get_signing_secret()
        except UserError as err:
            return {'answer': f"⚠️ {err.args[0]}", 'sources': []}

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
            # Commit immédiat : l'appel FastAPI ci-dessous déclenche un second
            # aller-retour XML-RPC vers Odoo, qui ouvre son propre curseur.
            # Sous READ COMMITTED, cette seconde transaction ne peut pas voir
            # l'INSERT tant qu'il n'est pas commité ici -- sans ce commit, la
            # clé n'existe pas encore pour la requête RPC et l'authentification
            # échoue systématiquement avec AccessDenied.
            request.env.cr.commit()
        except Exception as key_err:
            rpc_api_key = None
            apikey_record = None
            _logger.error("MIRO AI: échec de génération de la clé API pour uid=%s: %s", uid, key_err)

        # Génération du JWT (sub et uid, company_id, groups, clé API réelle, expiration 5 min)
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
            "groups": groups,
        }
        # Explicit source chosen in the UI; anything else means automatic routing.
        if source_mode in ("documentation", "systeme"):
            payload["source_mode"] = source_mode

        start_time = time.time()
        candidate_urls = [api_url]
        if api_url in ("http://miro_rag:8000", "http://miro_rag:8000/"):
            candidate_urls.append("http://127.0.0.1:8000")
        elif api_url in ("http://127.0.0.1:8000", "http://127.0.0.1:8000/"):
            candidate_urls.append("http://localhost:8000")
        else:
            _logger.debug("MIRO AI: URL candidate unique configurée: %s", api_url)

        timeout = settings.request_timeout
        resp = None
        backend_error = None
        try:
            resp, api_url = post_with_failover(candidate_urls, "/api/v1/ask", headers, payload, timeout)
        except BackendError as error:
            backend_error = error

        try:
            if resp is not None and resp.status_code == 200:
                elapsed_ms = int((time.time() - start_time) * 1000)
                data = resp.json()
                answer_str = data.get('answer', 'Aucune réponse renvoyée par le RAG.')
                sources_list = data.get('sources', [])
                # Métadonnées d'investigation (route, confiance, plan, éléments masqués)
                # nécessaires pour reconstruire fidèlement l'historique (miro.ai.log.get_session_history)
                metadata_dict = {
                    'route': data.get('route'),
                    'confidence': data.get('confidence', 1.0),
                    'evidence_status': data.get('evidence_status'),
                    'resolved_concept': data.get('resolved_concept'),
                    'omitted_for_authorization': data.get('omitted_for_authorization', []),
                    'investigation_plan': data.get('investigation_plan'),
                }
                # Enregistrement du journal d'audit en succès
                try:
                    request.env['miro.ai.log'].sudo().log_query(
                        question=question.strip(),
                        answer=answer_str,
                        session_id=effective_session,
                        response_time_ms=elapsed_ms,
                        sources=sources_list,
                        state='success',
                        metadata=metadata_dict
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
                raise backend_error
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            _logger.exception("Impossible de contacter l'API : %s", e)
            if isinstance(e, BackendTimeout):
                err_msg = (
                    f"Le serveur ({api_url}) n'a pas répondu en {timeout} s : la réponse est trop lente. "
                    "Réessayez, ou augmentez le délai dans Paramètres MIRO AI."
                )
            else:
                err_msg = f"Impossible de contacter le serveur  ({api_url}). Vérifiez que le backend FastAPI est lancé."
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
        finally:
            # La clé API est éphémère et n'a plus de raison d'exister une fois
            # l'appel terminé (succès, erreur HTTP ou exception réseau) : la
            # révoquer réduit la fenêtre d'exposition à une seule requête.
            if apikey_record:
                try:
                    apikey_record._remove()
                    # Commit immédiat, symétrique du commit fait a la
                    # génération : la révocation ne doit pas rester en
                    # attente du commit global de fin de requête d'Odoo,
                    # sinon la clé resterait visible/utilisable par toute
                    # autre transaction jusque-la.
                    request.env.cr.commit()
                except Exception as revoke_err:
                    _logger.warning(
                        "MIRO AI: échec de révocation de la clé API pour uid=%s: %s",
                        uid, revoke_err,
                    )
                    try:
                        request.env.cr.rollback()
                    except Exception:
                        pass

    @http.route('/miro_ai/sessions', type='json', auth='user', methods=['POST'])
    def sessions(self, limit=30, **kwargs):
        """Liste les conversations MIRO AI récentes visibles par l'utilisateur courant."""
        return request.env['miro.ai.log'].get_sessions(limit=limit)

    @http.route('/miro_ai/history', type='json', auth='user', methods=['POST'])
    def history(self, session_id=None, **kwargs):
        """Reconstitue l'historique complet d'une conversation MIRO AI donnée."""
        if not session_id:
            return []
        return request.env['miro.ai.log'].get_session_history(session_id)
